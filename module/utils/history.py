"""
This module contains all tooling to communicate to Yahoo Finance API to load historical data.
"""

import os
import pickle
import logging
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta


log = logging.getLogger("main.history")


class History:
    def __init__(self, ticker_yahoo, period, interval, cache="append"):
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pickle_path = f"{current_dir}/cache/{ticker_yahoo}.pickle"

        old_history_df = self.read_cache(pickle_path)

        if cache == "reuse" and not old_history_df.empty:
            self.history_df = old_history_df

        else:
            self.history_df = self.read_ticker(ticker_yahoo, period, interval)

            if cache == "append":
                self.history_df = self.history_df.append(old_history_df)
                self.history_df.drop_duplicates(inplace=True)
                self.dump_cache(pickle_path)

        self.history_df.sort_index(inplace=True)

        if period.endswith("d"):
            self.history_df = self.history_df.loc[
                (datetime.today() - timedelta(days=int(period[:-1])))
                .strftime("%Y-%m-%d") : datetime.today()
                .strftime("%Y-%m-%d")
            ]

    def read_ticker(self, ticker_yahoo, period, interval):
        ticker_obj = yf.Ticker(ticker_yahoo)

        total_period_int = int("".join([i for i in period if i.isdigit()]))

        # Progressive loader if more than a week of data with 1 min interval is requested
        if (period.endswith("d") and total_period_int > 7) and interval == "1m":

            earliest_date = datetime.today() - timedelta(days=min(total_period_int, 29))

            intervals_list = list()
            end_date = datetime.today() + timedelta(days=1)
            while True:
                start_date = max(earliest_date, end_date - timedelta(days=5))
                if end_date.date() == start_date.date():
                    break

                intervals_list.append(
                    [start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")]
                )
                end_date = start_date

            history_df = pd.DataFrame()
            for start_date, end_date in intervals_list:
                history_df = history_df.append(
                    ticker_obj.history(
                        interval=interval, start=start_date, end=end_date
                    )
                )
            history_df.drop_duplicates(inplace=True)

        # Simple loader
        else:
            history_df = ticker_obj.history(period=period, interval=interval)

        return history_df

    def read_cache(self, pickle_path):
        history_df = pd.DataFrame()

        directory_exists = os.path.exists("/".join(pickle_path.split("/")[:-1]))
        if not directory_exists:
            os.makedirs("/".join(pickle_path.split("/")[:-1]))
            return history_df

        if not os.path.exists(pickle_path):
            return history_df

        # Check if cache exists (and is completed)
        try:
            with open(pickle_path, "rb") as pcl:
                history_df = pickle.load(pcl)

        except EOFError:
            os.remove(pickle_path)

        return history_df

    def dump_cache(self, pickle_path):
        with open(pickle_path, "wb") as pcl:
            pickle.dump(self.history_df, pcl)
