from datetime import date, datetime
from typing import Optional

import mplfinance as mpf
import numpy as np
import pandas as pd
import yfinance as yf


class Plot:
    def __init__(
        self,
        data: Optional[pd.DataFrame] = None,
        date_target: Optional[date] = None,
        date_end: Optional[date] = None,
    ):
        if data is not None:
            self.data = data

        elif date_target is not None and date_end is not None:
            self.data = self.get_ticker_history(date_target, date_end)

        self.subplots: list = []
        self.signals: dict = {"BUY": [], "SELL": [], "EXIT": []}

    def get_signals_from_log(self, path: str) -> None:
        with open(path, "r") as f:
            lines = f.readlines()

        for line in lines:
            if not ("Signal: BUY" in line or "Signal: SELL" in line or "Exit" in line):
                continue

            signal = line.split("Signal: ")[1].split("|")[0].strip().upper()

            time = (
                datetime.strptime(line.split("[")[2].split("]")[0].strip(), "%H:%M:%S")
                .time()
                .replace(second=0)
            )

            self.signals[signal].append(time)

    def get_ticker_history(self, date_target: date, date_end: date) -> pd.DataFrame:
        ticker = yf.Ticker("^OMX")
        data = ticker.history(interval="1m", start=date_target, end=date_end)[
            ["Open", "High", "Low", "Close"]
        ].reset_index()
        data.index = pd.DatetimeIndex(data["Datetime"])  # type: ignore
        data = data.drop(columns=["Datetime"])

        return data

    def add_signals_to_figure(self, signals: Optional[dict] = None) -> None:
        if signals is None:
            signals = self.signals

        for signal, times in signals.items():
            self.data[signal] = np.nan
            if signal == "EXIT":
                for time in times:
                    self.data.loc[time, signal] = (
                        self.data.loc[time]["Close"] + self.data.loc[time]["Open"]
                    ) / 2
            else:
                for time in times:
                    self.data.loc[time, signal] = self.data.loc[time][
                        "Low" if signal == "BUY" else "High"
                    ]

        self.subplots = [
            mpf.make_addplot(
                self.data["BUY"],
                type="scatter",
                markersize=50,
                marker="^",
                secondary_y=False,
                color="g",
            ),
            mpf.make_addplot(
                self.data["SELL"],
                type="scatter",
                markersize=50,
                marker="v",
                secondary_y=False,
                color="r",
            ),
            mpf.make_addplot(
                self.data["EXIT"],
                type="scatter",
                markersize=50,
                marker="x",
                secondary_y=False,
                color="b",
            ),
        ]

    def add_balance_to_figure(self, orders_history: list):
        if not orders_history:
            return

        balance = 1000
        self.data["balance"] = np.nan
        for order in orders_history:
            self.data.loc[order["time_buy"], "balance"] = balance
            balance *= (100 + (order["profit"] - 1000) / 10) / 100
            self.data.loc[order["time_sell"], "balance"] = balance

        # add a separate plot for balance
        self.subplots.append(
            mpf.make_addplot(
                self.data["balance"],
                type="scatter",
                color="b",
                markersize=50,
                marker="*",
                panel=1,
                ylabel="Balance",
            )
        )

    def add_moving_average_to_figure(self) -> None:
        if "MA" not in self.data.columns:
            return

        self.subplots.append(
            mpf.make_addplot(
                self.data["MA"],
                color="black",
                secondary_y=False,
            )
        )

    def save_figure(self, path: str) -> None:
        fig, _ = mpf.plot(
            self.data,
            type="candle",
            style="yahoo",
            volume=False,
            ylabel="Price",
            figsize=(19.2, 10.8),
            title="OMX30",
            returnfig=True,
            scale_padding={"left": 0.2, "right": 0.8, "top": 0.5},
            addplot=self.subplots,
        )

        fig.savefig(path)
