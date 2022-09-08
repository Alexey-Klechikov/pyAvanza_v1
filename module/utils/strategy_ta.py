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
from typing import Tuple
from context import Context


warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None
pd.set_option("display.expand_frame_repr", False)

log = logging.getLogger("main.utils.strategy_ta")


class Strategy_TA:
    def __init__(self, data: pd.DataFrame, **kwargs):
        skip_points = kwargs.get("skip_points", 100)
        self.data, self.conditions = self.prepare_conditions(data, skip_points)

        if kwargs.get("strategies", list()) != list():
            strategies_component_names = self.parse_strategies_names(
                kwargs["strategies"]
            )
        else:
            strategies_component_names = self.generate_strategies_names()

        strategies = self.generate_strategies(strategies_component_names)
        self.summary = self.get_signal(kwargs.get("ticker_name", False), strategies)

    def prepare_conditions(self, data: pd.DataFrame, skip_points: int) -> Tuple[pd.DataFrame, dict]:
        def _check_enough_data(column: str, data: pd.DataFrame) -> bool:
            if column in data.columns:
                return True

            else:
                log.warning(f'Not enough data for "{column}"-related strategy')
                return False

        log.debug("Preparing conditions")

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
        conditions = {ct: dict() for ct in condition_types_list}

        """ Blank """
        conditions["Blank"]["HOLD"] = {
            "buy": lambda x: True,
            "sell": lambda x: False,
        }

        """ Cycles """
        # EBSW (Even Better Sinewave)
        data.ta.ebsw(append=True)
        if _check_enough_data("EBSW_40_10", data):
            conditions["Cycles"]["EBSW"] = {
                "buy": lambda x: x["EBSW_40_10"] > 0.5,
                "sell": lambda x: x["EBSW_40_10"] < -0.5,
            }

        """ Volume """
        # PVT (Price Volume Trend)
        data.ta.pvt(append=True)
        if _check_enough_data("PVT", data):
            data.ta.sma(close="PVT", length=9, append=True)
            conditions["Volume"]["PVT"] = {
                "buy": lambda x: x["SMA_9"] < x["PVT"],
                "sell": lambda x: x["SMA_9"] > x["PVT"],
            }

        # CMF (Chaikin Money Flow)
        data.ta.cmf(append=True)
        if _check_enough_data("CMF_20", data):
            conditions["Volume"]["CMF"] = {
                "buy": lambda x: x["CMF_20"] > 0,
                "sell": lambda x: x["CMF_20"] < 0,
            }

        # KVO (Klinger Volume Oscillator)
        try:
            data.ta.kvo(append=True)
            if _check_enough_data("KVO_34_55_13", data):
                conditions["Volume"]["KVO"] = {
                    "buy": lambda x: x["KVO_34_55_13"] > x["KVOs_34_55_13"],
                    "sell": lambda x: x["KVO_34_55_13"] < x["KVOs_34_55_13"],
                }
        except:
            log.warning("KVO not available")

        """ Volatility """
        # MASSI (Mass Index)
        data.ta.massi(append=True)
        if _check_enough_data("MASSI_9_25", data):
            conditions["Volatility"]["MASSI"] = {
                "buy": lambda x: 26 < x["MASSI_9_25"] < 27,
                "sell": lambda x: 26 < x["MASSI_9_25"] < 27,
            }

        # HWC (Holt-Winter Channel)
        data.ta.hwc(append=True)
        if _check_enough_data("HWM", data):
            conditions["Volatility"]["HWC"] = {
                "buy": lambda x: x["Close"] > x["HWM"],
                "sell": lambda x: x["Close"] < x["HWM"],
            }

        # BBANDS (Bollinger Bands)
        data.ta.bbands(length=20, std=2, append=True)
        if _check_enough_data("BBL_20_2.0", data):
            conditions["Volatility"]["BBANDS"] = {
                "buy": lambda x: x["Close"] > x["BBL_20_2.0"],
                "sell": lambda x: x["Close"] < x["BBU_20_2.0"],
            }

        """ Candle """
        # HA (Heikin-Ashi)
        data.ta.ha(append=True)
        if _check_enough_data("HA_open", data):
            conditions["Candle"]["HA"] = {
                "buy": lambda x: (x["HA_open"] < x["HA_close"])
                and (x["HA_low"] == x["HA_open"]),
                "sell": lambda x: (x["HA_open"] > x["HA_close"])
                and (x["HA_high"] == x["HA_open"]),
            }

        """ Trend """
        # PSAR (Parabolic Stop and Reverse)
        data.ta.psar(append=True)
        if _check_enough_data("PSARl_0.02_0.2", data):
            conditions["Trend"]["PSAR"] = {
                "buy": lambda x: x["Close"] > x["PSARl_0.02_0.2"],
                "sell": lambda x: x["Close"] < x["PSARs_0.02_0.2"],
            }

        # CHOP (Choppiness Index)
        data.ta.chop(append=True)
        if _check_enough_data("CHOP_14_1_100", data):
            conditions["Trend"]["CHOP"] = {
                "buy": lambda x: x["CHOP_14_1_100"] < 61.8,
                "sell": lambda x: x["CHOP_14_1_100"] > 61.8,
            }

        # CKSP (Chande Kroll Stop)
        data.ta.cksp(append=True)
        if _check_enough_data("CKSPl_10_3_20", data):
            conditions["Trend"]["CKSP"] = {
                "buy": lambda x: x["CKSPl_10_3_20"] > x["CKSPs_10_3_20"],
                "sell": lambda x: x["CKSPl_10_3_20"] < x["CKSPs_10_3_20"],
            }

        # ADX (Average Directional Movement Index)
        data.ta.adx(append=True)
        if _check_enough_data("DMP_14", data):
            conditions["Trend"]["ADX"] = {
                "buy": lambda x: x["DMP_14"] > x["DMN_14"],
                "sell": lambda x: x["DMP_14"] < x["DMN_14"],
            }

        """ Overlap """
        # ALMA (Arnaud Legoux Moving Average)
        data.ta.alma(length=15, append=True)
        if _check_enough_data("ALMA_15_6.0_0.85", data):
            conditions["Overlap"]["ALMA"] = {
                "buy": lambda x: x["Close"] > x["ALMA_15_6.0_0.85"],
                "sell": lambda x: x["Close"] < x["ALMA_15_6.0_0.85"],
            }

        # GHLA (Gann High-Low Activator)
        data.ta.hilo(append=True)
        if _check_enough_data("HILO_13_21", data):
            conditions["Overlap"]["GHLA"] = {
                "buy": lambda x: x["Close"] > x["HILO_13_21"],
                "sell": lambda x: x["Close"] < x["HILO_13_21"],
            }

        # SUPERT (Supertrend)
        data.ta.supertrend(append=True)
        if _check_enough_data("SUPERT_7_3.0", data):
            conditions["Overlap"]["SUPERT"] = {
                "buy": lambda x: x["Close"] > x["SUPERT_7_3.0"],
                "sell": lambda x: x["Close"] < x["SUPERT_7_3.0"],
            }

        # LINREG (Linear Regression)
        data.ta.linreg(append=True, r=True, offset=1)
        if _check_enough_data("LRr_14", data):
            data["LRrLag_14"] = data["LRr_14"]
            data.ta.linreg(append=True, r=True)
            conditions["Overlap"]["LINREG"] = {
                "buy": lambda x: x["LRr_14"] > x["LRrLag_14"],
                "sell": lambda x: x["LRr_14"] < x["LRrLag_14"],
            }

        """ Momentum """
        # STC (Schaff Trend Cycle)
        data.ta.stc(append=True)
        if _check_enough_data("STC_10_12_26_0.5", data):
            conditions["Momentum"]["STC"] = {
                "sell": lambda x: x["STC_10_12_26_0.5"] > 25,
                "buy": lambda x: x["STC_10_12_26_0.5"] < 75,
            }

        # CCI (Commodity Channel Index)
        data.ta.cci(length=20, append=True, offset=1)
        if _check_enough_data("CCI_20_0.015", data):
            data["CCILag_20_0.015"] = data["CCI_20_0.015"]
            data.ta.cci(length=20, append=True)
            conditions["Momentum"]["CCI"] = {
                "sell": lambda x: x["CCI_20_0.015"] > 100
                and x["CCI_20_0.015"] < x["CCILag_20_0.015"],
                "buy": lambda x: x["CCI_20_0.015"] < -100
                and x["CCI_20_0.015"] > x["CCILag_20_0.015"],
            }

        # RSI (Relative Strength Index)
        data.ta.rsi(length=14, append=True)
        if _check_enough_data("RSI_14", data):
            conditions["Momentum"]["RSI"] = {
                "buy": lambda x: x["RSI_14"] > 50,
                "sell": lambda x: x["RSI_14"] < 50,
            }

        # RVGI (Relative Vigor Index)
        data.ta.rvgi(append=True)
        if _check_enough_data("RVGI_14_4", data):
            conditions["Momentum"]["RVGI"] = {
                "buy": lambda x: x["RVGI_14_4"] > x["RVGIs_14_4"],
                "sell": lambda x: x["RVGI_14_4"] < x["RVGIs_14_4"],
            }

        # MACD (Moving Average Convergence Divergence)
        data.ta.macd(fast=8, slow=21, signal=5, append=True)
        if _check_enough_data("MACD_8_21_5", data):
            conditions["Momentum"]["MACD"] = {
                "buy": lambda x: x["MACD_8_21_5"] > x["MACDs_8_21_5"],
                "sell": lambda x: x["MACD_8_21_5"] < x["MACDs_8_21_5"],
            }

        # STOCH (Stochastic Oscillator)
        data.ta.stoch(k=14, d=3, append=True)
        if _check_enough_data("STOCHd_14_3_3", data):
            conditions["Momentum"]["STOCH"] = {
                "buy": lambda x: x["STOCHd_14_3_3"] < 80 and x["STOCHk_14_3_3"] < 80,
                "sell": lambda x: x["STOCHd_14_3_3"] > 20 and x["STOCHk_14_3_3"] > 20,
            }

        # UO (Ultimate Oscillator)
        data.ta.uo(append=True)
        if _check_enough_data("UO_7_14_28", data):
            conditions["Momentum"]["UO"] = {
                "buy": lambda x: x["UO_7_14_28"] < 30,
                "sell": lambda x: x["UO_7_14_28"] > 70,
            }

        return data.iloc[skip_points:], conditions

    def generate_strategies_names(self) -> list:
        # + Triple indicator strategies (try every combination of different types)

        log.debug("Generating strategies list")

        strategies_component_names = [[("Blank", "HOLD")]]
        indicators_names = list()
        special_case_indicators_names = "HOLD"

        for indicator_type, indicators_dict in self.conditions.items():
            indicators_names += [
                (indicator_type, indicator)
                for indicator in indicators_dict.keys()
                if indicator not in special_case_indicators_names
            ]

        for i_1, indicator_1 in enumerate(indicators_names):
            temp_indicators_names = indicators_names[i_1:]

            for i_2, indicator_2 in enumerate(temp_indicators_names):
                if indicator_1[0] == indicator_2[0]:
                    continue

                for indicator_3 in temp_indicators_names[i_2:]:
                    if indicator_2[0] == indicator_3[0]:
                        continue

                    strategies_component_names.append(
                        [indicator_1, indicator_2, indicator_3]
                    )

        return strategies_component_names

    def parse_strategies_names(self, strategies_names: list[str]) -> list[list[tuple[str, str]]]:
        log.debug("Parsing strategies list")

        strategies_component_names = [[("Blank", "HOLD")]]

        for strategy in strategies_names:
            # "(Trend) CKSP + (Overlap) SUPERT + (Momentum) STOCH"
            strategy_components = [i.strip().split(" ") for i in strategy.split("+")]

            # [['(Trend)', 'CKSP'], ['(Overlap)', 'SUPERT'], ['(Momentum)', 'STOCH']]
            strategy_components = [(i[0][1:-1], i[1]) for i in strategy_components]

            # [('Trend', 'CKSP'), ('Overlap', 'SUPERT'), ('Momentum', 'STOCH')]
            strategies_component_names += [strategy_components]

        return strategies_component_names

    def generate_strategies(self, strategies_component_names: list[list[tuple[str, str]]]) -> dict:
        log.debug("Generating strategies dict")

        strategies = dict()
        for strategy_components_names in strategies_component_names:
            strategy = dict()

            for order_type in ("buy", "sell"):
                strategy[order_type] = [
                    self.conditions[strategy_component_name[0]][
                        strategy_component_name[1]
                    ][order_type]
                    for strategy_component_name in strategy_components_names
                ]

            strategies[
                " + ".join([f"({i[0]}) {i[1]}" for i in strategy_components_names])
            ] = strategy

        return strategies

    def get_signal(self, ticker_name: str, strategies: dict) -> dict:
        log.debug("Getting signal")

        summary = {
            "ticker_name": ticker_name,
            "strategies": dict(),
            "max_output": dict(),
        }

        for strategy in strategies:
            summary["strategies"][strategy] = {"transactions": list(), "result": 0}

            TRANSACTION_COMMISSION = 0.0025

            balance_sequence = list()
            balance = {
                "deposit": 1000,
                "market": None,
                "total": 1000,
                "order_price": 0,
                "buy_signal": np.nan,
                "sell_signal": np.nan,
            }

            for i, row in self.data.iterrows():
                date = str(i)[:-6]

                # Sell event
                if (
                    all(map(lambda x: x(row), strategies[strategy]["sell"]))
                    and balance["market"] is not None
                ):
                    summary["strategies"][strategy]["transactions"].append(
                        f'({date}) Sell at {row["Close"]}'
                    )
                    price_change = (row["Close"] - balance["order_price"]) / balance[
                        "order_price"
                    ]
                    balance["deposit"] = (
                        balance["market"]
                        * (1 + price_change)
                        * (1 - TRANSACTION_COMMISSION)
                    )
                    balance["market"] = None
                    balance["total"] = balance["deposit"]
                    balance["sell_signal"] = balance["total"]

                # Buy event
                elif (
                    all(map(lambda x: x(row), strategies[strategy]["buy"]))
                    and balance["deposit"] is not None
                ):
                    summary["strategies"][strategy]["transactions"].append(
                        f'({date}) Buy at {row["Close"]}'
                    )
                    balance["buy_signal"] = balance["total"]
                    balance["order_price"] = row["Close"]
                    balance["market"] = balance["deposit"] * (
                        1 - TRANSACTION_COMMISSION
                    )
                    balance["deposit"] = None
                    balance["total"] = balance["market"]

                # Hold on market
                else:
                    if balance["deposit"] is None:
                        price_change = (
                            row["Close"] - balance["order_price"]
                        ) / balance["order_price"]
                        balance["total"] = balance["market"] * (1 + price_change)
                        balance["buy_signal"] = np.nan
                        balance["sell_signal"] = np.nan

                balance_sequence.append(copy(balance))

            summary["strategies"][strategy]["result"] = round(balance["total"])
            summary["strategies"][strategy]["signal"] = (
                "sell" if balance["market"] is None else "buy"
            )
            summary["strategies"][strategy]["transactions_counter"] = len(
                summary["strategies"][strategy]["transactions"]
            )
            if (
                balance["total"] > summary["max_output"].get("result", 0)
                and strategy != "(Blank) HOLD"
            ):
                for col in ["total", "buy_signal", "sell_signal"]:
                    self.data.loc[:, col] = [i[col] for i in balance_sequence]  # type: ignore

                summary["max_output"] = {
                    "strategy": strategy,
                    "result": summary["strategies"][strategy]["result"],
                    "signal": summary["strategies"][strategy]["signal"],
                    "transactions_counter": summary["strategies"][strategy][
                        "transactions_counter"
                    ],
                }

        summary["hold_result"] = summary["strategies"].pop("(Blank) HOLD")["result"]
        summary["sorted_strategies"] = sorted(
            summary["strategies"].items(),
            key=lambda x: int(x[1]["result"]),
            reverse=True,
        )
        summary["signal"] = summary["max_output"]["signal"]

        sorted_signals = [i[1]["signal"] for i in summary["sorted_strategies"]]
        if summary["max_output"]["transactions_counter"] == 1:
            summary["signal"] = (
                "buy" if sorted_signals[:3].count("buy") >= 2 else "sell"
            )

        log.info(
            f'> {summary["signal"]}{". Top 3 strategies were considered" if summary["max_output"]["transactions_counter"] == 1 else ""}'
        )

        return summary

    @staticmethod
    def load(filename_suffix: str) -> dict:
        log.info(f"Loading strategies_{filename_suffix}.json")

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
    def dump(filename_suffix: str, strategies: dict):
        log.info(f"Dump strategies_{filename_suffix}.json")

        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        with open(f"{current_dir}/data/strategies_{filename_suffix}.json", "w") as f:
            json.dump(strategies, f, indent=4)
