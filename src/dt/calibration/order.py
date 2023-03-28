import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from src.dt.common_types import Instrument

log = logging.getLogger("main.dt.calibration.order")


@dataclass
class CalibrationOrder:
    instrument: Instrument

    on_balance: bool = False
    price_buy: Optional[float] = None
    price_sell: Optional[float] = None
    price_stop_loss: Optional[float] = None
    price_take_profit: Optional[float] = None
    time_buy: Optional[datetime] = None
    time_sell: Optional[datetime] = None
    verdict: Optional[str] = None

    def buy(self, row: pd.Series) -> None:
        self.time_buy = row.name  # type: ignore

        self.on_balance = True

        self.price_buy = ((row["Open"] + row["Close"]) / 2) * (
            1.00015 if self.instrument == Instrument.BULL else 0.99985
        )

    def sell(self, row: pd.Series):
        self.time_sell = row.name  # type: ignore

        self.price_sell = (row["Close"] + row["Open"]) / 2

        self.verdict = (
            "good"
            if any(
                [
                    (
                        self.instrument == Instrument.BULL
                        and self.price_sell >= self.price_buy
                    ),
                    (
                        self.instrument == Instrument.BEAR
                        and self.price_sell <= self.price_buy
                    ),
                ]
            )
            else "bad"
        )

    def set_limits(self, row: pd.Series, settings_trading: dict) -> None:
        atr_correction = row["ATR"] / 20
        direction = 1 if self.instrument == Instrument.BULL else -1
        reference_price = (row["Open"] + row["Close"]) / 2

        self.price_stop_loss = reference_price * (
            1 - (1 - settings_trading["stop_loss"]) * atr_correction * direction
        )
        self.price_take_profit = reference_price * (
            1 + (settings_trading["take_profit"] - 1) * atr_correction * direction
        )

    def check_limits(self, row: pd.Series) -> bool:
        self.price_sell = row["Close"]

        if not self.price_stop_loss or not self.price_take_profit:
            return False

        return (
            True
            if any(
                [
                    (
                        self.instrument == Instrument.BULL
                        and any(
                            [
                                row["Close"] <= self.price_stop_loss,
                                (row["High"] + max(row["Close"], row["Open"])) / 2
                                >= self.price_take_profit,
                            ]
                        )
                    ),
                    (
                        self.instrument == Instrument.BEAR
                        and any(
                            [
                                row["Close"] >= self.price_stop_loss,
                                (row["Low"] + min(row["Close"], row["Open"])) / 2
                                <= self.price_take_profit,
                            ]
                        )
                    ),
                ]
            )
            else False
        )

    def pop_result(self) -> dict:
        profit: Optional[float] = None

        if self.price_sell is not None and self.price_buy is not None:
            profit = round(
                (
                    1
                    + 20
                    * (
                        (self.price_sell / self.price_buy - 1)
                        * (1 if self.instrument == Instrument.BULL else -1)
                    )
                )
                * 1000
            )

        points_bin = 0.0
        if profit is not None:
            points = 1 if (profit - 1000) > 0 else -1
            multiplier = min([1 + abs(profit - 1000) // 100, 4])
            points_bin = points * multiplier

        result = {
            "instrument": self.instrument,
            "price_buy": self.price_buy,
            "price_sell": self.price_sell,
            "time_buy": self.time_buy,
            "time_sell": self.time_sell,
            "verdict": self.verdict,
            "profit": profit,
            "points": points_bin,
        }

        self.on_balance = False
        self.price_buy = None
        self.price_sell = None
        self.time_buy = None
        self.time_sell = None
        self.verdict = None
        self.price_stop_loss = None
        self.price_take_profit = None

        return result
