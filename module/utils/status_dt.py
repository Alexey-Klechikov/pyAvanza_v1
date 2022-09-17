"""
This module contains a Status class for Day trading. Status of each instrument and time_of_day with their methods
"""

import time
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Union


log = logging.getLogger("main.utils.status_dt")


@dataclass
class InstrumentStatus:
    instrument_type: str
    active_order: dict = dict()
    has_position: bool = False
    buy_time: Optional[datetime] = None
    stop_loss_trailing_is_active: bool = False

    spread: Optional[float] = None
    price_current: Optional[float] = None
    price_acquired: Optional[float] = None
    price_stop_loss: Optional[float] = None
    price_stop_loss_trailing: float = 0
    price_take_profit: Optional[float] = None
    price_take_profit_super: Optional[float] = None

    def update(
        self, latest_instrument_status: dict, stop_loss_trailing_timer: Union[int, str]
    ) -> None:
        # Update all attributes when position is IN stock
        self.buy_time = self.buy_time if self.buy_time is not None else datetime.now()
        self.active_order = latest_instrument_status.get("active_order", dict())

        self.spread = latest_instrument_status.get("spread")
        self.price_current = latest_instrument_status.get("price_current")
        self.price_acquired = (
            self.price_acquired
            if self.price_acquired is not None
            else latest_instrument_status.get("price_current")
        )
        self.price_stop_loss = (
            self.price_stop_loss
            if self.price_stop_loss is not None
            else latest_instrument_status.get("price_stop_loss")
        )
        self.price_take_profit = (
            self.price_take_profit
            if self.price_take_profit is not None
            else latest_instrument_status.get("price_take_profit")
        )
        self.price_take_profit_super = latest_instrument_status.get(
            "price_take_profit_super"
        )
        self.price_stop_loss_trailing = max(
            [
                i
                for i in [
                    self.price_stop_loss,
                    self.price_stop_loss_trailing,
                    latest_instrument_status.get("price_stop_loss_trailing", 0),
                ]
                if i is not None
            ]
        )

        # If this position just appeared
        if not self.has_position:
            log.info(
                f"{self.instrument_type} - (SET limits): SL: {self.price_stop_loss}, TP: {self.price_take_profit}"
            )

        self.has_position = True

        # Check if it is time for trailing SL
        if not self.stop_loss_trailing_is_active:
            if (datetime.now() - self.buy_time).seconds > (
                int(stop_loss_trailing_timer) * 60
            ):
                self.stop_loss_trailing_is_active = True

                log.info(
                    f"{self.instrument_type} - {stop_loss_trailing_timer} min -> Switch to trailing stop_loss"
                )

        else:
            self.price_stop_loss = self.price_stop_loss_trailing

    def update_limits(
        self, settings_limits_percent: dict, new_relative_price: float
    ) -> None:
        self.buy_time = datetime.now()
        self.stop_loss_trailing_is_active = False

        self.price_stop_loss = round(
            settings_limits_percent["stop_loss"] * new_relative_price, 2
        )
        self.price_take_profit = round(
            settings_limits_percent["take_profit"] * new_relative_price,
            2,
        )

        log.info(
            f"{self.instrument_type} - (UPD limits): SL: {self.price_stop_loss}, TP: {self.price_take_profit}"
        )


class Status_DT:
    def __init__(self, settings: dict):
        self.BULL = InstrumentStatus("BULL")
        self.BEAR = InstrumentStatus("BEAR")
        self.day_time = "morning"
        self.settings = settings

    def get_instrument(self, instrument_type: str) -> InstrumentStatus:
        return self.BULL if instrument_type == "BULL" else self.BEAR

    def update_day_time(self) -> None:
        current_time = datetime.now()
        old_day_time = self.day_time

        if current_time <= current_time.replace(hour=9, minute=0):
            self.day_time = "morning"

            time.sleep(60)

        else:
            self.day_time = "day"

        if current_time >= current_time.replace(hour=17, minute=25):
            self.day_time = "evening_transition"

        if current_time >= current_time.replace(hour=17, minute=35):
            self.day_time = "evening"

            if (current_time >= current_time.replace(hour=18, minute=30)) or (
                not any(
                    [
                        (
                            self.get_instrument(instrument_type).has_position
                            or self.get_instrument(instrument_type).active_order
                        )
                        for instrument_type in ["BULL", "BEAR"]
                    ]
                )
            ):
                self.day_time = "night"

        if old_day_time != self.day_time:
            log.warning(f"Day time: {old_day_time} -> {self.day_time}")

    def update_instrument(
        self, instrument_type: str, latest_instrument_status: dict
    ) -> None:
        instrument_status = self.get_instrument(instrument_type)

        if latest_instrument_status.get("has_position"):
            instrument_status.update(
                latest_instrument_status, self.settings["stop_loss_trailing_timer"]
            )

        else:
            if instrument_status.has_position:

                trade_success_status = "( ? )"
                if (
                    latest_instrument_status["price_current"]
                    >= instrument_status.price_acquired
                ):
                    trade_success_status = "( + )"
                elif (
                    latest_instrument_status["price_current"]
                    < instrument_status.price_acquired
                ):
                    trade_success_status = "( - )"

                log.warning(
                    f"<<< {instrument_type} - Trade is complete {trade_success_status}"
                )

            setattr(self, instrument_type, InstrumentStatus(instrument_type))

    def update_instrument_trading_limits(
        self, instrument_type: str, new_relative_price: float
    ) -> None:
        instrument_status = self.get_instrument(instrument_type)

        instrument_status.update_limits(
            self.settings["limits_percent"], new_relative_price
        )
