#!/usr/bin/env python3

import os
import time
import operator
import asyncio
from dataclay import Client
from dataclay.exceptions import DataClayException
from icos_fl.utils.fetcher import BridgeConfiguration, ResourceConfiguration, MatchRule

async def main():
    # Connect to dataClay
    print("Connecting to dataClay...")
    dc_proxy_host = os.getenv("DATACLAY_PROXY_HOST", "127.0.0.1")
    dc_proxy_port = int(os.getenv("DATACLAY_PROXY_PORT", "8676"))
    client = Client(proxy_host=dc_proxy_host, proxy_port=dc_proxy_port, dataset="admin")
    client.start()
    
    # Add a short wait to ensure services are fully initialized
    time.sleep(3)
    
    # Define rules for Scaphandre metrics
    scaphandre_rules: list[MatchRule] = [
        ("service.name", operator.eq, "scaphandre")
    ]
    
    try:
        # Get existing configuration if available
        print("Checking for existing configuration...")
        bc = await BridgeConfiguration.a_get_by_alias("bridge_config")
        print("Retrieved existing BridgeConfiguration")
        
        # Create a ResourceConfiguration for Scaphandre
        rc_scaphandre = ResourceConfiguration("scaphandre-metrics", scaphandre_rules)
        
        # Add the specific metrics you want to track
        rc_scaphandre.add_metric("scaph_host_power_microwatts")
        rc_scaphandre.add_metric("scaph_host_load_avg_one")
        rc_scaphandre.add_metric("scaph_host_memory_total_bytes")
        rc_scaphandre.add_metric("scaph_host_memory_available_bytes")
        
        # Add this configuration to the bridge
        bc.set_res_config(rc_scaphandre)
        
        print("Updated BridgeConfiguration with Scaphandre metrics")
        
    except DataClayException:
        print("BridgeConfiguration not found. Creating new one...")
        
        # First try to clean up any stale alias that might be causing issues
        try:
            from dataclay.client.api import delete_alias
            await delete_alias("bridge_config")
            print("Cleaned up any stale alias")
        except:
            pass  # Ignore errors during cleanup
        
        bc = BridgeConfiguration()
        
        # Create a ResourceConfiguration for Scaphandre
        rc_scaphandre = ResourceConfiguration("scaphandre-metrics", scaphandre_rules)
        
        # Add the specific metrics you want to track
        rc_scaphandre.add_metric("scaph_host_power_microwatts")
        rc_scaphandre.add_metric("scaph_host_load_avg_one")
        rc_scaphandre.add_metric("scaph_host_memory_total_bytes")
        rc_scaphandre.add_metric("scaph_host_memory_available_bytes")
        
        # Add this configuration to the bridge
        bc.set_res_config(rc_scaphandre)
        
        # Store the configuration
        await bc.a_make_persistent(alias="bridge_config")
        
        print("Created new BridgeConfiguration with Scaphandre metrics")
    
    # Print the current configuration for verification
    print("\nCurrent configuration:")
    for name, config in bc.resource_configurations.items():
        print(f"- Resource configuration: {name}")
        print(f"  Metrics: {config.metric_names}")
    
    print("\nConfiguration complete.")

if __name__ == "__main__":
    asyncio.run(main())