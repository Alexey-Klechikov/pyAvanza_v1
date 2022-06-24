"""
This module contains all technical indicators and strategies generation routines
"""


import os
import json
import pickle
import logging
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
import pandas_ta as ta

from copy import copy
from pprint import pprint


warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None
pd.set_option("display.expand_frame_repr", False)

log = logging.getLogger("main.strategy")


class Strategy:
    def __init__(self, ticker_yahoo, ticker_ava, ava, **kwargs):
        self.ticker_obj, history_df = self.read_ticker(
            ticker_yahoo,
            ticker_ava,
            ava,
            kwargs.get("cache", False),
            period=kwargs.get("period", "18mo"),
            interval=kwargs.get("interval", "1d"),
        )

        if "adjust_history_dict" in kwargs:
            shift = history_df.iloc[0]["Open"] - kwargs["adjust_history_dict"]["base"]
            for col in ["Open", "High", "Low", "Close"]:
                history_df[col] = history_df[col] - shift
                if kwargs["adjust_history_dict"]["inverse"]:
                    history_df[col] = (-1 * history_df[col]) + (
                        2 * kwargs["adjust_history_dict"]["base"]
                    )

        skip_points = kwargs.get("skip_points", 100)
        self.history_df, self.conditions_dict = self.prepare_conditions(
            history_df, skip_points
        )

        if "strategies_list" in kwargs and kwargs["strategies_list"] != list():
            strategies_list = self.parse_strategies_list(kwargs["strategies_list"])
        else:
            strategies_list = self.generate_strategies_list()

        strategies_dict = self.generate_strategies_dict(strategies_list)
        self.summary = self.get_signal(
            kwargs.get("ticker_name", False), strategies_dict
        )

    def read_ticker(self, ticker_yahoo, ticker_ava, ava, cache, period, interval):
        log.info(f"Reading ticker")

        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pickle_path = f"{current_dir}/cache/{ticker_yahoo}.pickle"

        directory_exists = os.path.exists("/".join(pickle_path.split("/")[:-1]))
        if not directory_exists:
            os.makedirs("/".join(pickle_path.split("/")[:-1]))

        if not cache:
            if os.path.exists(pickle_path):
                os.remove(pickle_path)

        # Check if cache exists (and is completed)
        for _ in range(2):
            try:
                if not os.path.exists(pickle_path):
                    with open(pickle_path, "wb") as pcl:
                        ticker_obj = yf.Ticker(ticker_yahoo)
                        history_df = ticker_obj.history(
                            period=period, interval=interval
                        )

                        if str(history_df.iloc[-1]["Close"]) == "nan":
                            ava.get_todays_ochl(cache[1], ticker_ava)

                        cache = (ticker_obj, history_df)
                        pickle.dump(cache, pcl)

                with open(pickle_path, "rb") as pcl:
                    cache = pickle.load(pcl)
                    break

            except EOFError:
                os.remove(pickle_path)

        return cache

    def prepare_conditions(self, history_df, skip_points):
        
        def _check_enough_data(column, history_df):
            if column in history_df.columns:
                return True

            else:
                log.info(f'Not enough data for "{column}"-related strategy')
                return False

        log.info("Preparing conditions")

        condition_types_list = (
            "Blank",
            "Volatility",
            "Trend",
            "Candle",
            "Overlap",
            "Momentum",
            "Volume",
            "Cycles",
        )
        conditions_dict = {ct: dict() for ct in condition_types_list}

        """ Blank """
        conditions_dict["Blank"]["HOLD"] = {
            "buy": lambda x: True,
            "sell": lambda x: False,
        }

        """ Cycles """
        # EBSW (Even Better Sinewave)
        history_df.ta.ebsw(append=True)
        if _check_enough_data('EBSW_40_10', history_df):
            conditions_dict["Cycles"]["EBSW"] = {
                "buy": lambda x: x["EBSW_40_10"] > 0.5,
                "sell": lambda x: x["EBSW_40_10"] < -0.5,
            }

        """ Volume """
        # PVT (Price Volume Trend)
        history_df.ta.pvt(append=True)
        if _check_enough_data('PVT_10', history_df):
            history_df.ta.sma(close="PVT", length=9, append=True)
            conditions_dict["Volume"]["PVT"] = {
                "buy": lambda x: x["SMA_9"] < x["PVT"],
                "sell": lambda x: x["SMA_9"] > x["PVT"],
            }

        # CMF (Chaikin Money Flow)
        history_df.ta.cmf(append=True)
        if _check_enough_data('CMF_10', history_df):
            conditions_dict["Volume"]["CMF"] = {
                "buy": lambda x: x["CMF_20"] > 0,
                "sell": lambda x: x["CMF_20"] < 0,
            }

        # KVO (Klinger Volume Oscillator)
        history_df.ta.kvo(append=True)
        if _check_enough_data('KVO_34_55_13', history_df):
            conditions_dict["Volume"]["KVO"] = {
                "buy": lambda x: x["KVO_34_55_13"] > x["KVOs_34_55_13"],
                "sell": lambda x: x["KVO_34_55_13"] < x["KVOs_34_55_13"],
            }


        """ Volatility """
        # MASSI (Mass Index)
        history_df.ta.massi(append=True)
        if _check_enough_data('MASSI_9_25', history_df):
            conditions_dict["Volatility"]["MASSI"] = {
                "buy": lambda x: 26 < x["MASSI_9_25"] < 27,
                "sell": lambda x: 26 < x["MASSI_9_25"] < 27,
            }

        # HWC (Holt-Winter Channel)
        history_df.ta.hwc(append=True)
        if _check_enough_data('HWM', history_df):
            conditions_dict["Volatility"]["HWC"] = {
                "buy": lambda x: x["Close"] > x["HWM"],
                "sell": lambda x: x["Close"] < x["HWM"],
            }

        # BBANDS (Bollinger Bands)
        history_df.ta.bbands(length=20, std=2, append=True)
        if _check_enough_data('BBL_20_2.0', history_df):
            conditions_dict["Volatility"]["BBANDS"] = {
                "buy": lambda x: x["Close"] > x["BBL_20_2.0"],
                "sell": lambda x: x["Close"] < x["BBU_20_2.0"],
            }

        """ Candle """
        # HA (Heikin-Ashi)
        history_df.ta.ha(append=True)
        if _check_enough_data('HA_open', history_df):
            conditions_dict["Candle"]["HA"] = {
                "buy": lambda x: (x["HA_open"] < x["HA_close"])
                and (x["HA_low"] == x["HA_open"]),
                "sell": lambda x: (x["HA_open"] > x["HA_close"])
                and (x["HA_high"] == x["HA_open"]),
            }

        """ Trend """
        # PSAR (Parabolic Stop and Reverse)
        history_df.ta.psar(append=True)
        if _check_enough_data('PSARl_0.02_0.2', history_df):
            conditions_dict["Trend"]["PSAR"] = {
                "buy": lambda x: x["Close"] > x["PSARl_0.02_0.2"],
                "sell": lambda x: x["Close"] < x["PSARs_0.02_0.2"],
            }

        # CHOP (Choppiness Index)
        history_df.ta.chop(append=True)
        if _check_enough_data('CHOP_14_1_100', history_df):
            conditions_dict["Trend"]["CHOP"] = {
                "buy": lambda x: x["CHOP_14_1_100"] < 61.8,
                "sell": lambda x: x["CHOP_14_1_100"] > 61.8,
            }

        # CKSP (Chande Kroll Stop)
        history_df.ta.cksp(append=True)
        if _check_enough_data('CKSPl_10_3_20', history_df):
            conditions_dict["Trend"]["CKSP"] = {
                "buy": lambda x: x["CKSPl_10_3_20"] > x["CKSPs_10_3_20"],
                "sell": lambda x: x["CKSPl_10_3_20"] < x["CKSPs_10_3_20"],
            }

        # ADX (Average Directional Movement Index)
        history_df.ta.adx(append=True)
        if _check_enough_data('DMP_14', history_df):
            conditions_dict["Trend"]["ADX"] = {
                "buy": lambda x: x["DMP_14"] > x["DMN_14"],
                "sell": lambda x: x["DMP_14"] < x["DMN_14"],
            }

        """ Overlap """
        # ALMA (Arnaud Legoux Moving Average)
        history_df.ta.alma(length=15, append=True)
        if _check_enough_data('ALMA_15_6.0_0.85', history_df):
            conditions_dict["Overlap"]["ALMA"] = {
                "buy": lambda x: x["Close"] > x["ALMA_15_6.0_0.85"],
                "sell": lambda x: x["Close"] < x["ALMA_15_6.0_0.85"],
            }

        # GHLA (Gann High-Low Activator)
        history_df.ta.hilo(append=True)
        if _check_enough_data('HILO_13_21', history_df):
            conditions_dict["Overlap"]["GHLA"] = {
                "buy": lambda x: x["Close"] > x["HILO_13_21"],
                "sell": lambda x: x["Close"] < x["HILO_13_21"],
            }

        # SUPERT (Supertrend)
        history_df.ta.supertrend(append=True)
        if _check_enough_data('SUPERT_7_3.0', history_df):
            conditions_dict["Overlap"]["SUPERT"] = {
                "buy": lambda x: x["Close"] > x["SUPERT_7_3.0"],
                "sell": lambda x: x["Close"] < x["SUPERT_7_3.0"],
            }

        # LINREG (Linear Regression)
        history_df.ta.linreg(append=True, r=True, offset=1)
        if _check_enough_data('LRr_14', history_df):
            history_df["LRrLag_14"] = history_df["LRr_14"]
            history_df.ta.linreg(append=True, r=True)
            conditions_dict["Overlap"]["LINREG"] = {
                "buy": lambda x: x["LRr_14"] > x["LRrLag_14"],
                "sell": lambda x: x["LRr_14"] < x["LRrLag_14"],
            }

        """ Momentum """
        # RSI (Relative Strength Index)
        history_df.ta.rsi(length=14, append=True)
        if _check_enough_data('RSI_14', history_df):
            conditions_dict["Momentum"]["RSI"] = {
                "buy": lambda x: x["RSI_14"] > 50,
                "sell": lambda x: x["RSI_14"] < 50,
            }

        # RVGI (Relative Vigor Index)
        history_df.ta.rvgi(append=True)
        if _check_enough_data('RVGI_14_4', history_df):
            conditions_dict["Momentum"]["RVGI"] = {
                "buy": lambda x: x["RVGI_14_4"] > x["RVGIs_14_4"],
                "sell": lambda x: x["RVGI_14_4"] < x["RVGIs_14_4"],
            }

        # MACD (Moving Average Convergence Divergence)
        history_df.ta.macd(fast=8, slow=21, signal=5, append=True)
        if _check_enough_data('MACD_8_21_5', history_df):
            conditions_dict["Momentum"]["MACD"] = {
                "buy": lambda x: x["MACD_8_21_5"] > x["MACDs_8_21_5"],
                "sell": lambda x: x["MACD_8_21_5"] < x["MACDs_8_21_5"],
            }

        # STOCH (Stochastic Oscillator)
        history_df.ta.stoch(k=14, d=3, append=True)
        if _check_enough_data('STOCHd_14_3_3', history_df):
            conditions_dict["Momentum"]["STOCH"] = {
                "buy": lambda x: x["STOCHd_14_3_3"] < 80 and x["STOCHk_14_3_3"] < 80,
                "sell": lambda x: x["STOCHd_14_3_3"] > 20 and x["STOCHk_14_3_3"] > 20,
            }

        # UO (Ultimate Oscillator)
        history_df.ta.uo(append=True)
        if _check_enough_data('UO_7_14_28', history_df):
            conditions_dict["Momentum"]["UO"] = {
                "buy": lambda x: x["UO_7_14_28"] < 30,
                "sell": lambda x: x["UO_7_14_28"] > 70,
            }

        return history_df.iloc[skip_points:], conditions_dict

    def generate_strategies_list(self):
        log.info("Generating strategies list")

        strategies_list = [[("Blank", "HOLD")]]

        # + Triple indicator strategies (try every combination of different types)
        indicators_list = list()
        special_case_indicators_list = (
            "HOLD"  # should not participate in autogenerating strategies
        )
        for indicator_type, indicators_dict in self.conditions_dict.items():
            indicators_list += [
                (indicator_type, indicator)
                for indicator in indicators_dict.keys()
                if indicator not in special_case_indicators_list
            ]

        for i_1, indicator_1 in enumerate(indicators_list):
            temp_indicators_list = indicators_list[i_1:]
            for i_2, indicator_2 in enumerate(temp_indicators_list):
                if indicator_1[0] == indicator_2[0]:
                    continue
                for indicator_3 in temp_indicators_list[i_2:]:
                    if indicator_2[0] == indicator_3[0]:
                        continue
                    strategies_list.append([indicator_1, indicator_2, indicator_3])

        return strategies_list

    def parse_strategies_list(self, strategies_str_list):
        log.info("Parsing strategies list")

        strategies_list = [[("Blank", "HOLD")]]
        for (
            strategy_str
        ) in (
            strategies_str_list
        ):  # "(Trend) CKSP + (Overlap) SUPERT + (Momentum) STOCH"
            strategy_components_list = [
                i.strip().split(" ") for i in strategy_str.split("+")
            ]  # [['(Trend)', 'CKSP'], ['(Overlap)', 'SUPERT'], ['(Momentum)', 'STOCH']]
            strategy = [
                (i[0][1:-1], i[1]) for i in strategy_components_list
            ]  # [('Trend', 'CKSP'), ('Overlap', 'SUPERT'), ('Momentum', 'STOCH')]
            strategies_list.append(strategy)

        return strategies_list

    def generate_strategies_dict(self, strategies_list):
        log.info("Generating strategies dict")

        strategies_dict = dict()
        for strategy_list in strategies_list:
            strategy_dict = dict()
            for order_type in ("buy", "sell"):
                strategy_dict[order_type] = [
                    self.conditions_dict[strategy_component[0]][strategy_component[1]][
                        order_type
                    ]
                    for strategy_component in strategy_list
                ]
            strategies_dict[
                " + ".join([f"({i[0]}) {i[1]}" for i in strategy_list])
            ] = strategy_dict

        return strategies_dict

    def get_signal(self, ticker_name, strategies_dict):
        log.info("Getting signal")

        summary = {
            "ticker_name": ticker_name,
            "strategies": dict(),
            "max_output": dict(),
        }

        for strategy in strategies_dict:
            summary["strategies"][strategy] = {"transactions": list(), "result": 0}

            TRANSACTION_COMISSION = 0.0025

            balance_list = list()
            balance_dict = {
                "deposit": 1000,
                "market": None,
                "total": 1000,
                "order_price": 0,
                "buy_signal": np.nan,
                "sell_signal": np.nan,
            }
            for i, row in self.history_df.iterrows():
                date = str(i)[:-6]

                # Sell event
                if (
                    all(map(lambda x: x(row), strategies_dict[strategy]["sell"]))
                    and balance_dict["market"] is not None
                ):
                    summary["strategies"][strategy]["transactions"].append(
                        f'({date}) Sell at {row["Close"]}'
                    )
                    price_change = (
                        row["Close"] - balance_dict["order_price"]
                    ) / balance_dict["order_price"]
                    balance_dict["deposit"] = (
                        balance_dict["market"]
                        * (1 + price_change)
                        * (1 - TRANSACTION_COMISSION)
                    )
                    balance_dict["market"] = None
                    balance_dict["total"] = balance_dict["deposit"]
                    balance_dict["sell_signal"] = balance_dict["total"]

                # Buy event
                elif (
                    all(map(lambda x: x(row), strategies_dict[strategy]["buy"]))
                    and balance_dict["deposit"] is not None
                ):
                    summary["strategies"][strategy]["transactions"].append(
                        f'({date}) Buy at {row["Close"]}'
                    )
                    balance_dict["buy_signal"] = balance_dict["total"]
                    balance_dict["order_price"] = row["Close"]
                    balance_dict["market"] = balance_dict["deposit"] * (
                        1 - TRANSACTION_COMISSION
                    )
                    balance_dict["deposit"] = None
                    balance_dict["total"] = balance_dict["market"]

                # Hold on market
                else:
                    if balance_dict["deposit"] is None:
                        price_change = (
                            row["Close"] - balance_dict["order_price"]
                        ) / balance_dict["order_price"]
                        balance_dict["total"] = balance_dict["market"] * (
                            1 + price_change
                        )
                        balance_dict["buy_signal"] = np.nan
                        balance_dict["sell_signal"] = np.nan

                balance_list.append(copy(balance_dict))

            summary["strategies"][strategy]["result"] = round(balance_dict["total"])
            summary["strategies"][strategy]["signal"] = (
                "sell" if balance_dict["market"] is None else "buy"
            )
            summary["strategies"][strategy]["transactions_counter"] = len(
                summary["strategies"][strategy]["transactions"]
            )
            if (
                balance_dict["total"] > summary["max_output"].get("result", 0)
                and strategy != "(Blank) HOLD"
            ):
                for col in ["total", "buy_signal", "sell_signal"]:
                    self.history_df.loc[:, col] = [i[col] for i in balance_list]

                summary["max_output"] = {
                    "strategy": strategy,
                    "result": summary["strategies"][strategy]["result"],
                    "signal": summary["strategies"][strategy]["signal"],
                    "transactions_counter": summary["strategies"][strategy][
                        "transactions_counter"
                    ],
                }

        summary["hold_result"] = summary["strategies"].pop("(Blank) HOLD")["result"]
        summary["sorted_strategies_list"] = sorted(
            summary["strategies"].items(),
            key=lambda x: int(x[1]["result"]),
            reverse=True,
        )
        summary["signal"] = summary["max_output"]["signal"]

        sorted_signals_list = [
            i[1]["signal"] for i in summary["sorted_strategies_list"]
        ]
        if summary["max_output"]["transactions_counter"] == 1:
            log.info("Top 3 strategies were considered")
            summary["signal"] = (
                "buy" if sorted_signals_list[:3].count("buy") >= 2 else "sell"
            )

        return summary

    @staticmethod
    def load(filename_prefix):
        log.info(f"Loading {filename_prefix}_strategies.json")

        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            with open(f"{current_dir}/{filename_prefix}_strategies.json", "r") as f:
                strategies_json = json.load(f)
        except:
            strategies_json = dict()

        return strategies_json

    @staticmethod
    def dump(filename_prefix, strategies_json):
        log.info(f"Dump {filename_prefix}_strategies.json")

        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(f"{current_dir}/{filename_prefix}_strategies.json", "w") as f:
            json.dump(strategies_json, f, indent=4)
