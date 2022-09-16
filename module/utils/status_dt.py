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
                    "spread": latest_instrument_status.get("spread"),
                    "active_order": latest_instrument_status.get("active_order"),
                    "price_current": latest_instrument_status.get("price_current"),
                    "price_buy": instrument_status.get(
                        "price_buy",
                        latest_instrument_status.get("price_current"),
                    ),
                    "price_take_profit_super": latest_instrument_status.get(
                        "price_take_profit_super"
                    ),
                    "price_stop_loss": instrument_status.get(
                        "price_stop_loss",
                        latest_instrument_status.get("price_stop_loss", 0),
                    ),
                    "price_take_profit": instrument_status.get(
                        "price_take_profit",
                        latest_instrument_status.get("price_take_profit", 0),
                    ),
                }
            )

            instrument_status["price_stop_loss_trailing"] = max(
                instrument_status.get("price_stop_loss_trailing", 0),
                latest_instrument_status.get("price_stop_loss_trailing", 0),
                instrument_status.get("price_stop_loss", 0),
            )

            if not instrument_status.get("has_position"):
                instrument_status.update(
                    {"buy_time": datetime.now(), "has_position": True}
                )

                log.info(
                    f'{instrument_type} - (SET limits): SL: {instrument_status.get("price_stop_loss")}, TP: {instrument_status.get("price_take_profit")}'
                )

            if (datetime.now() - instrument_status["buy_time"]).seconds > (
                int(self.settings["stop_loss_trailing_timer"]) * 60
            ) and not instrument_status.get("trailing_stop_loss_active", False):
                instrument_status["trailing_stop_loss_active"] = True

                log.info(
                    f"{instrument_type} - {self.settings['stop_loss_trailing_timer']} min -> Switch to trailing stop_loss"
                )

            if instrument_status.get("trailing_stop_loss_active"):
                instrument_status["price_stop_loss"] = instrument_status[
                    "price_stop_loss_trailing"
                ]

        else:
            if instrument_status.get("has_position"):

                trade_success_status = "( ? )"
                if (
                    latest_instrument_status["price_current"]
                    >= instrument_status["price_buy"]
                ):
                    trade_success_status = "( + )"
                elif (
                    latest_instrument_status["price_current"]
                    < instrument_status["price_buy"]
                ):
                    trade_success_status = "( - )"

                log.warning(
                    f"<<< {instrument_type} - Trade is complete {trade_success_status}"
                )

            instrument_status = {
                **latest_instrument_status,
                **{
                    "trailing_stop_loss_active": False,
                    "price_stop_loss_trailing": 0,
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
                "price_stop_loss": round(
                    self.settings["limits_percent"]["stop_loss"] * new_relative_price, 2
                ),
                "price_take_profit": round(
                    self.settings["limits_percent"]["take_profit"] * new_relative_price,
                    2,
                ),
            }
        )

        log.info(
            f'{instrument_type} - (UPD limits): SL: {instrument_status["price_stop_loss"]}, TP: {instrument_status["price_take_profit"]}'
        )

        setattr(self, instrument_type, instrument_status)
