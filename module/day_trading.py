import imp
import time
import logging
import traceback
import yfinance as yf
from datetime import datetime, timedelta

from requests import ReadTimeout

from .utils import Plot
from .utils import Context
from .utils import TeleLog
from .utils import Settings
from .utils import Instrument
from .utils import Strategy_CS


log = logging.getLogger("main.day_trading_cs")


INSTRUMENT_SETTINGS_DICT = {"multiplier": 20, "budget": 2000}
ORDER_PRICE_LIMITS = {"SL": 0.98, "TP": 1.025}
RECALIBRATE_DICT = {
    "success_limit": 65,
    "update_bool": True,
    "plot_bool": False,
}


class Calibration:
    def __init__(self, instrument_id):
        self.instrument_id = instrument_id
        self.chart_directions_list = ["original", "inverted"]

        log.info(
            f"{'Updating' if RECALIBRATE_DICT['update_bool'] else 'Verifying'} strategies_dict"
        )

        self.update_strategies()
        history_df = self.test_strategies()
        self.plot_strategies(history_df)

    def update_strategies(self):
        if not RECALIBRATE_DICT["update_bool"]:
            return

        log.info(
            f"Updating strategies_dict: "
            + str(ORDER_PRICE_LIMITS)
            + f' success_limit: {RECALIBRATE_DICT["success_limit"]}'
        )

        strategy_obj = Strategy_CS(
            self.instrument_id,
            period="30d",
            interval="1m",
            order_price_limits_dict=ORDER_PRICE_LIMITS,
        )

        strategies_dict = {}

        strategy_obj.history_df = strategy_obj.history_df.loc[
            : (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        ]

        strategies_dict = strategy_obj.get_successful_strategies(
            RECALIBRATE_DICT["success_limit"]
        )

        strategy_obj.dump("DT_CS", strategies_dict)

    def test_strategies(self):
        log.info(f"Testing strategies")

        strategy_obj = Strategy_CS(
            self.instrument_id,
            period="2d",
            interval="1m",
            order_price_limits_dict=ORDER_PRICE_LIMITS,
        )

        strategies_dict = strategy_obj.load("DT_CS")

        strategy_obj.backtest_strategies(strategies_dict)

        return strategy_obj.history_df

    def plot_strategies(self, history_df):
        if not RECALIBRATE_DICT["plot_bool"]:
            return

        history_df["buy_signal"] = history_df.apply(
            lambda x: x["High"] if x["signal"] == "BUY" else None, axis=1
        )
        history_df["sell_signal"] = history_df.apply(
            lambda x: x["Low"] if x["signal"] == "SELL" else None, axis=1
        )

        plot_obj = Plot(
            data_df=history_df,
            title=f"Signals",
        )
        plot_obj.add_orders_to_main_plot()
        plot_obj.show_single_ticker()


class Trading:
    def __init__(self, user, account_ids_dict):
        self.account_ids_dict = account_ids_dict
        self.end_of_day_bool = False
        self.ava = Context(user, account_ids_dict, skip_lists=True)
        self.strategies_dict = Strategy_CS.load("DT_CS")
        self.instruments_obj = Instrument(INSTRUMENT_SETTINGS_DICT["multiplier"])

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
                    f"> signal - BUY: {instrument_type}-{ta_indicator}-{cs_pattern}"
                )
                return True

        return False

    def get_signal(self, strategies_dict, instrument_type):
        strategy_obj = Strategy_CS(
            self.instruments_obj.ids_dict["MONITORING"]["YAHOO"],
            period="2d",
            interval="1m",
        )

        strategies_dict = (
            strategies_dict if strategies_dict else strategy_obj.load("DT_CS")
        )

        try:
            last_full_candle_index = -1
            last_full_candle_timestamp = strategy_obj.history_df.iloc[
                last_full_candle_index
            ].name

            if datetime.now().minute == last_full_candle_timestamp.minute:
                last_full_candle_index = -2

        except:
            log.error("Unexpected error in parsing history_df datetime")
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
                    "stop_loss_price": round(
                        position_dict["averageAcquiredPrice"]
                        * ORDER_PRICE_LIMITS["SL"],
                        2,
                    ),
                    "take_profit_price": round(
                        position_dict["averageAcquiredPrice"]
                        * ORDER_PRICE_LIMITS["TP"],
                        2,
                    ),
                    "current_price": certificate_info_dict["sell"],
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
                            order_dict["price"] * ORDER_PRICE_LIMITS["SL"], 2
                        ),
                        "take_profit_price": round(
                            order_dict["price"] * ORDER_PRICE_LIMITS["TP"], 2
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

        if signal == "buy":
            order_data_dict.update(
                {
                    "price": certificate_info_dict[signal],
                    "volume": int(
                        INSTRUMENT_SETTINGS_DICT["budget"]
                        // certificate_info_dict[signal]
                    ),
                    "budget": INSTRUMENT_SETTINGS_DICT["budget"],
                }
            )

        elif signal == "sell":
            price = (
                certificate_info_dict["sell"]
                if certificate_info_dict["sell"]
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
            f'> (UPD) {signal.upper()}: {instrument_type} - {instrument_status_dict["active_order_dict"]["price"]} -> {certificate_info_dict[signal]}'
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
    def __init__(self, user, account_ids_dict):
        instruments_obj = Instrument(INSTRUMENT_SETTINGS_DICT["multiplier"])

        Calibration(instruments_obj.ids_dict["MONITORING"]["YAHOO"])

        self.trading_obj = Trading(user, account_ids_dict)
        self.balance_dict = {"before": 0, "after": 0}

        self.trading_status_dict = {
            "stock": {"BULL": False, "BEAR": False},
            "day_time": "morning",
        }

        while True:
            try:
                if self.run_analysis() == "Done for the day":
                    break

            except ReadTimeout:
                self.trading_obj.ava.ctx = self.trading_obj.ava.get_ctx(user)

    def update_trading_day_time(self):
        current_time = datetime.now()

        if current_time.hour <= 9 and current_time.minute < 40:
            time.sleep(60)
            self.trading_status_dict["day_time"] = "morning"

        elif current_time.hour >= 17 and current_time.minute >= 30:
            self.trading_status_dict["day_time"] = "evening"

        else:
            self.trading_status_dict["day_time"] = "day"

    def check_instrument_for_buy_action(self, strategies_dict, instrument_type):
        instrument_status_dict = self.trading_obj.check_instrument_status(
            instrument_type
        )

        self.trading_status_dict["stock"][instrument_type] = instrument_status_dict[
            "has_position_bool"
        ]

        if (
            self.trading_status_dict["stock"][instrument_type]
            or self.trading_status_dict["day_time"] == "evening"
        ):
            return

        # Update buy order if there is no position, but open order exists
        if instrument_status_dict["active_order_dict"]:
            self.trading_obj.update_order(
                "buy",
                instrument_type,
                instrument_status_dict,
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

            self.trading_obj.place_order("buy", instrument_type, instrument_status_dict)
            time.sleep(2)

    def check_instrument_for_sell_action(
        self, instrument_type, enforce_sell_bool=False
    ):
        instrument_status_dict = self.trading_obj.check_instrument_status(
            instrument_type
        )

        if not instrument_status_dict["has_position_bool"]:
            return

        # Create take_profit sell orders
        if not instrument_status_dict["active_order_dict"]:
            self.trading_obj.place_order(
                "sell", instrument_type, instrument_status_dict
            )

        # Check if hit stop loss (or enforce) -> sell
        else:
            certificate_info_dict = self.trading_obj.ava.get_certificate_info(
                self.trading_obj.instruments_obj.ids_dict["TRADING"][instrument_type]
            )

            if (
                certificate_info_dict["sell"]
                < instrument_status_dict["stop_loss_price"]
            ) or enforce_sell_bool:
                self.trading_obj.update_order(
                    "sell",
                    instrument_type,
                    instrument_status_dict,
                )

    # MAIN method
    def run_analysis(self):
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

            if self.trading_status_dict["day_time"] == "morning":
                continue

            elif self.trading_status_dict["day_time"] == "evening" and not any(
                self.trading_status_dict["stock"].values()
            ):
                break

            # Walk through instruments
            for instrument_type in ["BULL", "BEAR"]:
                self.check_instrument_for_buy_action(strategies_dict, instrument_type)
                self.check_instrument_for_sell_action(instrument_type)

                self.trading_obj.combine_stdout_line(instrument_type)

            self.trading_obj.update_last_stdout_line()

            time.sleep(10)

        self.balance_dict["after"] = sum(
            self.trading_obj.ava.get_portfolio()["buying_power"].values()
        )

        log.info(f'> End of the day. [{self.balance_dict["after"]}]')

        # Dump log to Telegram
        log_obj = TeleLog(
            day_trading_stats_dict={
                "balance_before": self.balance_dict["before"],
                "balance_after": self.balance_dict["after"],
                "budget": INSTRUMENT_SETTINGS_DICT["budget"],
            }
        )
        log_obj.dump_to_telegram()

        return "Done for the day"


def run():
    settings_obj = Settings()
    settings_json = settings_obj.load()
    user = list(settings_json.keys())[0]
    account_ids_dict = settings_obj.extract_accounts(settings_json, "run_day_trading")

    try:
        Day_Trading_CS(user, account_ids_dict)

    except Exception as e:
        log.error(f">>> {e}: {traceback.format_exc()}")
