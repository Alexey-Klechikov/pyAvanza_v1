import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import holidays
from avanza import OrderType

log = logging.getLogger("main.dt.common_types")


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
class TradingTime:
    day_time: DayTime = DayTime.MORNING
    _old_day_time: DayTime = DayTime.MORNING

    def update_day_time(self) -> None:
        current_time = datetime.now()

        if current_time <= current_time.replace(hour=12, minute=0):
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
