"""
This module contains all candlesticks related functions
"""


import os
import json
import talib
import logging
import warnings
import pandas as pd
import yfinance as yf
import pandas_ta as ta
from datetime import datetime, timedelta

from copy import copy


warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None
pd.set_option("display.max_rows", 0)
pd.set_option("display.expand_frame_repr", False)

log = logging.getLogger("main.strategy_cs")


class Strategy_CS:
    def __init__(self, history_df, **kwargs):
        self.history_df = history_df[~history_df.index.duplicated()]

        self.order_price_limits = {
            k: abs(round((1 - v) / 20, 5))
            for k, v in kwargs.get("order_price_limits_dict", {}).items()
        }

        self.get_candlestick_patterns()

        self.ta_indicators_dict = self.get_ta_indicators()

    def get_ta_indicators(self):
        ta_indicators_dict = {}

        """ Trend """
        # PSAR (Parabolic Stop and Reverse)
        self.history_df.ta.psar(append=True)
        ta_indicators_dict["PSAR"] = {
            "buy": lambda x: x["Close"] > x["PSARl_0.02_0.2"],
            "sell": lambda x: x["Close"] < x["PSARs_0.02_0.2"],
        }

        # CKSP (Chande Kroll Stop)
        self.history_df.ta.cksp(append=True)
        ta_indicators_dict["CKSP"] = {
            "buy": lambda x: x["CKSPl_10_3_20"] > x["CKSPs_10_3_20"],
            "sell": lambda x: x["CKSPl_10_3_20"] < x["CKSPs_10_3_20"],
        }

        """ Volatility """
        # BBANDS (Bollinger Bands)
        self.history_df.ta.bbands(length=20, std=1, append=True)
        ta_indicators_dict["BBANDS"] = {
            "buy": lambda x: x["Close"] > x["BBU_20_1.0"],
            "sell": lambda x: x["Close"] < x["BBL_20_1.0"],
        }

        """ Candle """
        # HA (Heikin-Ashi)
        self.history_df.ta.ha(append=True)
        ta_indicators_dict["HA"] = {
            "buy": lambda x: (x["HA_open"] < x["HA_close"])
            and (x["HA_low"] == x["HA_open"]),
            "sell": lambda x: (x["HA_open"] > x["HA_close"])
            and (x["HA_high"] == x["HA_open"]),
        }

        """ Momentum """
        # STC (Schaff Trend Cycle)
        self.history_df.ta.stc(append=True)
        ta_indicators_dict["STC"] = {
            "sell": lambda x: x["STC_10_12_26_0.5"] > 25,
            "buy": lambda x: x["STC_10_12_26_0.5"] < 75,
        }

        # CCI (Commodity Channel Index)
        self.history_df.ta.cci(length=20, append=True, offset=1)
        self.history_df["CCI_20_0.015_lag"] = self.history_df["CCI_20_0.015"]
        self.history_df.ta.cci(length=20, append=True)
        ta_indicators_dict["CCI"] = {
            "sell": lambda x: x["CCI_20_0.015"] > 100
            and x["CCI_20_0.015"] < x["CCI_20_0.015_lag"],
            "buy": lambda x: x["CCI_20_0.015"] < -100
            and x["CCI_20_0.015"] > x["CCI_20_0.015_lag"],
        }

        # RSI (Relative Strength Index)
        self.history_df.ta.rsi(length=14, append=True)
        ta_indicators_dict["RSI"] = {
            "sell": lambda x: x["RSI_14"] > 70,
            "buy": lambda x: x["RSI_14"] < 30,
        }

        # RVGI (Relative Vigor Index)
        self.history_df.ta.rvgi(append=True)
        ta_indicators_dict["RVGI"] = {
            "buy": lambda x: x["RVGI_14_4"] > x["RVGIs_14_4"],
            "sell": lambda x: x["RVGI_14_4"] < x["RVGIs_14_4"],
        }

        # MACD (Moving Average Convergence Divergence)
        self.history_df.ta.macd(fast=8, slow=21, signal=5, append=True)
        ta_indicators_dict["MACD"] = {
            "buy": lambda x: x["MACD_8_21_5"] > x["MACDs_8_21_5"],
            "sell": lambda x: x["MACD_8_21_5"] < x["MACDs_8_21_5"],
        }

        # STOCH (Stochastic Oscillator)
        self.history_df.ta.stoch(k=5, d=3, append=True)
        ta_indicators_dict["STOCH"] = {
            "buy": lambda x: x["STOCHd_5_3_3"] > 20 and x["STOCHk_5_3_3"] > 20,
            "sell": lambda x: x["STOCHd_5_3_3"] < 80 and x["STOCHk_5_3_3"] < 80,
        }

        # UO (Ultimate Oscillator)
        self.history_df.ta.uo(append=True)
        ta_indicators_dict["UO"] = {
            "buy": lambda x: x["UO_7_14_28"] < 30,
            "sell": lambda x: x["UO_7_14_28"] > 70,
        }

        return ta_indicators_dict

    def get_candlestick_patterns(self):
        self.history_df = pd.merge(
            left=self.history_df,
            right=self.history_df.ta.cdl_pattern(name="all"),
            left_index=True,
            right_index=True,
        )

    # Strategies testing
    def get_successful_strategies(self, success_limit):
        def _buy_order(order_dict, last_candle_signal):
            order_type = None
            if last_candle_signal == "BUY" and order_dict["BULL"]["status"] == "SELL":
                order_type = "BULL"
            elif (
                last_candle_signal == "SELL" and order_dict["BEAR"]["status"] == "SELL"
            ):
                order_type = "BEAR"

            if order_type is not None:
                order_dict[order_type]["buy_price"] = (row["High"] + row["Low"]) / 2
                order_dict[order_type]["status"] = "BUY"
                order_dict[order_type]["time_buy"] = index

            return order_type

        def _sell_order(order_dict, stats_counter_dict, orders_history_list):
            for order_type in order_dict.keys():
                if order_dict[order_type]["status"] == "BUY":
                    order_dict[order_type]["sell_price"] = (
                        row["High"] + row["Low"]
                    ) / 2
                    order_dict[order_type]["time_sell"] = index

                    verdict = None
                    if order_type == "BULL":
                        stop_loss = order_dict[order_type]["buy_price"] * (
                            1 - self.order_price_limits["SL"]
                        )
                        take_profit = order_dict[order_type]["buy_price"] * (
                            1 + self.order_price_limits["TP"]
                        )

                        if row["Low"] <= stop_loss:
                            verdict = "bad"

                        elif row["High"] >= take_profit:
                            verdict = "good"

                    elif order_type == "BEAR":
                        take_profit = order_dict[order_type]["buy_price"] * (
                            1 - self.order_price_limits["TP"]
                        )
                        stop_loss = order_dict[order_type]["buy_price"] * (
                            1 + self.order_price_limits["SL"]
                        )

                        if row["Low"] <= take_profit:
                            verdict = "good"

                        elif row["High"] >= stop_loss:
                            verdict = "bad"

                    if verdict is None:
                        continue

                    order_dict[order_type]["order_type"] = order_type
                    order_dict[order_type]["status"] = "SELL"
                    stats_counter_dict[verdict][order_type] += 1
                    order_dict[order_type]["verdict"] = verdict
                    orders_history_list.append(copy(order_dict[order_type]))

        def _get_signal(value, index):
            signal = None
            if value > 0 and ta_indicator_lambda["buy"](row):
                signal = "BUY"

            elif value < 0 and ta_indicator_lambda["sell"](row):
                signal = "SELL"

            self.history_df.at[index, "signal"] = signal

        def _filter_out_strategies(
            strategies_dict, stats_counter_dict, ta_indicator, column
        ):
            for order_type in strategies_dict:

                number_transactions = (
                    stats_counter_dict["good"][order_type]
                    + stats_counter_dict["bad"][order_type]
                )

                efficiency_percent = (
                    0
                    if number_transactions <= 1
                    else round(
                        (stats_counter_dict["good"][order_type] / number_transactions)
                        * 100
                    )
                )

                if efficiency_percent > success_limit:
                    strategies_dict[order_type].setdefault(ta_indicator, list())
                    strategies_dict[order_type][ta_indicator].append(column)

                    log.info(
                        f"{ta_indicator} + {column} - {order_type}: {efficiency_percent}% ({stats_counter_dict['good'][order_type]} Good / {stats_counter_dict['bad'][order_type]} Bad)"
                    )

        strategies_dict = {"BULL": dict(), "BEAR": dict()}

        for ta_indicator in self.ta_indicators_dict:
            ta_indicator_lambda = self.ta_indicators_dict[ta_indicator]

            for column in self.history_df.columns:
                orders_history_list = list()

                stats_counter_dict = {
                    "good": {"BULL": 0, "BEAR": 0, "percent": 0.0},
                    "bad": {"BULL": 0, "BEAR": 0, "percent": 0.0},
                }

                order_dict = {
                    i: {
                        "status": "SELL",
                        "buy_price": None,
                        "sell_price": None,
                        "time_buy": None,
                        "time_sell": None,
                        "verdict": None,
                    }
                    for i in ["BULL", "BEAR"]
                }

                self.history_df["signal"] = None

                if not column.startswith("CDL"):
                    continue
                
                time_start_testing = datetime.now()

                for i, (index, row) in enumerate(self.history_df.iterrows()):
                    order_type = _buy_order(
                        order_dict, self.history_df.iloc[i - 1]["signal"]
                    )
                    if order_type is not None:
                        continue

                    _sell_order(order_dict, stats_counter_dict, orders_history_list)
                    _get_signal(row[column], index)

                _filter_out_strategies(
                    strategies_dict,
                    stats_counter_dict,
                    ta_indicator,
                    column,
                )

                log.debug(f'{ta_indicator} + {column} - Time: {(datetime.now() - time_start_testing).seconds // 60} min {(datetime.now() - time_start_testing).seconds % 60} sec')

        return strategies_dict

    def backtest_strategies(self, strategies_dict):
        def _buy_order(order_dict, last_candle_signal):
            order_type = None
            if last_candle_signal == "BUY" and order_dict["BULL"]["status"] == "SELL":
                order_type = "BULL"
            elif (
                last_candle_signal == "SELL" and order_dict["BEAR"]["status"] == "SELL"
            ):
                order_type = "BEAR"

            if order_type is not None:
                order_dict[order_type]["buy_price"] = (row["High"] + row["Low"]) / 2
                order_dict[order_type]["status"] = "BUY"
                order_dict[order_type]["time_buy"] = index

            return order_type

        def _sell_order(order_dict, stats_counter_dict, orders_history_list):
            for order_type in order_dict.keys():
                if order_dict[order_type]["status"] == "BUY":
                    order_dict[order_type]["sell_price"] = (
                        row["High"] + row["Low"]
                    ) / 2
                    order_dict[order_type]["time_sell"] = index

                    verdict = None
                    if order_type == "BULL":
                        stop_loss = order_dict[order_type]["buy_price"] * (
                            1 - self.order_price_limits["SL"]
                        )
                        take_profit = order_dict[order_type]["buy_price"] * (
                            1 + self.order_price_limits["TP"]
                        )

                        if row["Low"] <= stop_loss:
                            verdict = "bad"

                        elif row["High"] >= take_profit:
                            verdict = "good"

                    elif order_type == "BEAR":
                        take_profit = order_dict[order_type]["buy_price"] * (
                            1 - self.order_price_limits["TP"]
                        )
                        stop_loss = order_dict[order_type]["buy_price"] * (
                            1 + self.order_price_limits["SL"]
                        )

                        if row["Low"] <= take_profit:
                            verdict = "good"

                        elif row["High"] >= stop_loss:
                            verdict = "bad"

                    if verdict is None:
                        continue

                    order_dict[order_type]["order_type"] = order_type
                    order_dict[order_type]["status"] = "SELL"
                    stats_counter_dict[order_type][verdict] += 1
                    order_dict[order_type]["verdict"] = verdict
                    orders_history_list.append(copy(order_dict[order_type]))

        def _get_ta_signal(row, ta_indicator):
            ta_signal = None

            if self.ta_indicators_dict[ta_indicator]["buy"](row):
                ta_signal = "BUY"

            elif self.ta_indicators_dict[ta_indicator]["sell"](row):
                ta_signal = "SELL"

            return ta_signal

        def _get_cs_signal(row, patterns_list):
            cs_signal, cs_pattern = None, None

            for pattern in patterns_list:
                if row[pattern] > 0:
                    cs_signal = "BUY"
                elif row[pattern] < 0:
                    cs_signal = "SELL"

                if cs_signal is not None:
                    cs_pattern = pattern
                    break

            return cs_signal, cs_pattern

        def _update_strategies_dict(
            stats_counter_dict, orders_history_list, strategies_dict
        ):
            for order_type in stats_counter_dict:
                log.info(
                    f"{order_type}: {stats_counter_dict[order_type]['good']} Good / {stats_counter_dict[order_type]['bad']} Bad"
                )

            orders_stats_dict = dict()
            for order_dict in orders_history_list:
                key = f'{order_dict["order_type"]}-{order_dict["ta_indicator"]}-{order_dict["cs_pattern"]}'
                orders_stats_dict.setdefault(key, dict()).setdefault(
                    order_dict["verdict"], 0
                )
                orders_stats_dict[key][order_dict["verdict"]] += 1

            for path, stats_dict in orders_stats_dict.items():
                log.info(f"{path}: {stats_dict}")
                if "good" not in stats_dict:
                    path = path.split("-")
                    strategies_dict[path[0]][path[1]] = list(
                        set(strategies_dict[path[0]][path[1]]) - {path[2]}
                    )

            return strategies_dict

        orders_history_list = list()

        stats_counter_dict = {
            "BULL": {"good": 0, "bad": 0, "percent": 0.0},
            "BEAR": {"good": 0, "bad": 0, "percent": 0.0},
        }

        order_dict = {
            i: {
                "status": "SELL",
                "buy_price": None,
                "sell_price": None,
                "time_buy": None,
                "time_sell": None,
                "verdict": None,
                "cs_pattern": None,
                "ta_indicator": None,
            }
            for i in ["BULL", "BEAR"]
        }

        self.history_df["signal"] = None

        for i, (index, row) in enumerate(self.history_df.iterrows()):
            order_type = _buy_order(order_dict, self.history_df.iloc[i - 1]["signal"])
            if order_type is not None:
                continue

            _sell_order(order_dict, stats_counter_dict, orders_history_list)
            if order_dict["BULL" if order_type == "BUY" else "BEAR"]["status"] == "BUY":
                continue

            for ta_indicator in self.ta_indicators_dict:
                ta_signal = _get_ta_signal(row, ta_indicator)
                if ta_signal is None:
                    continue

                cs_signal, cs_pattern = _get_cs_signal(
                    row,
                    strategies_dict["BULL" if ta_signal == "BUY" else "BEAR"].get(
                        ta_indicator, list()
                    ),
                )
                if cs_signal is None:
                    continue

                order_type = "BULL" if cs_signal == "BUY" else "BEAR"
                if cs_signal == ta_signal:
                    self.history_df.at[index, "signal"] = (
                        self.history_df.at[index, "signal"]
                        if self.history_df.at[index, "signal"] is not None
                        else cs_signal
                    )
                    order_dict[order_type]["cs_pattern"] = cs_pattern
                    order_dict[order_type]["ta_indicator"] = ta_indicator

                    log.warning(
                        f"{str(index)[5:16]} / {round(row['Close'], 2)} / {order_type}-{ta_indicator}-{cs_pattern}"
                    )

        strategies_dict = _update_strategies_dict(
            stats_counter_dict, orders_history_list, strategies_dict
        )

        return strategies_dict

    # File management
    @staticmethod
    def load(filename_suffix):
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            with open(
                f"{current_dir}/data/strategies_{filename_suffix}.json", "r"
            ) as f:
                strategies_json = json.load(f)
        except:
            strategies_json = dict()

        return strategies_json

    @staticmethod
    def dump(filename_suffix, strategies_json):
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(f"{current_dir}/data/strategies_{filename_suffix}.json", "w") as f:
            json.dump(strategies_json, f, indent=4)
