"""
This module contains all candlesticks related functions
"""


import os
import json
import logging
import warnings
import pandas as pd

from copy import copy
from typing import Tuple, Optional, Literal


warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None  # type: ignore
pd.set_option("display.max_rows", 0)
pd.set_option("display.expand_frame_repr", False)

log = logging.getLogger("main.utils.strategy_dt")

SIGNAL = Literal["BUY", "SELL"]
ORDER_TYPE = Literal["BULL", "BEAR"]


class Strategy_DT:
    def __init__(self, data: pd.DataFrame, **kwargs):
        self.data = data.groupby(data.index).last()
        self.order_price_limits = {
            k: abs(round((1 - v) / 20, 5))
            for k, v in kwargs.get("order_price_limits", dict()).items()
        }

        self.get_candlestick_patterns()

        self.ta_indicators = self.get_ta_indicators()

    def get_ta_indicators(self) -> dict:
        ta_indicators = dict()

        """ Trend """
        # PSAR (Parabolic Stop and Reverse)
        self.data.ta.psar(append=True)
        ta_indicators["PSAR"] = {
            "buy": lambda x: x["Close"] > x["PSARl_0.02_0.2"],
            "sell": lambda x: x["Close"] < x["PSARs_0.02_0.2"],
            "columns": ["PSARl_0.02_0.2", "PSARs_0.02_0.2"],
        }

        # CKSP (Chande Kroll Stop)
        self.data.ta.cksp(append=True)
        ta_indicators["CKSP"] = {
            "buy": lambda x: x["CKSPl_10_3_20"] > x["CKSPs_10_3_20"],
            "sell": lambda x: x["CKSPl_10_3_20"] < x["CKSPs_10_3_20"],
            "columns": ["CKSPl_10_3_20", "CKSPs_10_3_20"],
        }

        """ Volatility """
        # BBANDS (Bollinger Bands)
        self.data.ta.bbands(length=20, std=1, append=True)
        ta_indicators["BBANDS"] = {
            "buy": lambda x: x["Close"] > x["BBU_20_1.0"],
            "sell": lambda x: x["Close"] < x["BBL_20_1.0"],
            "columns": ["BBL_20_1.0", "BBU_20_1.0"],
        }

        # ACCBANDS (Acceleration Bands)
        self.data.ta.accbands(append=True)
        ta_indicators["ACCBANDS"] = {
            "buy": lambda x: x["Close"] > x["ACCBU_20"],
            "sell": lambda x: x["Close"] < x["ACCBL_20"],
            "columns": ["ACCBU_20", "ACCBL_20"],
        }

        # KC (Keltner Channel)
        self.data.ta.kc(append=True)
        ta_indicators["KC"] = {
            "buy": lambda x: x["Close"] > x["KCUe_20_2"],
            "sell": lambda x: x["Close"] < x["KCLe_20_2"],
            "columns": ["KCLe_20_2", "KCUe_20_2"],
        }

        # RVI (Relative Volatility Index)
        self.data.ta.rvi(append=True)
        ta_indicators["RVI"] = {
            "sell": lambda x: x["RVI_14"] > 50,
            "buy": lambda x: x["RVI_14"] < 50,
            "columns": ["RVI_14"],
        }

        """ Momentum """
        # STC (Schaff Trend Cycle)
        self.data.ta.stc(append=True)
        ta_indicators["STC"] = {
            "sell": lambda x: x["STC_10_12_26_0.5"] > 25,
            "buy": lambda x: x["STC_10_12_26_0.5"] < 75,
            "columns": ["STC_10_12_26_0.5"],
        }

        # BOP (Balance Of Power)
        self.data.ta.bop(append=True)
        ta_indicators["BOP"] = {
            "sell": lambda x: x["BOP"] > 0.3,
            "buy": lambda x: x["BOP"] < -0.25,
            "columns": ["BOP"],
        }

        # CCI (Commodity Channel Index)
        self.data.ta.cci(length=20, append=True, offset=1)
        self.data["CCI_20_0.015_lag"] = self.data["CCI_20_0.015"]
        self.data.ta.cci(length=20, append=True)
        ta_indicators["CCI"] = {
            "sell": lambda x: x["CCI_20_0.015"] > 100
            and x["CCI_20_0.015"] < x["CCI_20_0.015_lag"],
            "buy": lambda x: x["CCI_20_0.015"] < -100
            and x["CCI_20_0.015"] > x["CCI_20_0.015_lag"],
            "columns": ["CCI_20_0.015", "CCI_20_0.015_lag"],
        }

        # RSI (Relative Strength Index)
        self.data.ta.rsi(length=14, append=True)
        ta_indicators["RSI"] = {
            "sell": lambda x: x["RSI_14"] < 50,
            "buy": lambda x: x["RSI_14"] > 50,
            "columns": ["RSI_14"],
        }

        # MACD (Moving Average Convergence Divergence)
        self.data.ta.macd(fast=8, slow=21, signal=5, append=True)
        ta_indicators["MACD"] = {
            "buy": lambda x: x["MACD_8_21_5"] > x["MACDs_8_21_5"],
            "sell": lambda x: x["MACD_8_21_5"] < x["MACDs_8_21_5"],
            "columns": ["MACD_8_21_5", "MACDs_8_21_5"],
        }

        # STOCH (Stochastic Oscillator)
        self.data.ta.stoch(k=5, d=3, append=True)
        ta_indicators["STOCH"] = {
            "buy": lambda x: x["STOCHd_5_3_3"] > 20 and x["STOCHk_5_3_3"] > 20,
            "sell": lambda x: x["STOCHd_5_3_3"] < 80 and x["STOCHk_5_3_3"] < 80,
            "columns": ["STOCHd_5_3_3", "STOCHk_5_3_3"],
        }

        # UO (Ultimate Oscillator)
        self.data.ta.uo(append=True)
        ta_indicators["UO"] = {
            "buy": lambda x: x["UO_7_14_28"] < 30,
            "sell": lambda x: x["UO_7_14_28"] > 70,
            "columns": ["UO_7_14_28"],
        }

        return ta_indicators

    def get_candlestick_patterns(self) -> None:
        self.data = pd.merge(
            left=self.data,
            right=self.data.ta.cdl_pattern(name="all"),
            left_index=True,
            right_index=True,
        )

        self.data.drop(columns=["CDL_LADDERBOTTOM"], inplace=True)

    # Strategies testing
    def get_successful_strategies(self, success_limit: int) -> dict:
        def _buy_order(
            order: dict, last_candle_signal: Optional[SIGNAL]
        ) -> Optional[ORDER_TYPE]:
            order_type = None

            if last_candle_signal == "BUY" and order["BULL"]["status"] == "SELL":
                order_type = "BULL"

            elif last_candle_signal == "SELL" and order["BEAR"]["status"] == "SELL":
                order_type = "BEAR"

            if order_type is not None:
                order[order_type]["price_buy"] = ((row["High"] + row["Low"]) / 2) * (
                    1.00015 if order_type == "BULL" else 0.99985
                )
                order[order_type]["status"] = "BUY"
                order[order_type]["buy_time"] = row.name
                order[order_type]["status"] = "BUY"
                order[order_type]["time_buy"] = index

            return order_type

        def _sell_order(
            order: dict, stats_counter: dict, orders_history: list[dict]
        ) -> None:
            for order_type in order.keys():
                if order[order_type]["status"] == "BUY":
                    order[order_type]["price_sell"] = (row["High"] + row["Low"]) / 2
                    order[order_type]["time_sell"] = index

                    verdict = None
                    if order_type == "BULL":
                        stop_loss = order[order_type]["price_buy"] * (
                            1 - self.order_price_limits["stop_loss"]
                        )
                        take_profit = order[order_type]["price_buy"] * (
                            1 + self.order_price_limits["take_profit"]
                        )

                        if order[order_type]["price_sell"] <= stop_loss:
                            verdict = "bad"

                        elif row["High"] >= take_profit:
                            verdict = "good"

                    elif order_type == "BEAR":
                        take_profit = order[order_type]["price_buy"] * (
                            1 - self.order_price_limits["take_profit"]
                        )
                        stop_loss = order[order_type]["price_buy"] * (
                            1 + self.order_price_limits["stop_loss"]
                        )

                        if row["Low"] <= take_profit:
                            verdict = "good"

                        elif order[order_type]["price_sell"] >= stop_loss:
                            verdict = "bad"

                    if verdict is None:
                        continue

                    order[order_type].update(
                        {"order_type": order_type, "status": "SELL", "verdict": verdict}
                    )

                    stats_counter[verdict][order_type] += 1
                    orders_history.append(copy(order[order_type]))

        def _get_signal(value: int) -> Optional[SIGNAL]:
            signal = None

            if value > 0 and ta_indicator_lambda["buy"](row):
                signal = "BUY"

            elif value < 0 and ta_indicator_lambda["sell"](row):
                signal = "SELL"

            return signal

        def _filter_out_strategies(
            strategies: dict, stats_counter: dict, ta_indicator: str, column: str
        ) -> None:
            for order_type in strategies:

                number_transactions = (
                    stats_counter["good"][order_type] + stats_counter["bad"][order_type]
                )

                efficiency_percent = (
                    0
                    if stats_counter["good"][order_type]
                    - stats_counter["bad"][order_type]
                    <= 1
                    else round(
                        (stats_counter["good"][order_type] / number_transactions) * 100
                    )
                )

                if efficiency_percent >= success_limit:
                    strategies[order_type].setdefault(ta_indicator, list())
                    strategies[order_type][ta_indicator].append(column)

                    log.info(
                        f"{ta_indicator} + {column} - {order_type}: {efficiency_percent}% ({stats_counter['good'][order_type]} Good / {stats_counter['bad'][order_type]} Bad)"
                    )

                else:
                    log.debug(
                        f"{ta_indicator} + {column} - {order_type}: {efficiency_percent}% ({stats_counter['good'][order_type]} Good / {stats_counter['bad'][order_type]} Bad)"
                    )

        strategies = {"BULL": dict(), "BEAR": dict()}

        for ta_indicator in self.ta_indicators:
            ta_indicator_lambda = self.ta_indicators[ta_indicator]

            for column in self.data.columns:
                orders_history = list()

                stats_counter = {
                    "good": {"BULL": 0, "BEAR": 0, "percent": 0.0},
                    "bad": {"BULL": 0, "BEAR": 0, "percent": 0.0},
                }

                order = {
                    i: {
                        "status": "SELL",
                        "price_buy": None,
                        "price_sell": None,
                        "time_buy": None,
                        "time_sell": None,
                        "verdict": None,
                    }
                    for i in ["BULL", "BEAR"]
                }

                self.data["signal"] = None

                if not column.startswith("CDL") or (self.data[column] == 0).all():
                    continue

                last_candle_signal = None

                for index, row in self.data[
                    ["High", "Low", "Open", "Close", column]
                    + self.ta_indicators[ta_indicator]["columns"]
                ].iterrows():

                    order_type = _buy_order(order, last_candle_signal)
                    if order_type is not None:
                        continue

                    _sell_order(order, stats_counter, orders_history)
                    last_candle_signal = _get_signal(row[column])

                _filter_out_strategies(
                    strategies,
                    stats_counter,
                    ta_indicator,
                    column,
                )

        return strategies

    def backtest_strategies(self, strategies: dict) -> None:
        def _buy_order(
            order: dict, last_candle_signal: Optional[SIGNAL]
        ) -> Optional[ORDER_TYPE]:
            order_type = None

            if last_candle_signal == "BUY" and order["BULL"]["status"] == "SELL":
                order_type = "BULL"

            elif last_candle_signal == "SELL" and order["BEAR"]["status"] == "SELL":
                order_type = "BEAR"

            if order_type is not None:
                order[order_type]["price_buy"] = ((row["High"] + row["Low"]) / 2) * (
                    1.00015 if order_type == "BULL" else 0.99985
                )
                order[order_type]["status"] = "BUY"
                order[order_type]["time_buy"] = index

            return order_type

        def _sell_order(
            order: dict, stats_counter: dict, orders_history: list[dict]
        ) -> None:
            for order_type in order.keys():
                if order[order_type]["status"] == "BUY":
                    order[order_type]["price_sell"] = (row["High"] + row["Low"]) / 2
                    order[order_type]["time_sell"] = index

                    verdict = None
                    if order_type == "BULL":
                        stop_loss = order[order_type]["price_buy"] * (
                            1 - self.order_price_limits["stop_loss"]
                        )
                        take_profit = order[order_type]["price_buy"] * (
                            1 + self.order_price_limits["take_profit"]
                        )

                        if order[order_type]["price_sell"] <= stop_loss:
                            verdict = "bad"

                        elif row["High"] >= take_profit:
                            verdict = "good"

                    elif order_type == "BEAR":
                        take_profit = order[order_type]["price_buy"] * (
                            1 - self.order_price_limits["take_profit"]
                        )
                        stop_loss = order[order_type]["price_buy"] * (
                            1 + self.order_price_limits["stop_loss"]
                        )

                        if row["Low"] <= take_profit:
                            verdict = "good"

                        elif order[order_type]["price_sell"] >= stop_loss:
                            verdict = "bad"

                    if verdict is None:
                        continue

                    order[order_type].update(
                        {"order_type": order_type, "status": "SELL", "verdict": verdict}
                    )

                    stats_counter[order_type][verdict] += 1
                    orders_history.append(copy(order[order_type]))

        def _get_ta_signal(row: pd.Series, ta_indicator: str) -> Optional[SIGNAL]:

            ta_signal = None

            if self.ta_indicators[ta_indicator]["buy"](row):
                ta_signal = "BUY"

            elif self.ta_indicators[ta_indicator]["sell"](row):
                ta_signal = "SELL"

            return ta_signal

        def _get_cs_signal(
            row: pd.Series, patterns: list[str]
        ) -> Tuple[Optional[SIGNAL], Optional[str]]:
            cs_signal, cs_pattern = None, None

            for pattern in patterns:
                if row[pattern] > 0:
                    cs_signal = "BUY"
                elif row[pattern] < 0:
                    cs_signal = "SELL"

                if cs_signal is not None:
                    cs_pattern = pattern
                    break

            return cs_signal, cs_pattern

        def _update_strategies(
            stats_counter: dict, orders_history: list[dict], strategies: dict
        ) -> dict:
            for order_type in stats_counter:
                log.info(
                    f"{order_type}: {stats_counter[order_type]['good']} Good / {stats_counter[order_type]['bad']} Bad"
                )

            orders_stats = dict()
            for order in orders_history:
                key = f'{order["order_type"]}-{order["ta_indicator"]}-{order["cs_pattern"]}'
                orders_stats.setdefault(key, dict()).setdefault(order["verdict"], 0)
                orders_stats[key][order["verdict"]] += 1

            for path, stats in orders_stats.items():
                log.info(f"{path}: {stats}")
                if "good" not in stats:
                    path = path.split("-")
                    strategies[path[0]][path[1]] = list(
                        set(strategies[path[0]][path[1]]) - {path[2]}
                    )

            return strategies

        orders_history = list()

        stats_counter = {
            "BULL": {"good": 0, "bad": 0, "percent": 0.0},
            "BEAR": {"good": 0, "bad": 0, "percent": 0.0},
        }

        order = {
            i: {
                "status": "SELL",
                "price_buy": None,
                "price_sell": None,
                "time_buy": None,
                "time_sell": None,
                "verdict": None,
                "cs_pattern": None,
                "ta_indicator": None,
            }
            for i in ["BULL", "BEAR"]
        }

        self.data["signal"] = None

        for i, (index, row) in enumerate(self.data.iterrows()):
            order_type = _buy_order(order, self.data.iloc[i - 1]["signal"])
            if order_type is not None:
                continue

            _sell_order(order, stats_counter, orders_history)
            if order["BULL" if order_type == "BUY" else "BEAR"]["status"] == "BUY":
                continue

            for ta_indicator in self.ta_indicators:
                ta_signal = _get_ta_signal(row, ta_indicator)
                if ta_signal is None:
                    continue

                cs_signal, cs_pattern = _get_cs_signal(
                    row,
                    strategies["BULL" if ta_signal == "BUY" else "BEAR"].get(
                        ta_indicator, list()
                    ),
                )
                if cs_signal is None:
                    continue

                order_type = "BULL" if cs_signal == "BUY" else "BEAR"
                if cs_signal == ta_signal:
                    self.data.at[index, "signal"] = (
                        self.data.at[index, "signal"]
                        if self.data.at[index, "signal"] is not None
                        else cs_signal
                    )
                    order[order_type]["cs_pattern"] = cs_pattern
                    order[order_type]["ta_indicator"] = ta_indicator

                    log.warning(
                        f"{str(index)[5:16]} / {round(row['Close'], 2)} / {order_type}-{ta_indicator}-{cs_pattern}"
                    )

        _update_strategies(stats_counter, orders_history, strategies)

    # File management
    @staticmethod
    def load(filename_suffix: str) -> dict:
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        try:
            with open(
                f"{current_dir}/data/strategies_{filename_suffix}.json", "r"
            ) as f:
                strategies = json.load(f)
        except:
            strategies = dict()

        return strategies

    @staticmethod
    def dump(filename_suffix: str, strategies: dict) -> None:
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(f"{current_dir}/data/strategies_{filename_suffix}.json", "w") as f:
            json.dump(strategies, f, indent=4)
