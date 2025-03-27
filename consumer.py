#!/usr/bin/env python3

"""
Monitoring Consumer Script for Scaphandre

This script monitors the TimeSeriesData object with optimized timing,
observing how new data is added and old data is removed.
"""

import pandas as pd
import time
from datetime import datetime

from dataclay import Client
from dataclay.exceptions import DataClayException
from model.timeseries import TimeSeriesData

# Connect to dataClay
print("Connecting to dataClay...")
client = Client(proxy_host="127.0.0.1", dataset="admin")
client.start()

def process_dataframe(df):
    """Process the dataframe and create the dataset with Unix timestamps."""
    if df is None or len(df) == 0:
        return None
        
    # Create a new dataframe with the same index
    dataset = pd.DataFrame(index=df.index)
    
    # Convert index to Unix timestamp (seconds since epoch)
    dataset['timestamp'] = dataset.index / 1_000_000_000  # Convert nanoseconds to seconds
    
    # Find columns by type
    power_col = None
    load_col = None
    mem_total_col = None
    mem_avail_col = None
    
    for col in df.columns:
        if 'power_microwatts' in col:
            power_col = col
        elif 'load_avg_one' in col:
            load_col = col
        elif 'memory_total_bytes' in col:
            mem_total_col = col
        elif 'memory_available_bytes' in col:
            mem_avail_col = col
    
    # Add power consumption in watts
    if power_col:
        dataset['power_consumption'] = df[power_col] / 1_000_000  # Convert to watts
    
    # Add CPU usage (load average)
    if load_col:
        dataset['cpu_usage'] = df[load_col]
    
    # Calculate RAM usage in MB (total - available)
    if mem_total_col and mem_avail_col:
        dataset['ram_usage'] = (df[mem_total_col] - df[mem_avail_col]) / (1024 * 1024)  # Convert to MB
        
    return dataset

try:
    # Get TimeSeriesData
    print("Getting TimeSeriesData...")
    tsd = TimeSeriesData.get_by_alias("timeseries")
    print(f"TimeSeriesData found. Max rows: {tsd.max_rows}")
    
    # Initial state
    previous_df = tsd.get_dataframe()
    previous_indexes = set() if previous_df is None else set(previous_df.index)
    
    # Monitoring loop
    print("\n=== Starting Monitoring ===")
    print("Press Ctrl+C to stop...")
    
    # Wait time - set to just under 3 minutes (batch timeout)
    # This ensures we'll likely catch each batch soon after it arrives
    monitor_interval = 170  # seconds
    
    iteration = 0
    while True:
        iteration += 1
        current_time = datetime.now().strftime('%H:%M:%S')
        print(f"\n[{current_time}] Monitoring iteration {iteration}")
        
        # Get current dataframe
        current_df = tsd.get_dataframe()
        
        if current_df is None:
            print("No data available yet. Waiting for first batch...")
            current_df = tsd.wait_for_dataframe()
            print(f"Received first batch with {len(current_df)} rows!")
        
        # Get current indexes
        current_indexes = set(current_df.index)
        
        # Calculate added and removed indexes
        added_indexes = current_indexes - previous_indexes
        removed_indexes = previous_indexes - current_indexes
        
        # Print summary
        print(f"Current DataFrame size: {len(current_df)} / {tsd.max_rows} rows")
        
        if len(added_indexes) > 0:
            print(f"New rows added: {len(added_indexes)}")
            
            # Convert nanosecond timestamps to readable format for display
            first_ts = pd.to_datetime(min(added_indexes), unit='ns')
            last_ts = pd.to_datetime(max(added_indexes), unit='ns')
            
            print(f"First new row: {first_ts} (index: {min(added_indexes)})")
            print(f"Last new row: {last_ts} (index: {max(added_indexes)})")
            
            # Process the new data
            new_rows = current_df.loc[list(added_indexes)]
            new_dataset = process_dataframe(new_rows)
            if new_dataset is not None:
                print("\nNew data sample (first 3 rows):")
                print(new_dataset.head(3))
        else:
            print("No new rows added since last check.")
        
        if len(removed_indexes) > 0:
            print(f"Old rows removed: {len(removed_indexes)}")
            
            # Convert nanosecond timestamps to readable format for display
            first_ts = pd.to_datetime(min(removed_indexes), unit='ns')
            last_ts = pd.to_datetime(max(removed_indexes), unit='ns')
            
            print(f"First removed row: {first_ts} (index: {min(removed_indexes)})")
            print(f"Last removed row: {last_ts} (index: {max(removed_indexes)})")
            
            # Calculate what percentage of the buffer was replaced
            replacement_percent = (len(removed_indexes) / tsd.max_rows) * 100
            print(f"Buffer replacement: {replacement_percent:.1f}% of max capacity")
        
        # Every other iteration, process and display complete dataset statistics
        if iteration % 2 == 0 and current_df is not None:
            full_dataset = process_dataframe(current_df)
            if full_dataset is not None:
                print("\n=== Full Dataset Statistics ===")
                print(f"Total rows: {len(full_dataset)}")
                
                # Print time range in unix timestamps and human-readable format
                if len(full_dataset) > 1:
                    start_ts = full_dataset['timestamp'].min()
                    end_ts = full_dataset['timestamp'].max()
                    duration = end_ts - start_ts
                    
                    start_readable = datetime.fromtimestamp(start_ts).strftime('%H:%M:%S')
                    end_readable = datetime.fromtimestamp(end_ts).strftime('%H:%M:%S')
                    
                    print(f"Time range: {start_ts} to {end_ts} (Unix timestamps)")
                    print(f"Human readable: {start_readable} to {end_readable}")
                    print(f"Duration: {duration:.2f} seconds ({duration/60:.2f} minutes)")
                    print(f"Average interval: {duration / (len(full_dataset) - 1):.2f} seconds")
                
                # Print basic statistics
                for col in ['power_consumption', 'cpu_usage', 'ram_usage']:
                    if col in full_dataset.columns and not full_dataset[col].isna().all():
                        print(f"\n{col.replace('_', ' ').title()} statistics:")
                        print(f"  Average: {full_dataset[col].mean():.2f} {'watts' if col == 'power_consumption' else 'MB' if col == 'ram_usage' else ''}")
                        print(f"  Maximum: {full_dataset[col].max():.2f} {'watts' if col == 'power_consumption' else 'MB' if col == 'ram_usage' else ''}")
                        print(f"  Minimum: {full_dataset[col].min():.2f} {'watts' if col == 'power_consumption' else 'MB' if col == 'ram_usage' else ''}")
        
        # Update previous state
        previous_df = current_df
        previous_indexes = current_indexes
        
        # Wait until next check
        print(f"\nNext check in {monitor_interval} seconds (around {(datetime.now() + pd.Timedelta(seconds=monitor_interval)).strftime('%H:%M:%S')})")
        time.sleep(monitor_interval)
        
except KeyboardInterrupt:
    print("\nMonitoring stopped by user.")
except DataClayException as e:
    print(f"DataClay error: {e}")
    print("Make sure the bridge is running and has collected data.")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

# Clean exit
try:
    client.stop()
    print("DataClay client stopped gracefully")
except:
    pass

print("\nDone.")