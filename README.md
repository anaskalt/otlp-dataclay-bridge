# OpenTelemetry to dataClay bridge

This project creates a bridge between OpenTelemetry metrics and dataClay, allowing you to collect, store, and process system metrics in real-time. It's designed to work with Scaphandre for power consumption, CPU usage, and memory usage monitoring.

## Quick Start

### Requirements
- Ubuntu 20.04 or newer (x86)
- Docker and Docker Compose installed

### Setup and Run
1. Start all services with a single command:
   ```bash
   docker compose up -d
   ```
   This will start all necessary components: Scaphandre, OpenTelemetry collector, dataClay services, and the bridge.

2. Create a virtual environment and install requirements to run the consumer:
   ```bash
   python -m venv otlp_bridge_venv
   source otlp_bridge_venv/bin/activate
   pip install -r requirements.txt
   ```

3. Run the consumer script to monitor the data:
   ```bash
   python consumer.py
   ```

## Architecture Components

The system now runs entirely within Docker containers, with a streamlined workflow:

- **Scaphandre**: Collects power, CPU, and memory metrics from the host
- **OpenTelemetry Collector**: Scrapes metrics from Scaphandre (every 3s) and batches them (every 180s)
- **DataClay Services**: Redis, Metadata Service, Backend, and Proxy
- **Bridge**: Connects OpenTelemetry to DataClay (automatically configured)
- **TimeSeriesData**: Stores metrics in a unified sliding window (300 rows, ~15 minutes of history)

## Data Flow

```
  +---------------+     scrapes     +------------------+     batches     +-----------------+
  |  Scaphandre   |<---------------|  OTel Prometheus  |--------------->|  OTel Exporter  |
  |  (HTTP:8080)  |    every 3s    |     Receiver      |   for 180s     |   (gRPC:4317)   |
  +---------------+                +------------------+                  +---------+-------+
                                                                                   |
                                                                                   v
  +-----------------+                +------------------------+     stores    +----------------+
  |  Bridge Config  |<---------------|      OTLP-Bridge      |-------------->| TimeSeriesData |
  |  (in dataClay)  |   configures   |                       |    as unified | (sliding window)|
  +-----------------+                +------------------------+    DataFrame  +-------+--------+
                                                                                     |
                                                                                     v
                                     +------------------------+     reads     +----------------+
                                     |    Consumer Script     |<--------------|  300 rows of   |
                                     | (runs in local Python) |    processes  |  metric data   |
                                     +------------------------+    displays   +----------------+
```

## Monitoring Data

The `consumer.py` script provides:
- Real-time monitoring of the unified DataFrame
- Statistics on power consumption, CPU usage, and RAM usage
- Information about new data being added and old data being removed
- Time range and duration information

## Configuration Details

### OpenTelemetry Configuration
The configuration for the OpenTelemetry collector (`otel-config.yaml`):
- Scrape interval: 3 seconds
- Batch timeout: 180 seconds (3 minutes)

### TimeSeriesData Configuration
The sliding window in dataClay:
- Maintains 300 most recent data points (~15 minutes with 3s intervals)
- Automatically removes oldest data when new data arrives
- Stores data in a unified DataFrame for easier access

## Advanced Usage

You can customize the setup by modifying:
- `otel-config.yaml` - Change scrape intervals or batching settings
- `bridgeConfig.py` - Configure different metrics to collect
- `model/timeseries.py` - Adjust the sliding window size

## Data Format

The consumer processes raw metrics into a standardized DataFrame with columns:
- `timestamp` - Unix timestamp in seconds
- `power_consumption` - Power in watts (converted from microwatts)
- `cpu_usage` - CPU load average
- `ram_usage` - RAM usage in MB (calculated as total - available)
