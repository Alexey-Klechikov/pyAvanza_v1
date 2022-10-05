"""
This module contains a Status class for Day trading. Status of each instrument and time_of_day with their methods
"""

import time
import logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Union


log = logging.getLogger("main.utils.status_dt")


@dataclass
class InstrumentStatus:
    instrument_type: str
    active_order: dict = field(default_factory=dict)
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

        self.price_stop_loss = (
            self.price_stop_loss
            if self.price_stop_loss is not None
            else round(
                position["averageAcquiredPrice"] * settings_limits_percent["stop_loss"],
                2,
            )
        )

        self.price_take_profit = (
            self.price_take_profit
            if self.price_take_profit is not None
            else round(
                position["averageAcquiredPrice"]
                * settings_limits_percent["take_profit"],
                2,
            )
        )

        self.price_take_profit_super = round(
            position["averageAcquiredPrice"]
            * settings_limits_percent["take_profit_super"],
            2,
        )

        self.price_stop_loss_trailing = max(
            [
                i
                for i in [
                    self.price_stop_loss,
                    self.price_stop_loss_trailing,
                    round(
                        self.price_current
                        * settings_limits_percent["stop_loss_trailing"],
                        2,
                    ),
                ]
                if i is not None
            ]
        )

        if not self.has_position:
            log.info(
                f"{self.instrument_type} - (SET limits): SL: {self.price_stop_loss}, TP: {self.price_take_profit}"
            )

        self.has_position = True

    def update_on_active_buy_order(
        self,
        settings_limits_percent: dict,
    ) -> None:
        if self.active_order.get("type") != "BUY":
            return

        self.price_stop_loss = round(
            self.active_order["price"] * settings_limits_percent["stop_loss"],
            2,
        )

        self.price_take_profit = round(
            self.active_order["price"] * settings_limits_percent["take_profit"],
            2,
        )

    def update_on_new_signal(
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

    def set_trailing_stop_loss_after_timer(
        self, stop_loss_trailing_timer: Union[int, str]
    ) -> None:
        if self.buy_time is None:
            return

        if self.stop_loss_trailing_is_active:
            self.price_stop_loss = self.price_stop_loss_trailing

        elif (datetime.now() - self.buy_time).seconds > (
            int(stop_loss_trailing_timer) * 60
        ):
            self.stop_loss_trailing_is_active = True

            log.info(
                f"{self.instrument_type} - {stop_loss_trailing_timer} min -> Switch to trailing stop_loss"
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


class Status_DT:
    def __init__(self, settings: dict):
        self.BULL = InstrumentStatus("BULL")
        self.BEAR = InstrumentStatus("BEAR")
        self.day_time = "morning"
        self.settings = settings

    def update_day_time(self) -> None:
        current_time = datetime.now()
        old_day_time = self.day_time

        if current_time <= current_time.replace(hour=9, minute=0):
            """
            Trading starts at 9:00 AM
            """
            self.day_time = "morning"

            time.sleep(60)
        
        elif current_time <= current_time.replace(hour=10, minute=0):
            """
            I have enough data on Volume at 10:00 AM. 
            Data on Volume is available only from AVANZA, so I merge this data into YAHOO while this day_time
            """
            self.day_time = "morning_transition"

        else:
            """
            Normal trading
            """
            self.day_time = "day"

        if current_time >= current_time.replace(hour=17, minute=25):
            """
            Swedish market is closed, however, certificates are still available for trading. 
            This transition time has many gaps, so I stop trading for 10 minutes
            """
            self.day_time = "evening_transition"

        if current_time >= current_time.replace(hour=17, minute=35):
            """
            Swedish market is closed, I continue trading with certificates till 18.30 or until all certificates are sold.
            No buy orders are allowed at this time
            """
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
                """
                Trading is completed for the day
                """
                self.day_time = "night"

        if old_day_time != self.day_time:
            log.warning(f"Day time: {old_day_time} -> {self.day_time}")

    def get_instrument(self, instrument_type: str) -> InstrumentStatus:
        return self.BULL if instrument_type == "BULL" else self.BEAR

    def update_instrument(
        self, instrument_type: str, certificate_info: dict, active_order: dict
    ) -> InstrumentStatus:
        instrument_status = self.get_instrument(instrument_type)

        instrument_status.active_order = active_order
        instrument_status.spread = certificate_info.get("spread")
        instrument_status.price_current = certificate_info.get("sell")

        instrument_status.update_prices_on_position(
            certificate_info["positions"],
            self.settings["limits_percent"],
        )

        instrument_status.update_on_active_buy_order(
            self.settings["limits_percent"],
        )

        instrument_status.set_trailing_stop_loss_after_timer(
            self.settings["stop_loss_trailing_timer"]
        )

        if instrument_status.check_trade_is_completed():
            setattr(self, instrument_type, InstrumentStatus(instrument_type))

            instrument_status = self.get_instrument(instrument_type)

        return instrument_status

    def update_instrument_trading_limits(
        self, instrument_type: str, new_relative_price: Optional[float]
    ) -> None:
        if new_relative_price is None:
            return

        instrument_status = self.get_instrument(instrument_type)

        instrument_status.update_on_new_signal(
            self.settings["limits_percent"], new_relative_price
        )
