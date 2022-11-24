"""
This module contains a Status class for Day trading. Status of each instrument and time_of_day with their methods
"""

import copy
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Union

from avanza import OrderType

log = logging.getLogger("main.status_dt_cs")


PAUSE_TIMES = [
    {"start": (17, 25), "end": (17, 35)},
]


class DayTime(str, Enum):
    MORNING = "morning"  # No trading
    DAY = "day"  # Use AVA data
    PAUSE = "pause"  # Other markets are opening and influence OMX with often recovery to the previous trend
    EVENING = "evening"  #  Market is closing. No buy orders, only sell.
    NIGHT = "night"  # No trading


class Instrument(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"

    @classmethod
    def generate_empty_counters(cls) -> dict:
        return {i: 0 for i in cls}


@dataclass
class InstrumentStatus:
    instrument_type: str
    active_order: dict = field(default_factory=dict)
    has_position: bool = False
    buy_time: Optional[datetime] = None
    last_update_limits_message_timer: int = 0

    atr: float = 0
    spread: Optional[float] = None
    price_current: Optional[float] = None
    price_acquired: Optional[float] = None
    price_stop_loss: Optional[float] = None
    price_take_profit: Optional[float] = None
    price_take_profit_super: Optional[float] = None

    def update_prices_on_position(
        self,
        positions: list,
        settings_limits_percent: dict,
    ) -> None:
        active_positions = [
            position
            for position in positions
            if position.get("averageAcquiredPrice") is not None
        ]

        if len(active_positions) == 0:
            self.has_position = False

            return

        self.buy_time = self.buy_time if self.buy_time is not None else datetime.now()

        position = active_positions[0]

        self.price_acquired = (
            self.price_acquired
            if self.price_acquired is not None
            else self.price_current
        )

        self.price_stop_loss = round(
            position["averageAcquiredPrice"]
            * (1 - (1 - settings_limits_percent["stop_loss"]) * self.atr),
            2,
        )

        self.price_take_profit = round(
            position["averageAcquiredPrice"]
            * (1 + (settings_limits_percent["take_profit"] - 1) * self.atr),
            2,
        )

        self.price_take_profit_super = round(
            position["averageAcquiredPrice"]
            * (1 + (settings_limits_percent["take_profit_super"] - 1) * self.atr),
            2,
        )

        update_limits_message_timer = round(
            (datetime.now() - self.buy_time).seconds / 60
        )

        action = None
        if not self.has_position:
            action = "SET"
            self.last_update_limits_message_timer = 0

        elif (
            self.buy_time is not None
            and update_limits_message_timer % 10 == 0
            and update_limits_message_timer != self.last_update_limits_message_timer
        ):
            action = "UPDATE"
            self.last_update_limits_message_timer = update_limits_message_timer

        if action is not None:
            log.info(
                "".join(
                    [
                        f"{self.instrument_type} - ({action} limits): ",
                        f"ATR: {round(self.atr, 2)}, ",
                        f"SL: {self.price_stop_loss}, ",
                        f"TP: {self.price_take_profit}, ",
                    ]
                )
            )

        self.has_position = True

    def update_on_active_buy_order(
        self,
        settings_limits_percent: dict,
    ) -> None:
        if self.active_order.get("type") != OrderType.BUY:
            return

        self.price_stop_loss = round(
            self.active_order["price"]
            * (1 - (1 - settings_limits_percent["stop_loss"]) * self.atr),
            2,
        )

        self.price_take_profit = round(
            self.active_order["price"]
            * (1 + (settings_limits_percent["take_profit"] - 1) * self.atr),
            2,
        )

    def check_trade_is_completed(self) -> bool:
        if self.active_order or self.has_position:
            return False

        if self.price_acquired and self.price_current:
            trade_success_status = "( ? )"

            if self.price_current >= self.price_acquired:
                trade_success_status = "( + )"

            elif self.price_current < self.price_acquired:
                trade_success_status = "( - )"

            log.warning(
                f"<<< {self.instrument_type} - Trade is complete {trade_success_status}"
            )

            return True

        return False


class Status:
    def __init__(self, settings: dict):
        self.BULL: InstrumentStatus = InstrumentStatus(Instrument.BULL.name)
        self.BEAR: InstrumentStatus = InstrumentStatus(Instrument.BEAR.name)
        self.day_time: DayTime = DayTime.MORNING
        self.settings = settings

    def update_day_time(self) -> None:
        current_time = datetime.now()
        old_day_time = self.day_time

        if current_time <= current_time.replace(hour=10, minute=0):
            self.day_time = DayTime.MORNING

            time.sleep(60)

        else:
            self.day_time = DayTime.DAY

        for pt in PAUSE_TIMES:
            if current_time >= current_time.replace(
                hour=pt["start"][0], minute=pt["start"][1]
            ) and current_time <= current_time.replace(
                hour=pt["end"][0], minute=pt["end"][1]
            ):
                self.day_time = DayTime.PAUSE

        if current_time >= current_time.replace(hour=17, minute=35):
            self.day_time = DayTime.EVENING

        if (current_time >= current_time.replace(hour=18, minute=30)) or (
            self.day_time == DayTime.EVENING
            and not any(
                [
                    (
                        getattr(self, instrument_type.name).has_position
                        or getattr(self, instrument_type.name).active_order
                    )
                    for instrument_type in Instrument
                ]
            )
        ):
            self.day_time = DayTime.NIGHT

        if old_day_time != self.day_time:
            log.warning(f"Day time: {old_day_time} -> {self.day_time}")

    def update_instrument(
        self,
        instrument_type: Instrument,
        certificate_info: dict,
        active_order: dict,
        atr: float,
    ) -> InstrumentStatus:
        instrument_status: InstrumentStatus = getattr(self, instrument_type.name)

        instrument_status.active_order = active_order
        instrument_status.spread = certificate_info.get("spread")
        instrument_status.price_current = certificate_info.get(OrderType.SELL)
        instrument_status.atr = atr

        instrument_status.update_prices_on_position(
            certificate_info["positions"],
            self.settings["limits_percent"],
        )

        instrument_status.update_on_active_buy_order(
            self.settings["limits_percent"],
        )

        if instrument_status.check_trade_is_completed():
            setattr(self, instrument_type.name, InstrumentStatus(instrument_type.name))

            instrument_status = getattr(self, instrument_type.name)

        return instrument_status
