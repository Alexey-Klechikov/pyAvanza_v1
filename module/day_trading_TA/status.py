"""
This module contains a Status class for Day trading. Status of each instrument and time_of_day with their methods
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from avanza import OrderType

log = logging.getLogger("main.status_dt_ta")


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


@dataclass
class InstrumentStatus:
    stop_settings: dict

    price_sell: Optional[float] = None
    price_buy: Optional[float] = None
    spread: Optional[float] = None

    position: dict = field(default_factory=dict)
    active_order: dict = field(default_factory=dict)

    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    def get_status(self, certificate_info: dict) -> None:
        self.price_buy = certificate_info[OrderType.BUY]
        self.price_sell = certificate_info[OrderType.SELL]
        self.spread = certificate_info["spread"]
        self.position = certificate_info["position"]
        self.active_order = certificate_info["order"]

    def update_limits(self, atr) -> None:
        if not self.position:
            return None

        self.stop_loss = round(
            self.price_sell * (1 - (1 - self.stop_settings["stop_loss"]) * atr), 2
        )
        self.take_profit = round(
            self.price_sell * (1 + (self.stop_settings["take_profit"] - 1) * atr), 2
        )


@dataclass
class TradingTime:
    day_time: DayTime = DayTime.MORNING
    _old_day_time: DayTime = DayTime.MORNING

    def update_day_time(self) -> None:
        current_time = datetime.now()

        if current_time <= current_time.replace(hour=10, minute=0):
            self.day_time = DayTime.MORNING

        elif current_time >= current_time.replace(hour=17, minute=15):
            self.day_time = DayTime.EVENING

        else:
            self.day_time = DayTime.DAY

        if self._old_day_time != self.day_time:
            log.warning(f"Day time: {self._old_day_time} -> {self.day_time}")

            self._old_day_time = self.day_time
