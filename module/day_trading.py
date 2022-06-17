"""
This module is the "frontend" meant for everyday run. It will perform analysis on stocks and trigger trades.
It will import other modules to run the analysis on the stocks -> place orders -> dump log in Telegram.py
"""


import time
import logging
from pprint import pprint

from .utils import Instrument
from .utils import Settings
from .utils import Strategy
from .utils import Context
from .utils import Plot


log = logging.getLogger("main.day_trading")


class Day_Trading:
    def __init__(self, user, accounts_dict, multiplier, budget):
        self.ava = Context(user, accounts_dict, skip_lists=True)
        instruments_dict = Instrument(multiplier)

        self.run_analysis(accounts_dict, instruments_dict, budget)

    def plot_ticker(self, strategy_obj, instrument_type):
        log.info(f"Plotting {instrument_type}")

        plot_obj = Plot(
            data_df=strategy_obj.history_df,
            title=f'{strategy_obj.ticker_obj.info["symbol"]} ({strategy_obj.ticker_obj.info["shortName"]}) - {strategy_obj.summary["max_output"]["strategy"]}',
        )
        plot_obj.create_extra_panels()
        plot_obj.show_single_ticker()

    def run_analysis(self, accounts_dict, instruments_dict, budget):
        log.info(f'Running analysis for account(s): {" & ".join(accounts_dict)}')
        self.ava.remove_active_orders(account_ids_list=list(accounts_dict.values()))

        counter = 1
        strategies_dict = Strategy.load("DT")
        transactions_dict = {"BULL": [], "BEAR": []}
        while True:
            for instrument_type in transactions_dict.keys():
                log.info(f"-------------------{instrument_type}-------------------")

                # Analize
                strategy_obj = Strategy(
                    instruments_dict.ids_dict["MONITORING"]["YAHOO"],
                    19002,
                    self.ava,
                    strategies_list=(
                        strategies_dict.get(instrument_type, list())
                        if counter % 20 == 0
                        else list()
                    ),
                    period="1d",
                    interval="1m",
                    adjust_history_dict={
                        "base": 100,
                        "inverse": True if instrument_type == "BEAR" else False,
                    },
                    skip_points=0,
                )

                # self.plot_ticker(strategy_obj, instrument_type)

                if strategy_obj.summary["max_output"]["result"] <= 1000:
                    continue

                Strategy.dump("DT", strategies_dict)

                # Print
                for i, (strategy_name, strategy_dict) in enumerate(
                    strategy_obj.summary["sorted_strategies_list"][:5]
                ):
                    log.info(
                        f"Strategy {i+1} - {strategy_name}: {strategy_dict['signal']} ({strategy_dict['result']})"
                    )
                    strategies_dict[instrument_type] = [
                        i
                        for (i, _) in strategy_obj.summary["sorted_strategies_list"][
                            :50
                        ]
                    ]

                # Order
                ## Research
                trading_instrument_id = instruments_dict.ids_dict["TRADING"][
                    instrument_type
                ]

                certificate_dict = self.ava.get_certificate_price(trading_instrument_id)

                signal = strategy_obj.summary["max_output"]["signal"]

                last_action = None
                if len(certificate_dict["positions"]) > 0:
                    last_action = "buy"
                elif len(transactions_dict[instrument_type]) > 0:
                    transactions_dict[instrument_type][-1]["type"]

                self.ava.remove_active_orders(
                    account_ids_list=list(accounts_dict.values()),
                    orderbook_ids_list=[trading_instrument_id],
                )
                if (len(certificate_dict["positions"]) > 0 and signal == "buy") or (
                    len(certificate_dict["positions"]) == 0 and signal == "sell"
                ):
                    continue

                if last_action == signal:
                    transactions_dict[instrument_type].pop(-1)

                ## Place
                if signal == "buy":
                    self.ava.create_orders(
                        [
                            {
                                "account_id": list(accounts_dict.values())[0],
                                "order_book_id": trading_instrument_id,
                                "budget": budget,
                                "price": certificate_dict[signal],
                                "volume": budget // certificate_dict[signal],
                                "name": instrument_type,
                                "max_return": strategy_obj.summary["max_output"][
                                    "result"
                                ],
                            }
                        ],
                        "buy",
                    )

                elif signal == "sell":
                    self.ava.create_orders(
                        [
                            {
                                "account_id": list(accounts_dict.values())[0],
                                "order_book_id": trading_instrument_id,
                                "volume": certificate_dict["positions"][0]["volume"],
                                "price": certificate_dict[signal],
                                "profit": certificate_dict["positions"][0][
                                    "profitPercent"
                                ],
                                "name": instrument_type,
                                "max_return": strategy_obj.summary["max_output"][
                                    "result"
                                ],
                            }
                        ],
                        "sell",
                    )

                transactions_dict[instrument_type].append(
                    {
                        "type": signal,
                        "price": certificate_dict[signal],
                        "strategy": strategy_obj.summary["max_output"]["strategy"],
                    }
                )

                log.warning(
                    f'{instrument_type} - {signal} - {certificate_dict[signal]} - {strategy_obj.summary["max_output"]["strategy"]} - {strategy_obj.summary["max_output"]["result"]}'
                )
                time.sleep(10)

            counter += 1


def run(multiplier, budget):
    settings_json = Settings().load()

    user = list(settings_json.keys())[0]
    accounts_dict = dict()
    for settings_per_account_dict in settings_json.values():
        for settings_dict in settings_per_account_dict.values():
            if not settings_dict["run_day_trading"]:
                continue

            accounts_dict.update(settings_dict["accounts"])

    Day_Trading(user, accounts_dict, multiplier, budget)
