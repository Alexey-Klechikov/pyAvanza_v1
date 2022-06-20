"""
This module is the "frontend" meant for everyday run. It will perform analysis on stocks and trigger trades.
It will import other modules to run the analysis on the stocks -> place orders -> dump log in Telegram.py
"""


import time
import logging
from pprint import pprint
from datetime import datetime

from .utils import Instrument
from .utils import Settings
from .utils import Strategy
from .utils import Context
from .utils import Plot


log = logging.getLogger("main.day_trading")


class Day_Trading:
    def __init__(self, user, account_ids_dict, multiplier, budget):
        self.budget = budget
        self.account_ids_dict = account_ids_dict
        self.end_of_day_bool = False
        self.ava = Context(user, account_ids_dict, skip_lists=True)
        self.strategies_dict = Strategy.load("DT")
        self.instruments_dict = Instrument(multiplier)
        self.instruments_status_dict = {"BULL": "sell", "BEAR": "sell"}

        self.run_analysis()

    # HELPER functions
    def plot_ticker(self, strategy_obj, instrument_type):
        plot_obj = Plot(
            data_df=strategy_obj.history_df,
            title=f'{instrument_type} ({strategy_obj.ticker_obj.info["shortName"]}) - {strategy_obj.summary["max_output"]["strategy"]}',
        )
        plot_obj.create_extra_panels()
        plot_obj.show_single_ticker()

    def get_strategy_obj(self, instrument_type):
        try:
            strategy_obj = Strategy(
                self.instruments_dict.ids_dict["MONITORING"]["YAHOO"],
                self.instruments_dict.ids_dict["MONITORING"]["AVA"],
                self.ava,
                strategies_list=self.strategies_dict.get(instrument_type, list()),
                period="1d",
                interval="2m",
                adjust_history_dict={
                    "base": 100,
                    "inverse": True if instrument_type == "BEAR" else False,
                },
                skip_points=0,
            )
        except Exception as e:
            log.error(f"Error in getting strategy_obj: {e}")
            strategy_obj = None

        return strategy_obj

    def save_strategies(self, instrument_type, strategy_obj):
        self.strategies_dict[instrument_type] = list()
        for i, (strategy_name, strategy_dict) in enumerate(
            strategy_obj.summary["sorted_strategies_list"][
                :50
            ]  # HERE I change number of strategies to save
        ):
            self.strategies_dict[instrument_type].append(strategy_name)

            if i < 5:
                log.info(
                    f"Strategy {strategy_name}: {strategy_dict['signal']} ({strategy_dict['result']})"
                )

            if i == 0:  # HERE I change number of strategies to save
                break

        Strategy.dump("DT", self.strategies_dict)

    def get_signal(self, instrument_type, strategy_obj):
        self.ava.remove_active_orders(
            account_ids_list=list(self.account_ids_dict.values()),
            orderbook_ids_list=[
                self.instruments_dict.ids_dict["TRADING"][instrument_type]
            ],
        )
        certificate_info_dict = self.ava.get_certificate_info(
            self.instruments_dict.ids_dict["TRADING"][instrument_type]
        )
        signal = (
            "sell"
            if self.end_of_day_bool
            else strategy_obj.summary["max_output"]["signal"]
        )
        self.instruments_status_dict[instrument_type] = (
            "buy" if len(certificate_info_dict["positions"]) > 0 else "sell"
        )

        if (self.instruments_status_dict[instrument_type] == signal) or (
            strategy_obj.summary["max_output"]["result"] <= 1000
            and not self.end_of_day_bool
        ):
            return None, certificate_info_dict

        return signal, certificate_info_dict

    def place_order(self, instrument_type, strategy_obj, signal, certificate_info_dict):
        if signal == "buy":
            self.ava.create_orders(
                [
                    {
                        "account_id": list(self.account_ids_dict.values())[0],
                        "order_book_id": self.instruments_dict.ids_dict["TRADING"][
                            instrument_type
                        ],
                        "budget": self.budget,
                        "price": certificate_info_dict[signal],
                        "volume": int(self.budget // certificate_info_dict[signal]),
                        "name": instrument_type,
                        "max_return": strategy_obj.summary["max_output"]["result"],
                    }
                ],
                "buy",
            )

        elif signal == "sell":
            self.ava.create_orders(
                [
                    {
                        "account_id": list(self.account_ids_dict.values())[0],
                        "order_book_id": self.instruments_dict.ids_dict["TRADING"][
                            instrument_type
                        ],
                        "volume": certificate_info_dict["positions"][0]["volume"],
                        "price": certificate_info_dict[signal],
                        "profit": certificate_info_dict["positions"][0][
                            "profitPercent"
                        ],
                        "name": instrument_type,
                        "max_return": strategy_obj.summary["max_output"]["result"],
                    }
                ],
                "sell",
            )

        log.warning(
            " - ".join(
                [
                    str(i)
                    for i in [
                        instrument_type,
                        signal,
                        certificate_info_dict[signal],
                        strategy_obj.summary["max_output"]["strategy"],
                        strategy_obj.summary["max_output"]["result"],
                        "profit: " + "-"
                        if signal == "buy"
                        else str(
                            certificate_info_dict["positions"][0]["profitPercent"]
                        ),
                    ]
                ]
            )
        )

    # MAIN functions
    def run_analysis(self):
        log.info(
            f'Running analysis for account(s): {" & ".join(self.account_ids_dict)}'
        )
        self.ava.remove_active_orders(
            account_ids_list=list(self.account_ids_dict.values())
        )

        while True:
            current_time = datetime.now()

            if current_time.hour < 10:
                continue

            if current_time.hour >= 17:
                self.end_of_day_bool = True

            if current_time.minute == 0:
                self.strategies_dict = {}

            for instrument_type in list(self.instruments_status_dict.keys()):
                log.info(f"-------------------{instrument_type}-------------------")

                strategy_obj = self.get_strategy_obj(instrument_type)

                if strategy_obj is None:
                    continue

                self.plot_ticker(strategy_obj, instrument_type)

                self.save_strategies(instrument_type, strategy_obj)

                signal, certificate_info_dict = self.get_signal(
                    instrument_type, strategy_obj
                )

                if signal is not None:
                    self.place_order(
                        instrument_type, strategy_obj, signal, certificate_info_dict
                    )

                    time.sleep(20)

            time.sleep(60)

            if (
                self.end_of_day_bool
                and "buy" not in self.instruments_status_dict.values()
            ):
                break


def run(multiplier, budget):
    settings_json = Settings().load()

    user = list(settings_json.keys())[0]
    account_ids_dict = dict()
    for settings_per_account_dict in settings_json.values():
        for settings_dict in settings_per_account_dict.values():
            if not settings_dict["run_day_trading"]:
                continue

            account_ids_dict.update(settings_dict["accounts"])

    Day_Trading(user, account_ids_dict, multiplier, budget)
