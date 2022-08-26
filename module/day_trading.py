import time
import logging
import platform
import traceback
import yfinance as yf
from datetime import datetime, timedelta

from requests import ReadTimeout

from .utils import Plot
from .utils import History
from .utils import Context
from .utils import TeleLog
from .utils import Settings
from .utils import Instrument
from .utils import Strategy_CS


log = logging.getLogger("main.day_trading_cs")


class Trading:
    def __init__(self, user, account_ids_dict, settings_dict):
        self.settings_trade_dict = settings_dict["trade_dict"]

        self.end_of_day_bool = False
        self.account_ids_dict = account_ids_dict

        self.ava = Context(user, account_ids_dict, skip_lists=True)
        self.strategies_dict = Strategy_CS.load("DT_CS")
        self.instruments_obj = Instrument(self.settings_trade_dict["multiplier"])

        self.overwrite_last_line = {"bool": True, "message_list": []}

    def _check_last_candle_buy(
        self, strategy_obj, row, strategies_dict, instrument_type
    ):
        def _get_ta_signal(row, ta_indicator):
            ta_signal = None

            if strategy_obj.ta_indicators_dict[ta_indicator]["buy"](row):
                ta_signal = "BULL"

            elif strategy_obj.ta_indicators_dict[ta_indicator]["sell"](row):
                ta_signal = "BEAR"

            return ta_signal

        def _get_cs_signal(row, patterns_list):
            cs_signal, cs_pattern = None, None

            for pattern in patterns_list:
                if row[pattern] > 0:
                    cs_signal = "BULL"
                elif row[pattern] < 0:
                    cs_signal = "BEAR"

                if cs_signal is not None:
                    cs_pattern = pattern
                    break

            return cs_signal, cs_pattern

        ta_indicator, cs_pattern = None, None
        for ta_indicator in strategies_dict:
            ta_signal = _get_ta_signal(row, ta_indicator)
            if ta_signal is None:
                continue

            cs_signal, cs_pattern = _get_cs_signal(
                row,
                strategies_dict.get(ta_indicator, list()),
            )
            if cs_signal is None:
                continue

            if cs_signal == ta_signal == instrument_type:
                log.warning(
                    f">>> signal - BUY: {instrument_type}-{ta_indicator}-{cs_pattern} at {row.name}"
                )
                return True

        return False

    def get_signal(self, strategies_dict, instrument_type):
        history_obj = History(
            self.instruments_obj.ids_dict["MONITORING"]["YAHOO"],
            "2d",
            "1m",
            cache="skip",
        )

        strategy_obj = Strategy_CS(
            history_obj.history_df,
            order_price_limits_dict=self.settings_trade_dict["limits_dict"],
        )

        strategies_dict = (
            strategies_dict if strategies_dict else strategy_obj.load("DT_CS")
        )

        last_full_candle_index = -2

        if (datetime.now() - strategy_obj.history_df.iloc[last_full_candle_index].name.replace(tzinfo=None)).seconds > 120:  # type: ignore
            log.error(
                f"Last candle is outdated: {strategy_obj.history_df.iloc[last_full_candle_index].name}"
            )
            return

        last_candle_signal_buy_bool = self._check_last_candle_buy(
            strategy_obj,
            strategy_obj.history_df.iloc[last_full_candle_index],
            strategies_dict[instrument_type],
            instrument_type,
        )

        return last_candle_signal_buy_bool

    def check_instrument_status(self, instrument_type):
        instrument_id = str(self.instruments_obj.ids_dict["TRADING"][instrument_type])

        instrument_status_dict = {
            "has_position_bool": False,
            "active_order_dict": dict(),
            "stop_loss_price": None,
            "take_profit_price": None,
            "current_price": None,
        }

        # Check if instrument has a position
        certificate_info_dict = self.ava.get_certificate_info(
            self.instruments_obj.ids_dict["TRADING"][instrument_type]
        )

        for position_dict in certificate_info_dict["positions"]:
            instrument_status_dict.update(
                {
                    "has_position_bool": True,
                    "current_price": certificate_info_dict["sell"],
                    "stop_loss_price": round(
                        position_dict["averageAcquiredPrice"]
                        * self.settings_trade_dict["limits_dict"]["SL"],
                        2,
                    ),
                    "take_profit_price": round(
                        position_dict["averageAcquiredPrice"]
                        * self.settings_trade_dict["limits_dict"]["TP"],
                        2,
                    ),
                    "trailing_stop_loss_price_latest": round(
                        certificate_info_dict["sell"]
                        * self.settings_trade_dict["limits_dict"]["SL_trailing"],
                        2,
                    ),
                }
            )

        # Check if active order exists
        deals_and_orders_dict = self.ava.ctx.get_deals_and_orders()
        active_orders_list = (
            list() if not deals_and_orders_dict else deals_and_orders_dict["orders"]
        )

        for order_dict in active_orders_list:
            if (order_dict["orderbook"]["id"] != instrument_id) or (
                order_dict["rawStatus"] != "ACTIVE"
            ):
                continue

            instrument_status_dict["active_order_dict"] = order_dict

            if order_dict["type"] == "BUY":
                instrument_status_dict.update(
                    {
                        "stop_loss_price": round(
                            order_dict["price"]
                            * self.settings_trade_dict["limits_dict"]["SL"],
                            2,
                        ),
                        "take_profit_price": round(
                            order_dict["price"]
                            * self.settings_trade_dict["limits_dict"]["TP"],
                            2,
                        ),
                    }
                )

        return instrument_status_dict

    def place_order(self, signal, instrument_type, instrument_status_dict):
        if (signal == "buy" and instrument_status_dict["has_position_bool"]) or (
            signal == "sell" and not instrument_status_dict["has_position_bool"]
        ):
            return

        self.overwrite_last_line["bool"] = False

        certificate_info_dict = self.ava.get_certificate_info(
            self.instruments_obj.ids_dict["TRADING"][instrument_type]
        )

        order_data_dict = {
            "name": instrument_type,
            "signal": signal,
            "account_id": list(self.account_ids_dict.values())[0],
            "order_book_id": self.instruments_obj.ids_dict["TRADING"][instrument_type],
            "max_return": 0,
        }

        if certificate_info_dict[signal] is None:
            log.error(f"Certificate info could not be fetched")
            return

        if signal == "buy":
            order_data_dict.update(
                {
                    "price": certificate_info_dict[signal],
                    "volume": int(
                        self.settings_trade_dict["budget"]
                        // certificate_info_dict[signal]
                    ),
                    "budget": self.settings_trade_dict["budget"],
                }
            )

        elif signal == "sell":
            price = (
                certificate_info_dict[signal]
                if certificate_info_dict[signal]
                < instrument_status_dict["stop_loss_price"]
                else instrument_status_dict["take_profit_price"]
            )

            order_data_dict.update(
                {
                    "price": price,
                    "volume": certificate_info_dict["positions"][0]["volume"],
                    "profit": certificate_info_dict["positions"][0]["profitPercent"],
                }
            )

        self.ava.create_orders(
            [order_data_dict],
            signal,
        )

        log.warning(
            f'{order_data_dict["signal"].upper()}: {order_data_dict["name"]} - {order_data_dict["price"]}'
        )

    def update_order(
        self,
        signal,
        instrument_type,
        instrument_status_dict,
    ):
        certificate_info_dict = self.ava.get_certificate_info(
            self.instruments_obj.ids_dict["TRADING"][instrument_type]
        )

        if certificate_info_dict[signal] is None:
            return

        self.overwrite_last_line["bool"] = False

        instrument_type = instrument_status_dict["active_order_dict"]["orderbook"][
            "name"
        ].split(" ")[0]
        log.warning(
            f'{signal.upper()} (UPD): {instrument_type} - {instrument_status_dict["active_order_dict"]["price"]} -> {certificate_info_dict[signal]}'
        )

        self.ava.update_order(
            instrument_status_dict["active_order_dict"], certificate_info_dict[signal]
        )

    def combine_stdout_line(self, instrument_type):
        instrument_status_dict = self.check_instrument_status(instrument_type)
        if instrument_status_dict["has_position_bool"]:
            self.overwrite_last_line["message_list"].append(
                f'{instrument_type} - {instrument_status_dict["stop_loss_price"]} < {instrument_status_dict["current_price"]} < {instrument_status_dict["take_profit_price"]}'
            )

    def update_last_stdout_line(self):
        if self.overwrite_last_line["bool"]:
            LINE_UP = "\033[1A"
            LINE_CLEAR = "\x1b[2K"

            print(LINE_UP, end=LINE_CLEAR)

        print(
            f'[{datetime.now().strftime("%H:%M")}] {" ||| ".join(self.overwrite_last_line["message_list"])}'
        )

        self.overwrite_last_line["bool"] = True


class Day_Trading_CS:
    def __init__(self, user, account_ids_dict, settings_dict):
        self.settings_trade_dict = settings_dict["trade_dict"]

        self.trading_obj = Trading(user, account_ids_dict, settings_dict)
        self.balance_dict = {"before": 0, "after": 0}

        self.instruments_status_dict = {
            "BULL": dict(),
            "BEAR": dict(),
            "day_time": "morning",
        }

        while True:
            try:
                if (
                    self.run_analysis(settings_dict["log_to_telegram"])
                    == "Done for the day"
                ):
                    break

            except ReadTimeout:
                self.trading_obj.ava.ctx = self.trading_obj.ava.get_ctx(user)

    def update_trading_day_time(self):
        current_time = datetime.now()

        if current_time <= current_time.replace(hour=9, minute=40):
            time.sleep(60)
            self.instruments_status_dict["day_time"] = "morning"

        elif current_time >= current_time.replace(hour=17, minute=30):
            self.instruments_status_dict["day_time"] = "evening"

            if (current_time >= current_time.replace(hour=18, minute=30)) or (
                not any(
                    [
                        (
                            self.instruments_status_dict[instrument_type][
                                "has_position_bool"
                            ]
                            or len(
                                self.instruments_status_dict[instrument_type][
                                    "active_order_dict"
                                ]
                            )
                            > 0
                        )
                        for instrument_type in ["BULL", "BEAR"]
                    ]
                )
            ):
                self.instruments_status_dict["day_time"] = "night"

        else:
            self.instruments_status_dict["day_time"] = "day"

    def update_instrument_status(self, instrument_type):
        self.instruments_status_dict[instrument_type].update(
            self.trading_obj.check_instrument_status(instrument_type)
        )

        if self.instruments_status_dict[instrument_type]["has_position_bool"]:

            if self.instruments_status_dict[instrument_type].get("buy_time") is None:
                self.instruments_status_dict[instrument_type][
                    "buy_time"
                ] = datetime.now()

                log.info(
                    f'{instrument_type}: Stop loss: {self.instruments_status_dict[instrument_type]["stop_loss_price"]}, Take profit: {self.instruments_status_dict[instrument_type]["take_profit_price"]}'
                )

            self.instruments_status_dict[instrument_type][
                "trailing_stop_loss_price"
            ] = max(
                self.instruments_status_dict[instrument_type].get(
                    "trailing_stop_loss_price", 0
                ),
                self.instruments_status_dict[instrument_type].pop(
                    "trailing_stop_loss_price_latest", 0
                ),
                self.instruments_status_dict[instrument_type]["stop_loss_price"],
            )

            # Switch to tighter stop loss price if order is not fullfilled after 4 min
            if (
                datetime.now()
                - self.instruments_status_dict[instrument_type]["buy_time"]
            ).seconds > 240:
                self.instruments_status_dict[instrument_type][
                    "stop_loss_price"
                ] = self.instruments_status_dict[instrument_type][
                    "trailing_stop_loss_price"
                ]

        else:
            self.instruments_status_dict[instrument_type].update(
                {"buy_time": None, "trailing_stop_loss_price": 0}
            )

        return self.instruments_status_dict[instrument_type]

    def check_instrument_for_buy_action(self, strategies_dict, instrument_type):
        self.update_instrument_status(instrument_type)

        if self.instruments_status_dict[instrument_type]["has_position_bool"]:
            return

        # Update buy order if there is no position, but open order exists
        if self.instruments_status_dict[instrument_type]["active_order_dict"]:
            self.trading_obj.update_order(
                "buy",
                instrument_type,
                self.instruments_status_dict[instrument_type],
            )
            time.sleep(2)

        # Create buy order if there is no position
        else:
            buy_instrument_bool = self.trading_obj.get_signal(
                strategies_dict, instrument_type
            )
            if not buy_instrument_bool:
                return

            # Sell the other instrument if exists
            self.check_instrument_for_sell_action(
                "BEAR" if instrument_type == "BULL" else "BULL",
                enforce_sell_bool=True,
            )
            time.sleep(1)

            self.trading_obj.place_order(
                "buy", instrument_type, self.instruments_status_dict[instrument_type]
            )
            time.sleep(2)

    def check_instrument_for_sell_action(
        self, instrument_type, enforce_sell_bool=False
    ):
        self.update_instrument_status(instrument_type)

        if not self.instruments_status_dict[instrument_type]["has_position_bool"]:
            return

        # Create take_profit sell orders
        if not self.instruments_status_dict[instrument_type]["active_order_dict"]:
            self.trading_obj.place_order(
                "sell", instrument_type, self.instruments_status_dict[instrument_type]
            )

        # Check if hit stop loss (or enforce) -> sell
        else:
            certificate_info_dict = self.trading_obj.ava.get_certificate_info(
                self.trading_obj.instruments_obj.ids_dict["TRADING"][instrument_type]
            )

            if (
                certificate_info_dict["sell"]
                < self.instruments_status_dict[instrument_type]["stop_loss_price"]
            ) or enforce_sell_bool:
                self.trading_obj.update_order(
                    "sell",
                    instrument_type,
                    self.instruments_status_dict[instrument_type],
                )

    # MAIN method
    def run_analysis(self, log_to_telegram):
        self.balance_dict["before"] = sum(
            self.trading_obj.ava.get_portfolio()["buying_power"].values()
        )

        log.info(
            f'> Running trading for account(s): {" & ".join(self.trading_obj.account_ids_dict)} [{self.balance_dict["before"]}]'
        )

        strategies_dict = dict()
        while True:
            self.update_trading_day_time()
            self.trading_obj.overwrite_last_line["message_list"] = []

            if self.instruments_status_dict["day_time"] == "morning":
                continue

            elif self.instruments_status_dict["day_time"] == "night":
                break

            # Walk through instruments
            for instrument_type in ["BULL", "BEAR"]:

                if self.instruments_status_dict["day_time"] != "evening":
                    self.check_instrument_for_buy_action(
                        strategies_dict, instrument_type
                    )

                self.check_instrument_for_sell_action(instrument_type)

                self.trading_obj.combine_stdout_line(instrument_type)

            self.trading_obj.update_last_stdout_line()

            time.sleep(10)

        self.balance_dict["after"] = sum(
            self.trading_obj.ava.get_portfolio()["buying_power"].values()
        )

        log.info(f'> End of the day. [{self.balance_dict["after"]}]')

        if log_to_telegram:
            TeleLog(
                day_trading_stats_dict={
                    "balance_before": self.balance_dict["before"],
                    "balance_after": self.balance_dict["after"],
                    "budget": self.settings_trade_dict["budget"],
                }
            )

        return "Done for the day"


def run():
    settings_json = Settings().load()

    for user, settings_per_account_dict in settings_json.items():
        for settings_dict in settings_per_account_dict.values():
            if not settings_dict.get("run_day_trading", False):
                continue

            try:
                Day_Trading_CS(user, settings_dict["accounts"], settings_dict)

            except Exception as e:
                log.error(f">>> {e}: {traceback.format_exc()}")

                TeleLog(crash_report=f"DT script has crashed: {e}")

            return
