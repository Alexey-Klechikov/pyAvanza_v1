"""
This module contains a Status class for Day trading. Status of each instrument and time_of_day with their methods
"""

import time
import logging
from datetime import datetime


log = logging.getLogger("main.utils.status_dt")


class Status_DT:
    def __init__(self, settings_dict):
        self.BULL = dict()
        self.BEAR = dict()
        self.day_time = "morning"
        self.settings_dict = settings_dict

    def get_instrument(self, inst_type):
        return self.BULL if inst_type == "BULL" else self.BEAR

    def update_day_time(self):
        current_time = datetime.now()

        old_day_time = self.day_time

        if current_time <= current_time.replace(hour=9, minute=40):
            time.sleep(60)
            self.day_time = "morning"

        elif current_time >= current_time.replace(hour=17, minute=25):
            self.day_time = "evening"

            if (current_time >= current_time.replace(hour=18, minute=30)) or (
                not any(
                    [
                        (
                            self.get_instrument(inst_type).get("has_position_bool")
                            or len(
                                self.get_instrument(inst_type).get("active_order_dict", [])
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

    def update_instrument(self, inst_type, latest_inst_status_dict):
        inst_status_dict = self.get_instrument(inst_type)

        if latest_inst_status_dict.get("has_position_bool"):
            inst_status_dict["trailing_stop_loss_price"] = max(
                inst_status_dict.get("trailing_stop_loss_price", 0),
                latest_inst_status_dict.pop("trailing_stop_loss_price", 0),
                inst_status_dict.get("stop_loss_price", 0),
            )

            if not inst_status_dict.get("has_position_bool"):
                inst_status_dict["buy_time"] = datetime.now()

                log.info(
                    f'{inst_type}: Stop loss: {latest_inst_status_dict["stop_loss_price"]}, Take profit: {latest_inst_status_dict["take_profit_price"]}'
                )

            if (datetime.now() - inst_status_dict["buy_time"]).seconds > (
                int(self.settings_dict["trailing_SL_timer"]) * 60
            ) and not inst_status_dict["trailing_stop_loss_bool"]:
                inst_status_dict["trailing_stop_loss_bool"] = True

                log.info(
                    f"{self.settings_dict['trailing_SL_timer']} min -> Switch to trailing stop_loss"
                )

            inst_status_dict.update(latest_inst_status_dict)

            if inst_status_dict.get("trailing_stop_loss_bool"):
                inst_status_dict["stop_loss_price"] = inst_status_dict[
                    "trailing_stop_loss_price"
                ]

                inst_status_dict["take_profit_price"] = round(
                    inst_status_dict["stop_loss_price"]
                    * float(self.settings_dict["limits_dict"]["TP_trailing"]),
                    2,
                )

        else:
            if inst_status_dict.get("has_position_bool"):
                log.warning(f"<<< Trade is complete ({inst_type})")

            inst_status_dict = {
                **latest_inst_status_dict,
                **{
                    "buy_time": None,
                    "trailing_stop_loss_bool": False,
                    "trailing_stop_loss_price": 0,
                },
            }

        setattr(self, inst_type, inst_status_dict)

    def raise_instrument_trading_limits(self, inst_type, new_relative_price):
        inst_status_dict = self.get_instrument(inst_type)

        inst_status_dict.update(
            {
                "buy_time": datetime.now(),
                "stop_loss_price": self.settings_dict["limits_dict"]["SL"]
                * new_relative_price,
                "take_profit_price": self.settings_dict["limits_dict"]["TP"]
                * new_relative_price,
            }
        )

        log.info(
            f'{inst_type}: Stop loss: {inst_status_dict["stop_loss_price"]}, Take profit: {inst_status_dict["take_profit_price"]}'
        )

        setattr(self, inst_type, inst_status_dict)
