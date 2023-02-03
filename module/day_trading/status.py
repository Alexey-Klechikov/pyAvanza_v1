"""
This module contains a Status class for Day trading. Status of each instrument and time_of_day with their methods
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import holidays
from avanza import OrderType

log = logging.getLogger("main.day_trading.status")


class DayTime(str, Enum):
    MORNING = "morning"  # No trading
    DAY = "day"  # Trading is on
    EVENING = "evening"  #  Market is closing. Sell all.


class Instrument(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"

    @classmethod
    def generate_empty_counters(cls) -> dict:
        return {i: 0 for i in cls}

    @classmethod
    def from_signal(cls, signal: OrderType) -> dict:
        return {
            OrderType.BUY: Instrument.BULL
            if signal == OrderType.BUY
            else Instrument.BEAR,
            OrderType.SELL: Instrument.BEAR
            if signal == OrderType.BUY
            else Instrument.BULL,
        }


@dataclass
class InstrumentStatus:
    instrument: Instrument
    stop_settings: dict

    price_sell: Optional[float] = None
    price_buy: Optional[float] = None
    spread: Optional[float] = None

    position: dict = field(default_factory=dict)
    active_order: dict = field(default_factory=dict)
    last_sell_deal: dict = field(default_factory=dict)

    acquired_price: Optional[float] = None

    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    price_max: Optional[float] = None

    def get_status(self, certificate_info: dict) -> None:
        self.position = certificate_info["position"]
        self.last_sell_deal = (
            certificate_info["last_deal"]
            if certificate_info["last_deal"].get("orderType") == "SELL"
            else {}
        )

        if self.acquired_price and not self.position:
            log.warning(
                ", ".join(
                    [
                        f'{self.instrument.value} ===> Verdict: {"good" if self.acquired_price < self.last_sell_deal.get("price", 0) else "bad"}',
                        f"Acquired: {self.acquired_price}",
                        f"Sold: {self.price_sell}",
                        f"Profit: {round((self.last_sell_deal.get('price', 0) / self.acquired_price - 1)* 100, 2)}%",
                    ]
                )
            )

            self.price_max = None
            self.acquired_price = None

        elif not self.acquired_price and self.position:
            self.acquired_price = self.position["acquiredPrice"]

        self.spread = certificate_info["spread"]
        if (
            self.spread is not None
            and self.spread >= self.stop_settings["spread_limit"]
        ):
            log.debug(f"{self.instrument.value} ===> High spread: {self.spread}")

            self.price_buy = None
            self.price_sell = None

        else:
            self.price_buy = certificate_info[OrderType.BUY]
            self.price_sell = certificate_info[OrderType.SELL]
            self.active_order = certificate_info["order"]

            self.price_max = (
                self.price_sell
                if not self.price_max
                else max(self.price_max, self.price_sell)
            )

    def update_limits(self, atr) -> None:
        if not self.position or self.price_sell is None:
            return None

        self.stop_loss = round(
            self.price_sell * (1 - (1 - self.stop_settings["stop_loss"]) * atr), 2
        )
        self.take_profit = round(
            self.price_sell * (1 + (self.stop_settings["take_profit"] - 1) * atr), 2
        )

    def get_profit(self) -> float:
        if (
            not self.position
            or self.acquired_price is None
            or self.price_sell is None
            or round(self.price_sell - self.acquired_price, 2) == 0
        ):
            return 0.0

        return round(
            ((self.price_sell - self.acquired_price) / self.acquired_price) * 100, 2
        )


@dataclass
class TradingTime:
    day_time: DayTime = DayTime.MORNING
    _old_day_time: DayTime = DayTime.MORNING

    def update_day_time(self) -> None:
        current_time = datetime.now()

        if current_time <= current_time.replace(hour=10, minute=0):
            self.day_time = DayTime.MORNING

        elif (
            current_time >= current_time.replace(hour=17, minute=15)
            or current_time.date() in holidays.SE()
        ):
            self.day_time = DayTime.EVENING

        else:
            self.day_time = DayTime.DAY

        if self._old_day_time != self.day_time:
            log.warning(f"Day time: {self._old_day_time} -> {self.day_time}")

            self._old_day_time = self.day_time
