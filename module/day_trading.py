import time
import logging
import traceback
import yfinance as yf
from datetime import datetime

from requests import ReadTimeout

from .utils import History
from .utils import Context
from .utils import TeleLog
from .utils import Settings
from .utils import Instrument
from .utils import Strategy_DT
from .utils import Status_DT as Status


log = logging.getLogger("main.day_trading")


class Helper:
    def __init__(self, user, account_ids_dict, settings_dict):
        self.settings_trade_dict = settings_dict["trade_dict"]

        self.end_of_day_bool = False
        self.account_ids_dict = account_ids_dict

        self.ava = Context(user, account_ids_dict, skip_lists=True)
        self.strategies_dict = Strategy_DT.load("DT")
        self.instruments_obj = Instrument(self.settings_trade_dict["multiplier"])

        self.overwrite_last_line = {"bool": True, "message_list": []}

        self._update_budget()

    def _check_last_candle_buy(self, strategy_obj, row, strategies_dict, inst_type):
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

            if cs_signal == ta_signal == inst_type:
                log.warning(
                    f">>> signal - BUY: {inst_type}-{ta_indicator}-{cs_pattern} at {row.name}"
                )
                return True

        return False

    def _update_budget(self):
        own_capital = self.ava.get_portfolio()["total_own_capital"]
        floating_budget = (own_capital // 1000 - 1) * 1000

        self.settings_trade_dict["budget"] = max(
            floating_budget, self.settings_trade_dict["budget"]
        )

    def get_signal(self, strategies_dict, inst_type):
        # This needs to change to use avanza data (once I have enough volume data cached) -> deadline 2022-10-02
        history_obj = History(
            self.instruments_obj.ids_dict["MONITORING"]["YAHOO"],
            "2d",
            "1m",
            cache="skip",
        )

        strategy_obj = Strategy_DT(
            history_obj.history_df,
            order_price_limits_dict=self.settings_trade_dict["limits_dict"],
        )

        strategies_dict = (
            strategies_dict if strategies_dict else strategy_obj.load("DT")
        )

        last_full_candle_index = -2

        if (datetime.now() - strategy_obj.history_df.iloc[last_full_candle_index].name.replace(tzinfo=None)).seconds > 130:  # type: ignore
            return

        last_candle_signal_buy_bool = self._check_last_candle_buy(
            strategy_obj,
            strategy_obj.history_df.iloc[last_full_candle_index],
            strategies_dict[inst_type],
            inst_type,
        )

        return last_candle_signal_buy_bool

    def check_instrument_status(self, inst_type):
        inst_id = str(self.instruments_obj.ids_dict["TRADING"][inst_type])

        inst_status_dict = {
            "has_position_bool": False,
            "active_order_dict": dict(),
        }

        # Check if instrument has a position
        certificate_info_dict = self.ava.get_certificate_info(
            self.instruments_obj.ids_dict["TRADING"][inst_type]
        )

        for position_dict in certificate_info_dict["positions"]:
            if position_dict.get("averageAcquiredPrice") is None:
                continue

            inst_status_dict.update(
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
                    "trailing_stop_loss_price": round(
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
            if (order_dict["orderbook"]["id"] != inst_id) or (
                order_dict["rawStatus"] != "ACTIVE"
            ):
                continue

            inst_status_dict["active_order_dict"] = order_dict

            if order_dict["type"] == "BUY":
                inst_status_dict.update(
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

        return inst_status_dict

    def place_order(self, signal, inst_type, inst_status_dict):
        if (signal == "buy" and inst_status_dict["has_position_bool"]) or (
            signal == "sell" and not inst_status_dict["has_position_bool"]
        ):
            return

        self.overwrite_last_line["bool"] = False

        certificate_info_dict = self.ava.get_certificate_info(
            self.instruments_obj.ids_dict["TRADING"][inst_type]
        )

        order_data_dict = {
            "name": inst_type,
            "signal": signal,
            "account_id": list(self.account_ids_dict.values())[0],
            "order_book_id": self.instruments_obj.ids_dict["TRADING"][inst_type],
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
                if certificate_info_dict[signal] < inst_status_dict["stop_loss_price"]
                else inst_status_dict["take_profit_price"]
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

        log.info(
            f'{order_data_dict["signal"].upper()}: {order_data_dict["name"]} - {order_data_dict["price"]}'
        )

    def update_order(self, signal, inst_type, inst_status_dict, price):
        if price is None:
            return

        self.overwrite_last_line["bool"] = False

        inst_type = inst_status_dict["active_order_dict"]["orderbook"]["name"].split(
            " "
        )[0]

        log.info(
            f'{signal.upper()} (UPD): {inst_type} - {inst_status_dict["active_order_dict"]["price"]} -> {price}'
        )

        self.ava.update_order(inst_status_dict["active_order_dict"], price)

    def combine_stdout_line(self, inst_type, status_obj):
        inst_status_dict = status_obj.get_instrument(inst_type)

        if inst_status_dict["has_position_bool"]:
            self.overwrite_last_line["message_list"].append(
                f'{inst_type} - {inst_status_dict["stop_loss_price"]} < {inst_status_dict["current_price"]} < {inst_status_dict["take_profit_price"]}'
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


class Day_Trading:
    def __init__(self, user, account_ids_dict, settings_dict):
        self.settings_trade_dict = settings_dict["trade_dict"]

        self.helper_obj = Helper(user, account_ids_dict, settings_dict)
        self.balance_dict = {"before": 0, "after": 0}
        self.status_obj = Status(self.settings_trade_dict)

        while True:
            try:
                self.run_analysis(settings_dict["log_to_telegram"])

                break

            except ReadTimeout:
                self.helper_obj.ava.ctx = self.helper_obj.ava.get_ctx(user)

    def check_instrument_for_buy_action(self, strategies_dict, inst_type):
        main_inst_type = inst_type

        self.status_obj.update_instrument(
            main_inst_type,
            self.helper_obj.check_instrument_status(main_inst_type),
        )

        main_inst_status_dict = self.status_obj.get_instrument(main_inst_type)
        main_inst_buy_price = self.helper_obj.ava.get_certificate_info(
            self.helper_obj.instruments_obj.ids_dict["TRADING"][main_inst_type]
        )["buy"]
        main_inst_buy_signal_bool = self.helper_obj.get_signal(
            strategies_dict, main_inst_type
        )

        other_inst_type = "BEAR" if main_inst_type == "BULL" else "BULL"
        other_inst_status_dict = self.status_obj.get_instrument(other_inst_type)
        other_inst_sell_price = (
            None
            if not all(
                [
                    main_inst_buy_signal_bool,
                    other_inst_status_dict.get("has_position_bool", False),
                ]
            )
            else self.helper_obj.ava.get_certificate_info(
                self.helper_obj.instruments_obj.ids_dict["TRADING"][other_inst_type]
            ).get("sell")
        )

        if all(
            [
                main_inst_buy_signal_bool,
                main_inst_status_dict["has_position_bool"],
            ]
        ):
            self.status_obj.raise_instrument_trading_limits(
                main_inst_type, main_inst_buy_price
            )

        elif all(
            [
                main_inst_buy_signal_bool,
                not main_inst_status_dict["has_position_bool"],
                not main_inst_status_dict["active_order_dict"],
            ]
        ):
            self.helper_obj.update_order(
                "sell",
                other_inst_type,
                other_inst_status_dict,
                other_inst_sell_price,
            )
            time.sleep(1)

            self.helper_obj.place_order("buy", main_inst_type, main_inst_status_dict)
            time.sleep(2)

        elif all(
            [
                not main_inst_status_dict["has_position_bool"],
                main_inst_status_dict["active_order_dict"],
            ]
        ):
            self.helper_obj.update_order(
                "buy",
                main_inst_type,
                main_inst_status_dict,
                main_inst_buy_price,
            )
            time.sleep(2)

    def check_instrument_for_sell_action(self, inst_type, enforce_sell_bool=False):
        self.status_obj.update_instrument(
            inst_type, self.helper_obj.check_instrument_status(inst_type)
        )

        inst_status_dict = self.status_obj.get_instrument(inst_type)

        if not inst_status_dict["has_position_bool"]:
            return

        # Create sell orders (take_profit)
        if not inst_status_dict["active_order_dict"]:
            self.helper_obj.place_order("sell", inst_type, inst_status_dict)

        # Update sell order (if hit stop_loss / enforced / trailing_stop_loss initiated, so take_profit_price has changed)
        else:
            sell_price = None
            current_sell_price = self.helper_obj.ava.get_certificate_info(
                self.helper_obj.instruments_obj.ids_dict["TRADING"][inst_type]
            )["sell"]

            if (sell_price < inst_status_dict["stop_loss_price"]) or enforce_sell_bool:
                sell_price = current_sell_price

            elif (
                inst_status_dict["active_order_dict"]["price"]
                != inst_status_dict["take_profit_price"]
            ):
                sell_price = inst_status_dict["take_profit_price"]

            self.helper_obj.update_order(
                "sell",
                inst_type,
                inst_status_dict,
                sell_price,
            )

    # MAIN method
    def run_analysis(self, log_to_telegram):
        self.balance_dict["before"] = sum(
            self.helper_obj.ava.get_portfolio()["buying_power"].values()
        )

        log.info(
            f'> Running trading for account(s): {" & ".join(self.helper_obj.account_ids_dict)} [{self.balance_dict["before"]}]'
        )

        strategies_dict = dict()
        while True:
            self.status_obj.update_day_time()
            self.helper_obj.overwrite_last_line["message_list"] = []

            if self.status_obj.day_time == "morning":
                continue

            elif self.status_obj.day_time == "night":
                break

            # Walk through instruments
            for inst_type in ["BULL", "BEAR"]:

                if self.status_obj.day_time != "evening":
                    self.check_instrument_for_buy_action(strategies_dict, inst_type)

                self.check_instrument_for_sell_action(inst_type)

                self.helper_obj.combine_stdout_line(inst_type, self.status_obj)

            self.helper_obj.update_last_stdout_line()

            time.sleep(30)

        self.balance_dict["after"] = sum(
            self.helper_obj.ava.get_portfolio()["buying_power"].values()
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


def run():
    settings_json = Settings().load()

    for user, settings_per_account_dict in settings_json.items():
        for settings_dict in settings_per_account_dict.values():
            if not settings_dict.get("run_day_trading", False):
                continue

            try:
                Day_Trading(user, settings_dict["accounts"], settings_dict)

            except Exception as e:
                log.error(f">>> {e}: {traceback.format_exc()}")

                TeleLog(crash_report=f"DT: script has crashed: {e}")

            return
