"""
This module contains a Status class for Day trading. Status of each instrument and time_of_day with their methods
"""

import time
import logging
from datetime import datetime


log = logging.getLogger("main.utils.status_dt")


class Status_DT:
    def __init__(self):
        self.BULL = dict()
        self.BEAR = dict()
        self.day_time = "morning"

    def get_instrument(self, instrument_type):
        return self.BULL if instrument_type == "BULL" else self.BEAR

    def update_day_time(self):
        current_time = datetime.now()

        if current_time <= current_time.replace(hour=9, minute=40):
            time.sleep(60)
            self.day_time = "morning"

        elif current_time >= current_time.replace(hour=17, minute=25):
            self.day_time = "evening"

            if (current_time >= current_time.replace(hour=18, minute=30)) or (
                not any(
                    [
                        (
                            self.get_instrument(instrument_type).get(
                                "has_position_bool"
                            )
                            or len(
                                self.get_instrument(instrument_type)[
                                    "active_order_dict"
                                ]
                            )
                            > 0
                        )
                        for instrument_type in ["BULL", "BEAR"]
                    ]
                )
            ):
                self.day_time = "night"

        else:
            self.day_time = "day"

    def update_instrument(
        self, instrument_type, latest_instrument_status_dict, take_profit_percentage
    ):
        instrument_status_dict = self.get_instrument(instrument_type)

        if latest_instrument_status_dict.get("has_position_bool"):
            instrument_status_dict["trailing_stop_loss_price"] = max(
                instrument_status_dict.get("trailing_stop_loss_price", 0),
                latest_instrument_status_dict.pop("trailing_stop_loss_price", 0),
                instrument_status_dict.get("stop_loss_price", 0),
            )

            if not instrument_status_dict.get("has_position_bool"):
                instrument_status_dict["buy_time"] = datetime.now()

                log.info(
                    f'{instrument_type}: Stop loss: {latest_instrument_status_dict["stop_loss_price"]}, Take profit: {latest_instrument_status_dict["take_profit_price"]}'
                )

            if (
                datetime.now() - instrument_status_dict["buy_time"]
            ).seconds > 240 and not instrument_status_dict["trailing_stop_loss_bool"]:
                instrument_status_dict["trailing_stop_loss_bool"] = True

                log.info("4 min -> Switch to tighter stop_loss and take_profit prices")

            instrument_status_dict.update(latest_instrument_status_dict)

            if instrument_status_dict.get("trailing_stop_loss_bool"):
                instrument_status_dict["stop_loss_price"] = instrument_status_dict[
                    "trailing_stop_loss_price"
                ]

                instrument_status_dict["take_profit_price"] = round(
                    instrument_status_dict["stop_loss_price"] * take_profit_percentage,
                    2,
                )

        else:
            if instrument_status_dict.get("has_position_bool"):
                log.warning("<<< Trade is complete")

            instrument_status_dict = {
                **latest_instrument_status_dict,
                **{
                    "buy_time": None,
                    "trailing_stop_loss_bool": False,
                    "trailing_stop_loss_price": 0,
                },
            }

        setattr(self, instrument_type, instrument_status_dict)
