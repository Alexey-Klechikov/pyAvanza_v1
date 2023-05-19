"""
This module contains all tooling to communicate to Yahoo Finance API to load historical data.
"""

import logging
import os
import pickle
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional

import pandas as pd
import yfinance as yf

log = logging.getLogger("main.utils.history")


class Cache(str, Enum):
    REUSE = "REUSE"
    SKIP = "SKIP"
    APPEND = "APPEND"


class History:
    def __init__(
        self,
        ticker_yahoo: str,
        period: str,
        interval: str,
        cache: str = Cache.APPEND,
        extra_data: pd.DataFrame = pd.DataFrame(
            columns=["Open", "High", "Low", "Close", "Volume"]
        ),
        target_day_direction: Optional[str] = None,
    ):
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.pickle_path = f"{current_dir}/cache/{ticker_yahoo}.pickle"
        self.ticker_yahoo = ticker_yahoo
        self.extra_data = extra_data
        self.interval = interval
        self.period = period
        self.cache = cache

        self.data = self.get_data(target_day_direction)

    def get_data(self, target_day_direction: Optional[str]) -> pd.DataFrame:
        data: pd.DataFrame = pd.DataFrame(
            columns=["Open", "High", "Low", "Close", "Volume"]
        )

        if self.cache == Cache.REUSE:
            data = self._read_cache(self.pickle_path)

            if data.empty:
                self.cache = Cache.SKIP

        if self.cache == Cache.SKIP:
            data = (
                self.extra_data
                if not self.extra_data.empty
                else self._read_ticker(self.ticker_yahoo, self.period, self.interval)
            )

        if self.cache == Cache.APPEND:
            # If we want evenly distributed data, we need to get excessive data that we can later filter out
            period = (
                self.period
                if not target_day_direction
                else f"{int(self.period[:-1]) * 6}d"
            )

            data = (
                self._read_cache(self.pickle_path)
                .append(self.extra_data)
                .append(self._read_ticker(self.ticker_yahoo, period, self.interval))
                .fillna(0)
            )

            data = (
                data[["Open", "High", "Low", "Close", "Volume"]]
                .groupby(data.index)
                .first()
            )

            self._dump_cache(self.pickle_path, data)

            if target_day_direction:
                data = self._get_directed_history(data, target_day_direction)

            else:
                data = data[
                    lambda x: (
                        (datetime.today() - timedelta(days=int(period[:-1]))).strftime(
                            "%Y-%m-%d"
                        )
                        <= x.index
                    )
                ]  # type: ignore

        data.sort_index(inplace=True)

        return data

    def _read_ticker(
        self, ticker_yahoo: str, period: str, interval: str
    ) -> pd.DataFrame:
        ticker = yf.Ticker(ticker_yahoo)

        period_num = int("".join([i for i in period if i.isdigit()]))

        # Progressive loader if more than a week of data with 1 min interval is requested
        if (period.endswith("d") and period_num > 7) and interval == "1m":

            earliest_date = datetime.today() - timedelta(days=min(period_num, 29))

            intervals: List[List[str]] = []
            end_date = datetime.today() + timedelta(days=1)
            while True:
                start_date = max(earliest_date, end_date - timedelta(days=5))
                if end_date.date() == start_date.date():
                    break

                intervals.append(
                    [start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")]
                )
                end_date = start_date

            data = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
            for start, end in intervals:
                data = data.append(
                    ticker.history(interval=interval, start=start, end=end)
                )
            data.drop_duplicates(inplace=True)

        # Simple loader
        else:
            data = ticker.history(period=period, interval=interval)

        return data

    def _read_cache(self, pickle_path: str) -> pd.DataFrame:
        data = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

        directory_exists = os.path.exists("/".join(pickle_path.split("/")[:-1]))
        if not directory_exists:
            os.makedirs("/".join(pickle_path.split("/")[:-1]))
            return data

        if not os.path.exists(pickle_path):
            return data

        # Check if cache exists (and is completed)
        try:
            with open(pickle_path, "rb") as pcl:
                data = pickle.load(pcl)

        except EOFError:
            os.remove(pickle_path)

        return data[["Open", "High", "Low", "Close", "Volume"]]

    def _dump_cache(self, pickle_path: str, data: pd.DataFrame) -> None:
        with open(pickle_path, "wb") as pcl:
            pickle.dump(data, pcl)

    def _get_directed_history(
        self, data: pd.DataFrame, target_day_direction: str
    ) -> pd.DataFrame:
        strategy_target = int(self.period[:-1])

        counters = {"BULL": 0, "BEAR": 0}

        filtered_data = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

        for _, group in reversed(tuple(data.groupby(data.index.date))):  # type: ignore
            if len(group) < 470 or sum(group["Volume"]) == 0:
                continue

            day_direction = None
            day_price_change = group["Close"].iloc[-10] / group["Close"].iloc[60]
            if day_price_change > 1.005:
                day_direction = "BULL"

            elif day_price_change < 0.995:
                day_direction = "BEAR"

            if (
                not day_direction
                or counters[day_direction] >= strategy_target
                or day_direction != target_day_direction
            ):
                continue

            counters[day_direction] += 1

            filtered_data = pd.concat([filtered_data, group])

        log.debug(f"Counters: {counters}")

        return filtered_data
