"""
This module contains a Status class for Day trading. Status of each instrument and time_of_day with their methods
"""

import time
import logging
from datetime import datetime


log = logging.getLogger("main.utils.status_dt")


class Status_DT:
    def __init__(self, settings: dict):
        self.BULL = dict()
        self.BEAR = dict()
        self.day_time = "morning"
        self.settings = settings

    def get_instrument(self, instrument_type: str) -> dict:
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
                            self.get_instrument(instrument_type).get("has_position")
                            or self.get_instrument(instrument_type).get("active_order")
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
                {
                    "current_price": latest_instrument_status.get("current_price"),
                    "active_order": latest_instrument_status.get("active_order"),
                    "super_take_profit": latest_instrument_status.get(
                        "super_take_profit"
                    ),
                    "stop_loss_price": instrument_status.get(
                        "stop_loss_price",
                        latest_instrument_status.get("stop_loss_price", 0),
                    ),
                    "take_profit_price": instrument_status.get(
                        "take_profit_price",
                        latest_instrument_status.get("take_profit_price", 0),
                    ),
                }
            )

            instrument_status["trailing_stop_loss_price"] = max(
                instrument_status.get("trailing_stop_loss_price", 0),
                latest_instrument_status.get("trailing_stop_loss_price", 0),
                instrument_status.get("stop_loss_price", 0),
            )

            if not instrument_status.get("has_position"):
                instrument_status.update(
                    {"buy_time": datetime.now(), "has_position": True}
                )

                log.info(
                    f'{instrument_type} - (SET limits): SL: {instrument_status.get("stop_loss_price")}, TP: {instrument_status.get("take_profit_price")}'
                )

            if (datetime.now() - instrument_status["buy_time"]).seconds > (
                int(self.settings["trailing_SL_timer"]) * 60
            ) and not instrument_status.get("trailing_stop_loss_active", False):
                instrument_status["trailing_stop_loss_active"] = True

                log.info(
                    f"{instrument_type} - {self.settings['trailing_SL_timer']} min -> Switch to trailing stop_loss"
                )

            if instrument_status.get("trailing_stop_loss_active"):
                instrument_status["stop_loss_price"] = instrument_status[
                    "trailing_stop_loss_price"
                ]

        else:
            if instrument_status.get("has_position"):

                trade_success_status = "(???)"
                if (
                    latest_instrument_status["current_price"]
                    >= instrument_status["take_profit_price"]
                ):
                    trade_success_status = "(+++)"
                elif (
                    latest_instrument_status["current_price"]
                    < instrument_status["stop_loss_price"]
                ):
                    trade_success_status = "(---)"

                log.warning(
                    f"<<< {instrument_type} - Trade is complete {trade_success_status}"
                )

            instrument_status = {
                **latest_instrument_status,
                **{
                    "buy_time": None,
                    "trailing_stop_loss_active": False,
                    "trailing_stop_loss_price": 0,
                },
            }

        setattr(self, instrument_type, instrument_status)

    def update_instrument_trading_limits(
        self, instrument_type: str, new_relative_price: float
    ) -> None:
        instrument_status = self.get_instrument(instrument_type)

        instrument_status.update(
            {
                "buy_time": datetime.now(),
                "trailing_stop_loss_active": False,
                "stop_loss_price": round(
                    self.settings["limits"]["SL"] * new_relative_price, 2
                ),
                "take_profit_price": round(
                    self.settings["limits"]["TP"] * new_relative_price, 2
                ),
            }
        )

        log.info(
            f'{instrument_type} - (UPD limits): SL: {instrument_status["stop_loss_price"]}, TP: {instrument_status["take_profit_price"]}'
        )

        setattr(self, instrument_type, instrument_status)
