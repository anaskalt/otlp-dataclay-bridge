from threading import Event
from typing import Optional, List

import pandas as pd

from dataclay import DataClayObject, activemethod


class TimeSeriesData(DataClayObject):
    """Class for managing time series data with a sliding window approach.
    
    This class maintains a single DataFrame with a fixed maximum size,
    implementing a sliding window over time. New data points are appended
    and old data points are removed to maintain the window size.
    """
    
    dataframe: Optional[pd.DataFrame]
    max_rows: int
    waiters: List[Event]

    def __init__(self, max_rows: int = 300):
        """Initialize the TimeSeriesData object.
        
        Args:
            max_rows: Maximum number of rows to keep in the DataFrame. Default is 300,
                      which provides enough history for LSTM training and 5-minute prediction
                      with 3-second interval data collection.
        """
        self.dataframe = None
        self.max_rows = max_rows
        self.waiters = list()

    @activemethod
    def add_dataframe(self, df: pd.DataFrame) -> None:
        """Add new data to the unified dataframe, maintaining the sliding window.
        
        When new data is added, the oldest data points are removed if the total
        size exceeds max_rows.
        
        Args:
            df: New DataFrame to append
        """
        if self.dataframe is None:
            self.dataframe = df
        else:
            # Append new data
            self.dataframe = pd.concat([self.dataframe, df])
            
            # Maintain sliding window by removing oldest entries
            if len(self.dataframe) > self.max_rows:
                self.dataframe = self.dataframe.iloc[-self.max_rows:]
        
        # Notify waiters that new data is available
        for waiter in self.waiters:
            waiter.set()
    
    @activemethod
    def get_dataframe(self) -> Optional[pd.DataFrame]:
        """Get the current unified DataFrame.
        
        Returns:
            The current DataFrame, or None if no data has been added yet.
        """
        return self.dataframe
    
    @activemethod
    def wait_for_dataframe(self) -> pd.DataFrame:
        """Wait for new data to be added to the DataFrame.
        
        This method blocks until new data is added through add_dataframe().
        
        Returns:
            The updated DataFrame after new data has been added.
        """
        waiter = Event()
        self.waiters.append(waiter)
        waiter.wait()
        self.waiters.remove(waiter)
        return self.dataframe
    
    # Maintain backward compatibility with original implementation
    @activemethod
    def get_all_dataframes(self) -> List[pd.DataFrame]:
        """Get all DataFrames (maintained for backwards compatibility).
        
        Returns:
            List containing the single unified DataFrame (if it exists)
        """
        if self.dataframe is not None:
            return [self.dataframe]
        return []
    
    @activemethod
    def get_last_dataframe(self) -> Optional[pd.DataFrame]:
        """Get the last DataFrame (maintained for backwards compatibility).
        
        Returns:
            The unified DataFrame
        """
        return self.dataframe