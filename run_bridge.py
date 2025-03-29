#!/usr/bin/env python3
import asyncio
from collections import defaultdict
import logging
import os
import sys

from opentelemetry.proto.collector.metrics.v1 import (
    metrics_service_pb2,
    metrics_service_pb2_grpc,
)
import grpc
from google.protobuf.json_format import MessageToJson
import pandas as pd

# This is ugly at this point of the file, amongst imports,
# but we want to set up the logging *before* dataClay library configures it.
logging.basicConfig(level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper()))
dclogger = logging.getLogger("dataclay")
dclogger.setLevel(logging.INFO)
grpclogger = logging.getLogger("grpc")
grpclogger.setLevel(logging.INFO)
logger = logging.getLogger("otlp-dataclay-bridge")

from dataclay import Client
from dataclay.exceptions import DataClayException
from dataclay.event_loop import get_dc_event_loop

from icos_fl.utils.fetcher import BridgeConfiguration
from icos_fl.utils.fetcher import TimeSeriesData


config = None
tsd = None

class MetricsServicer(metrics_service_pb2_grpc.MetricsServiceServicer):
    def __init__(self, main_loop, work_queue) -> None:
        super().__init__()
        self.main_loop = main_loop
        self.work_queue = work_queue

    async def Export(
        self,
        request: metrics_service_pb2.ExportMetricsServiceRequest,
        context: grpc.aio.ServicerContext,
    ):
        logger.info("Attending Export request")
        response = metrics_service_pb2.ExportMetricsServiceResponse()

        self.main_loop.call_soon_threadsafe(
            self.work_queue.put_nowait, request.resource_metrics
        )

        return response


async def prepare_server(main_loop, work_queue):
    logger.info("Creating gRPC server to listen for OTLP data")
    # Create a gRPC server
    grpc_server = grpc.aio.server()
    metrics_service_pb2_grpc.add_MetricsServiceServicer_to_server(
        MetricsServicer(main_loop, work_queue), grpc_server
    )

    grpc_server.add_insecure_port("[::]:4317")
    await grpc_server.start()

    logger.info("Server started")
    await grpc_server.wait_for_termination()


async def attend_metrics(queue):
    while True:
        resource_metrics = await queue.get()

        aggregation = defaultdict(dict)

        logger.info("Received #%d resource metrics", len(resource_metrics))

        for rm in resource_metrics:
            attributes = {
                entry.key: entry.value.string_value for entry in rm.resource.attributes
            }
            logger.debug(
                "Processing resource with the following attributes: %s", attributes
            )

            for rc in config.get_matching_res_configs(attributes):
                # Cache these values
                rc_name = rc.name
                metric_names = rc.metric_names

                logger.info(
                    "Resource matches configuration %s, adding metrics to DataFrame",
                    rc.name,
                )

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Resource metrics content:\n%s", MessageToJson(rm))

                for sm in rm.scope_metrics:
                    for m in sm.metrics:
                        logger.debug("Metric: %s", m.name)
                        if m.name not in metric_names:
                            logger.debug(
                                "Metric %s not in configuration, skipping", m.name
                            )
                            continue
                        logger.debug("Processing metric %s", m.name)

                        if m.HasField("gauge"):
                            logger.debug("Found a gauge metric")
                            print(type(m.gauge))
                            values = {p.time_unix_nano: p.as_double for p in m.gauge.data_points}
                        elif m.HasField("sum"):
                            logger.debug("Found a sum metric")
                            values = [(p.time_unix_nano, p.as_double) for p in m.sum.data_points]
                        # elif m.HasField("histogram"):
                        #     logger.debug("Found a histogram metric")
                        #     values = ...
                        # elif m.HasField("exponential_histogram"):
                        #     logger.debug("Found an exponential histogram metric")
                        #     values = ...
                        # elif m.HasField("summary"):
                        #     logger.debug("Found a summary metric")
                        #     values = ...
                        else:
                            logger.debug("Unknown metric type in metric: %s", m.name)
                            logger.warning("Skipping unknown metric")
                            continue

                        aggregation[(rc_name, m.name)].update(values)
        
        df_series = dict()
        for key, values in aggregation.items():
            df_series[".".join(key)] = pd.Series(values)

        df = pd.DataFrame(df_series)
        logger.debug("Resulting DataFrame:\n%s", df)
        tsd.add_dataframe(df)


async def main():
    logger.info("Starting OTLP to dataClay bridge")

    logger.info("Establishing connection to dataClay")
    dc_proxy_host = os.getenv("DATACLAY_PROXY_HOST", "127.0.0.1")
    dc_proxy_port = int(os.getenv("DATACLAY_PROXY_PORT", "8676"))
    client = Client(proxy_host=dc_proxy_host, proxy_port=dc_proxy_port, dataset="admin")
    client.start()

    global config
    global tsd
    try:
        logger.info(
            "Retrieving bridge configuration from dataClay (persistent storage)"
        )
        config = await BridgeConfiguration.a_get_by_alias(
            os.getenv("BRIDGE_CONFIGURATION_ALIAS", "bridge_config")
        )
    except DataClayException:
        logger.warning("Bridge configuration not found, aborting")
        sys.exit(1)

    try:
        tsd = TimeSeriesData.get_by_alias(os.getenv("TIMESERIES_ALIAS", "timeseries"))
    except DataClayException:
        tsd = TimeSeriesData()
        tsd.make_persistent(alias=os.getenv("TIMESERIES_ALIAS", "timeseries"))

    main_loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    f = asyncio.run_coroutine_threadsafe(
        prepare_server(main_loop, queue), get_dc_event_loop()
    )

    main_loop.create_task(attend_metrics(queue))
    await asyncio.wrap_future(f)


if __name__ == "__main__":
    asyncio.run(main())
