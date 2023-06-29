import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import holidays
from avanza import OrderType

log = logging.getLogger("main.dt.common_types")


class DayTime(str, Enum):
    MORNING = "morning"
    DAY = "day"
    EVENING = "evening"


class Instrument(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"


@dataclass
class TradingTime:
    day_time: DayTime = DayTime.MORNING
    _old_day_time: DayTime = DayTime.MORNING

    def update_day_time(self) -> None:
        current_time = datetime.now()

        if current_time <= current_time.replace(hour=9, minute=0):
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
