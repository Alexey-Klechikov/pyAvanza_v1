"""
This module contains all technical indicators and strategies generation routines
"""


import json
import logging
import os
import warnings
from copy import copy
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import pandas_ta as ta
from avanza import OrderType as Signal

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None  # type: ignore
pd.set_option("display.expand_frame_repr", False)

log = logging.getLogger("main.utils.strategy_ta")


@dataclass
class StrategyInfo:
    transactions: list = field(default_factory=list)
    result: float = 0
    signal: Signal = Signal.SELL
    transactions_counter: int = 0


@dataclass
class MaxOutput:
    strategy: str = ""
    result: float = 0
    signal: Signal = Signal.SELL
    transactions_counter: int = 0


@dataclass
class Summary:
    ticker_name: str
    signal: Signal = Signal.SELL
    hold_result: float = 0
    strategies: Dict[str, StrategyInfo] = field(default_factory=dict)
    max_output: MaxOutput = MaxOutput()
    sorted_strategies: list = field(default_factory=list)

    def sort_strategies(self) -> None:
        self.sorted_strategies = sorted(
            self.strategies.items(),
            key=lambda x: x[1].result,
            reverse=True,
        )


@dataclass
class Balance:
    deposit: float = 1000
    market: float = np.nan
    total: float = 1000
    order_price: float = 0
    buy_signal: float = np.nan
    sell_signal: float = np.nan


class StrategyTA:
    def __init__(self, data: pd.DataFrame, **kwargs):
        skip_points = kwargs.get("skip_points", 100)
        self.data, self.conditions, columns_needed = self.prepare_conditions(
            data, skip_points
        )

        self.drop_columns(columns_needed)

        if kwargs.get("strategies", []) != []:
            strategies_component_names = self.parse_strategies_names(
                kwargs["strategies"]
            )
        else:
            strategies_component_names = self.generate_strategies_names()

        strategies = self.generate_strategies(strategies_component_names)
        self.summary = self.get_signal(kwargs.get("ticker_name", False), strategies)

    def prepare_conditions(
        self, data: pd.DataFrame, skip_points: int
    ) -> Tuple[pd.DataFrame, dict, List[str]]:
        log.debug("Preparing conditions")

        _check_enough_data = (
            lambda column, data: True if column in data.columns else False
        )

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
        conditions: dict = {ct: {} for ct in condition_types_list}

        """ Blank """
        conditions["Blank"]["HOLD"] = {
            Signal.BUY: lambda x: True,
            Signal.SELL: lambda x: False,
        }
        columns_needed = ["Open", "High", "Low", "Close", "Volume"]

        """ Cycles """
        # EBSW (Even Better Sinewave)
        data.ta.ebsw(append=True)
        if _check_enough_data("EBSW_40_10", data):
            conditions["Cycles"]["EBSW"] = {
                Signal.BUY: lambda x: x["EBSW_40_10"] > 0.5,
                Signal.SELL: lambda x: x["EBSW_40_10"] < -0.5,
            }
            columns_needed += ["EBSW_40_10"]

        """ Volume """
        # PVT (Price Volume Trend)
        data.ta.pvt(append=True)
        if _check_enough_data("PVT", data):
            data.ta.sma(close="PVT", length=9, append=True)
            conditions["Volume"]["PVT"] = {
                Signal.BUY: lambda x: x["SMA_9"] < x["PVT"],
                Signal.SELL: lambda x: x["SMA_9"] > x["PVT"],
            }
            columns_needed += ["SMA_9", "PVT"]

        # CMF (Chaikin Money Flow)
        data.ta.cmf(append=True)
        if _check_enough_data("CMF_20", data):
            cmf = {"max": data["CMF_20"].max(), "min": data["CMF_20"].min()}
            conditions["Volume"]["CMF"] = {
                Signal.BUY: lambda x: x["CMF_20"] > cmf["max"] * 0.2,
                Signal.SELL: lambda x: x["CMF_20"] < cmf["min"] * 0.2,
            }
            columns_needed += ["CMF_20"]

        # EFI (Elder's Force Index)
        data.ta.cmf(append=True)
        if _check_enough_data("EFI_13", data):
            conditions["Volume"]["EFI"] = {
                Signal.BUY: lambda x: x["EFI_13"] < 0,
                Signal.SELL: lambda x: x["EFI_13"] > 0,
            }
            columns_needed += ["EFI_13"]

        # KVO (Klinger Volume Oscillator)
        try:
            data.ta.kvo(append=True)
            if _check_enough_data("KVO_34_55_13", data):
                conditions["Volume"]["KVO"] = {
                    Signal.BUY: lambda x: x["KVO_34_55_13"] > x["KVOs_34_55_13"],
                    Signal.SELL: lambda x: x["KVO_34_55_13"] < x["KVOs_34_55_13"],
                }
                columns_needed += ["KVO_34_55_13", "KVOs_34_55_13"]
        except Exception as exc:
            log.warning(f"KVO not available: {exc}")

        """ Volatility """
        # MASSI (Mass Index)
        data.ta.massi(append=True)
        if _check_enough_data("MASSI_9_25", data):
            conditions["Volatility"]["MASSI"] = {
                Signal.BUY: lambda x: 26 < x["MASSI_9_25"] < 27,
                Signal.SELL: lambda x: 26 < x["MASSI_9_25"] < 27,
            }
            columns_needed += ["MASSI_9_25"]

        # HWC (Holt-Winter Channel)
        data.ta.hwc(append=True)
        if _check_enough_data("HWM", data):
            conditions["Volatility"]["HWC"] = {
                Signal.BUY: lambda x: x["Close"] > x["HWM"],
                Signal.SELL: lambda x: x["Close"] < x["HWM"],
            }
            columns_needed += ["HWM"]

        # BBANDS (Bollinger Bands)
        data.ta.bbands(length=20, std=2, append=True)
        if _check_enough_data("BBL_20_2.0", data):
            conditions["Volatility"]["BBANDS"] = {
                Signal.BUY: lambda x: x["Close"] > x["BBL_20_2.0"],
                Signal.SELL: lambda x: x["Close"] < x["BBU_20_2.0"],
            }
            columns_needed += ["BBL_20_2.0", "BBU_20_2.0"]

        # ACCBANDS (Acceleration Bands)
        data.ta.accbands(append=True)
        if _check_enough_data("ACCBU_20", data):
            conditions["Volatility"]["ACCBANDS"] = {
                Signal.BUY: lambda x: x["Close"] > x["ACCBU_20"],
                Signal.SELL: lambda x: x["Close"] < x["ACCBU_20"],
            }
            columns_needed += ["ACCBU_20"]

        """ Candle """
        # HA (Heikin-Ashi)
        data.ta.ha(append=True)
        if _check_enough_data("HA_open", data):
            conditions["Candle"]["HA"] = {
                Signal.BUY: lambda x: (x["HA_open"] < x["HA_close"])
                and (x["HA_low"] == x["HA_open"]),
                Signal.SELL: lambda x: (x["HA_open"] > x["HA_close"])
                and (x["HA_high"] == x["HA_open"]),
            }
            columns_needed += ["HA_open", "HA_close", "HA_low", "HA_high"]

        """ Trend """
        # PSAR (Parabolic Stop and Reverse)
        data.ta.psar(append=True)
        if _check_enough_data("PSARl_0.02_0.2", data):
            conditions["Trend"]["PSAR"] = {
                Signal.BUY: lambda x: x["Close"] > x["PSARl_0.02_0.2"],
                Signal.SELL: lambda x: x["Close"] < x["PSARs_0.02_0.2"],
            }
            columns_needed += ["PSARl_0.02_0.2", "PSARs_0.02_0.2"]

        # CHOP (Choppiness Index)
        data.ta.chop(append=True)
        if _check_enough_data("CHOP_14_1_100", data):
            conditions["Trend"]["CHOP"] = {
                Signal.BUY: lambda x: x["CHOP_14_1_100"] < 61.8,
                Signal.SELL: lambda x: x["CHOP_14_1_100"] > 61.8,
            }
            columns_needed += ["CHOP_14_1_100"]

        # CKSP (Chande Kroll Stop)
        data.ta.cksp(append=True)
        if _check_enough_data("CKSPl_10_3_20", data):
            conditions["Trend"]["CKSP"] = {
                Signal.BUY: lambda x: x["CKSPl_10_3_20"] > x["CKSPs_10_3_20"],
                Signal.SELL: lambda x: x["CKSPl_10_3_20"] < x["CKSPs_10_3_20"],
            }
            columns_needed += ["CKSPl_10_3_20", "CKSPs_10_3_20"]

        """ Overlap """
        # GHLA (Gann High-Low Activator)
        data.ta.hilo(append=True)
        if _check_enough_data("HILO_13_21", data):
            conditions["Overlap"]["GHLA"] = {
                Signal.BUY: lambda x: x["Close"] > x["HILO_13_21"],
                Signal.SELL: lambda x: x["Close"] < x["HILO_13_21"],
            }
            columns_needed += ["HILO_13_21"]

        # SUPERT (Supertrend)
        data.ta.supertrend(append=True)
        if _check_enough_data("SUPERT_7_3.0", data):
            conditions["Overlap"]["SUPERT"] = {
                Signal.BUY: lambda x: x["Close"] > x["SUPERT_7_3.0"],
                Signal.SELL: lambda x: x["Close"] < x["SUPERT_7_3.0"],
            }
            columns_needed += ["SUPERT_7_3.0"]

        # LINREG (Linear Regression)
        data.ta.linreg(append=True, r=True)
        if _check_enough_data("LRr_14", data):
            data["LRr_direction"] = (
                data["LRr_14"].rolling(2).apply(lambda x: x.iloc[1] > x.iloc[0])
            )
            conditions["Overlap"]["LINREG"] = {
                Signal.BUY: lambda x: x["LRr_direction"] == 1,
                Signal.SELL: lambda x: x["LRr_direction"] == 0,
            }
            columns_needed += ["LRr_direction"]

        """ Momentum """
        # STC (Schaff Trend Cycle)
        data.ta.stc(append=True)
        if _check_enough_data("STC_10_12_26_0.5", data):
            conditions["Momentum"]["STC"] = {
                Signal.BUY: lambda x: x["STC_10_12_26_0.5"] < 75,
                Signal.SELL: lambda x: x["STC_10_12_26_0.5"] > 25,
            }
            columns_needed += ["STC_10_12_26_0.5"]

        # CCI (Commodity Channel Index)
        data.ta.cci(length=20, append=True, offset=1)
        if _check_enough_data("CCI_20_0.015", data):
            data["CCI_direction"] = (
                data["CCI_20_0.015"].rolling(2).apply(lambda x: x.iloc[1] > x.iloc[0])
            )
            conditions["Overlap"]["LINREG"] = {
                Signal.BUY: lambda x: x["CCI_20_0.015"] < -100
                and x["CCI_direction"] == 1,
                Signal.SELL: lambda x: x["CCI_20_0.015"] > 100
                and x["CCI_direction"] == 0,
            }
            columns_needed += ["CCI_20_0.015", "CCI_direction"]

        # RVGI (Relative Vigor Index)
        data.ta.rvgi(append=True)
        if _check_enough_data("RVGI_14_4", data):
            conditions["Momentum"]["RVGI"] = {
                Signal.BUY: lambda x: x["RVGI_14_4"] > x["RVGIs_14_4"],
                Signal.SELL: lambda x: x["RVGI_14_4"] < x["RVGIs_14_4"],
            }
            columns_needed += ["RVGI_14_4", "RVGIs_14_4"]

        # MACD (Moving Average Convergence Divergence)
        data.ta.macd(fast=8, slow=21, signal=5, append=True)
        if _check_enough_data("MACD_8_21_5", data):
            data["MACD_ma_diff"] = (
                data["MACDh_8_21_5"].rolling(2).apply(lambda x: x.iloc[1] > x.iloc[0])
            )
            conditions["Momentum"]["MACD"] = {
                Signal.BUY: lambda x: x["MACD_ma_diff"] == 1,
                Signal.SELL: lambda x: x["MACD_ma_diff"] == 0,
            }
            columns_needed += ["MACD_ma_diff"]

        # STOCH (Stochastic Oscillator)
        data.ta.stoch(k=14, d=3, append=True)
        if _check_enough_data("STOCHd_14_3_3", data):
            conditions["Momentum"]["STOCH"] = {
                Signal.BUY: lambda x: x["STOCHd_14_3_3"] < 80
                and x["STOCHk_14_3_3"] < 80,
                Signal.SELL: lambda x: x["STOCHd_14_3_3"] > 20
                and x["STOCHk_14_3_3"] > 20,
            }
            columns_needed += ["STOCHd_14_3_3", "STOCHk_14_3_3"]

        return data.iloc[skip_points:], conditions, columns_needed

    def drop_columns(self, columns_needed: list) -> None:
        columns_drop = list(set(self.data.columns) - (set(columns_needed)))

        self.data.drop(columns=columns_drop, inplace=True)

    def generate_strategies_names(self) -> list:
        # + Triple indicator strategies (try every combination of different types)

        log.debug("Generating strategies list")

        strategies_component_names = [[("Blank", "HOLD")]]
        indicators_names = []
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

    def parse_strategies_names(
        self, strategies_names: list[str]
    ) -> list[list[tuple[str, str]]]:
        log.debug("Parsing strategies list")

        strategies_component_names = [[("Blank", "HOLD")]]

        for strategy in strategies_names:
            # "(Trend) CKSP + (Overlap) SUPERT + (Momentum) STOCH"
            strategy_components_v1 = [i.strip().split(" ") for i in strategy.split("+")]

            # [['(Trend)', 'CKSP'], ['(Overlap)', 'SUPERT'], ['(Momentum)', 'STOCH']]
            strategy_components_v2 = [
                (i[0][1:-1], i[1]) for i in strategy_components_v1
            ]

            # [('Trend', 'CKSP'), ('Overlap', 'SUPERT'), ('Momentum', 'STOCH')]
            strategies_component_names += [strategy_components_v2]

        return strategies_component_names

    def generate_strategies(
        self, strategies_component_names: list[list[tuple[str, str]]]
    ) -> dict:
        log.debug("Generating strategies dict")

        strategies = {}
        for strategy_components_names in strategies_component_names:
            strategy = {}

            for order_type in Signal:
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

    def get_signal(self, ticker_name: str, strategies: dict) -> Summary:
        log.debug("Getting signal")

        summary = Summary(ticker_name)

        for strategy in strategies:
            summary.strategies[strategy] = StrategyInfo()

            TRANSACTION_COMMISSION = 0.0025

            balance_sequence = []
            balance = Balance()

            for i, row in self.data.iterrows():
                date = str(i)[:-6]

                # Sell event
                if all(
                    map(lambda x: x(row), strategies[strategy][Signal.SELL])
                ) and not np.isnan(balance.market):
                    summary.strategies[strategy].transactions.append(
                        f'({date}) Sell at {row["Close"]}'
                    )
                    price_change = (
                        row["Close"] - balance.order_price
                    ) / balance.order_price
                    balance.deposit = (
                        balance.market
                        * (1 + price_change)
                        * (1 - TRANSACTION_COMMISSION)
                    )
                    balance.market = np.nan
                    balance.total = balance.deposit
                    balance.sell_signal = balance.total

                # Buy event
                elif all(
                    map(lambda x: x(row), strategies[strategy][Signal.BUY])
                ) and not np.isnan(balance.deposit):
                    summary.strategies[strategy].transactions.append(
                        f'({date}) Buy at {row["Close"]}'
                    )
                    balance.buy_signal = balance.total
                    balance.order_price = row["Close"]
                    balance.market = balance.deposit * (1 - TRANSACTION_COMMISSION)
                    balance.deposit = np.nan
                    balance.total = balance.market

                # Hold on market
                else:
                    if np.isnan(balance.deposit):
                        price_change = (
                            row["Close"] - balance.order_price
                        ) / balance.order_price
                        balance.total = balance.market * (1 + price_change)
                        balance.buy_signal = np.nan
                        balance.sell_signal = np.nan

                balance_sequence.append(copy(balance))

            summary.strategies[strategy].result = round(balance.total)
            summary.strategies[strategy].signal = (
                Signal.SELL if np.isnan(balance.market) else Signal.BUY
            )
            summary.strategies[strategy].transactions_counter = len(
                summary.strategies[strategy].transactions
            )
            if balance.total > summary.max_output.result and strategy != "(Blank) HOLD":
                for col in ["total", "buy_signal", "sell_signal"]:
                    self.data.loc[:, col] = [getattr(i, col) for i in balance_sequence]  # type: ignore

                summary.max_output = MaxOutput(
                    strategy=strategy,
                    result=summary.strategies[strategy].result,
                    signal=summary.strategies[strategy].signal,
                    transactions_counter=summary.strategies[
                        strategy
                    ].transactions_counter,
                )

        summary.hold_result = summary.strategies.pop("(Blank) HOLD").result
        summary.sort_strategies()
        summary.signal = summary.max_output.signal

        sorted_signals = [getattr(i[1], "signal") for i in summary.sorted_strategies]
        if summary.max_output.transactions_counter == 1:
            summary.signal = (
                Signal.BUY if sorted_signals[:3].count(Signal.BUY) >= 2 else Signal.SELL
            )

        log.info(
            f'> {summary.signal.name}{". Top 3 strategies were considered" if summary.max_output.transactions_counter == 1 else ""}'
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

        except (JSONDecodeError, TypeError):
            strategies = {}

        return strategies

    @staticmethod
    def dump(filename_suffix: str, strategies: dict):
        log.info(f"Dump strategies_{filename_suffix}.json")

        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        with open(f"{current_dir}/data/strategies_{filename_suffix}.json", "w") as f:
            json.dump(strategies, f, indent=4)
