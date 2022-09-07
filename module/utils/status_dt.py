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

    def get_instrument(self, inst_type: str) -> dict:
        return self.BULL if inst_type == "BULL" else self.BEAR

    def update_day_time(self) -> None:
        current_time = datetime.now()
        old_day_time = self.day_time

        if current_time <= current_time.replace(hour=9, minute=40):
            self.day_time = "morning"

            time.sleep(60)

        elif current_time >= current_time.replace(hour=17, minute=25):
            self.day_time = "evening"

            if (current_time >= current_time.replace(hour=18, minute=30)) or (
                not any(
                    [
                        (
                            self.get_instrument(inst_type).get("has_position")
                            or len(
                                self.get_instrument(inst_type).get(
                                    "active_order_dict", []
                                )
                            )
                            > 0
                        )
                        for inst_type in ["BULL", "BEAR"]
                    ]
                )
            ):
                self.day_time = "night"

        else:
            self.day_time = "day"

        if old_day_time != self.day_time:
            log.warning(f"Day time: {old_day_time} -> {self.day_time}")

    def update_instrument(self, inst_type: str, latest_instrument_status: dict) -> None:
        instrument_status = self.get_instrument(inst_type)

        if latest_instrument_status.get("has_position"):
            instrument_status.update(
                {
                    "current_price": latest_instrument_status.get("current_price"),
                    "active_order": latest_instrument_status.get("active_order"),
                    "stop_loss_price": instrument_status.get(
                        "stop_loss_price",
                        latest_instrument_status.pop("stop_loss_price", 0),
                    ),
                    "take_profit_price": instrument_status.get(
                        "take_profit_price",
                        latest_instrument_status.pop("take_profit_price", 0),
                    ),
                }
            )

            instrument_status["trailing_stop_loss_price"] = max(
                instrument_status.get("trailing_stop_loss_price", 0),
                latest_instrument_status.pop("trailing_stop_loss_price", 0),
                instrument_status.get("stop_loss_price", 0),
            )

            if not instrument_status.get("has_position"):
                instrument_status.update(
                    {"buy_time": datetime.now(), "has_position": True}
                )

                log.info(
                    f'{inst_type}: Stop loss: {instrument_status.get("stop_loss_price")}, Take profit: {instrument_status.get("take_profit_price")}'
                )

            if (datetime.now() - instrument_status["buy_time"]).seconds > (
                int(self.settings["trailing_SL_timer"]) * 60
            ) and not instrument_status.get("trailing_stop_loss_active", False):
                instrument_status["trailing_stop_loss_active"] = True

                log.info(
                    f"{self.settings['trailing_SL_timer']} min -> Switch to trailing stop_loss"
                )

            if instrument_status.get("trailing_stop_loss_active"):
                instrument_status["stop_loss_price"] = instrument_status[
                    "trailing_stop_loss_price"
                ]

                instrument_status["take_profit_price"] = round(
                    instrument_status["stop_loss_price"]
                    * float(self.settings["limits"]["TP_trailing"]),
                    2,
                )

        else:
            if instrument_status.get("has_position"):
                log.warning(f"<<< Trade is complete ({inst_type})")

            instrument_status = {
                **latest_instrument_status,
                **{
                    "buy_time": None,
                    "trailing_stop_loss_active": False,
                    "trailing_stop_loss_price": 0,
                },
            }

        setattr(self, inst_type, instrument_status)

    def update_instrument_trading_limits(
        self, inst_type: str, new_relative_price: float
    ) -> None:
        instrument_status = self.get_instrument(inst_type)

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
            f'{inst_type}: Update limits: Stop loss: {instrument_status["stop_loss_price"]}, Take profit: {instrument_status["take_profit_price"]}'
        )

        setattr(self, inst_type, instrument_status)
