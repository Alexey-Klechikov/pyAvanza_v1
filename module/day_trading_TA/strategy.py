"""
This module contains all technical indicators and strategies generation routines
"""


import json
import logging
import os
import warnings
from datetime import datetime
from json import JSONDecodeError
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import pandas_ta as ta
from avanza import OrderType

from module.day_trading_TA import Instrument

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None  # type: ignore
pd.set_option("display.expand_frame_repr", False)

log = logging.getLogger("main.strategy_dt_ta")


class Signal:
    def __init__(self, ava, settings: dict, strategy_names: list) -> None:
        self.ava = ava
        self.settings = settings

        self.strategy_names = strategy_names

        self.last_candle = None

    def get_instrument(self, signal: OrderType) -> dict:
        return {
            OrderType.BUY: Instrument.BULL
            if signal == OrderType.BUY
            else Instrument.BEAR,
            OrderType.SELL: Instrument.BEAR
            if signal == OrderType.BUY
            else Instrument.BULL,
        }

    def _get_last_signal_on_strategy(
        self, data: pd.DataFrame, strategy_logic: dict
    ) -> Optional[OrderType]:
        for index in reversed(data.index):
            time_index: datetime = index  # type: ignore
            if (
                time_index.hour < 10
                or (datetime.now() - time_index.replace(tzinfo=None)).seconds / 60 > 60
            ):
                continue

            row = data.loc[index]
            for signal in [OrderType.BUY, OrderType.SELL]:
                if not all([i(row) for i in strategy_logic[signal]]):
                    continue

                return signal

        return None

    def _get_signal_from_list(self, signals: list) -> Optional[OrderType]:
        count = {
            "buy": signals.count(OrderType.BUY),
            "sell": signals.count(OrderType.SELL),
        }

        if count["buy"] > count["sell"]:
            return OrderType.BUY

        if count["sell"] > count["buy"]:
            return OrderType.SELL

        for signal in signals:
            if signal is not None:
                return signal

        return None

    def get(self) -> Optional[OrderType]:
        history = self.ava.get_today_history(
            self.settings["instruments"]["MONITORING"]["AVA"]
        ).iloc[:-1]

        strategy = Strategy(history, strategies=self.strategy_names)

        # Case when I hit the same candle multiple times
        if self.last_candle is not None and self.last_candle.name == strategy.data.iloc[-1].name:  # type: ignore
            return None

        self.last_candle = strategy.data.iloc[-1]

        if (datetime.now() - self.last_candle.name.replace(tzinfo=None)).seconds > 122:  # type: ignore
            return None

        signals = [
            self._get_last_signal_on_strategy(strategy.data, strategy_logic)
            for strategy_logic in strategy.strategies.values()
        ]

        print("Signals: ", signals, " -> ", self._get_signal_from_list(signals))

        return self._get_signal_from_list(signals)


class Strategy:
    def __init__(self, data: pd.DataFrame, **kwargs):
        self.data = data.groupby(data.index).last().iloc[100:]

        self.data, self.conditions, columns_needed = self.prepare_conditions(data)

        self.drop_columns(columns_needed)

        if kwargs.get("strategies", []) != []:
            strategies_component_names = self.parse_strategies_names(
                kwargs["strategies"]
            )
        else:
            strategies_component_names = self.generate_strategies_names()

        self.strategies = self.generate_strategies(strategies_component_names)

    def prepare_conditions(
        self, data: pd.DataFrame
    ) -> Tuple[pd.DataFrame, dict, List[str]]:
        log.debug("Preparing conditions")

        _check_enough_data = (
            lambda column, data: True if column in data.columns else False
        )

        condition_types_list = (
            "Volatility",
            "Trend",
            "Candle",
            "Overlap",
            "Momentum",
            "Volume",
            "Cycles",
        )
        conditions: dict = {ct: {} for ct in condition_types_list}

        columns_needed = ["Open", "High", "Low", "Close", "Volume"]

        """ Cycles """
        # EBSW (Even Better Sinewave) # FIXED
        data.ta.ebsw(length=50, bars=15, append=True)
        if _check_enough_data("EBSW_50_15", data):
            conditions["Cycles"]["EBSW"] = {
                OrderType.BUY: lambda x: x["EBSW_50_15"] > 0.5,
                OrderType.SELL: lambda x: x["EBSW_50_15"] < -0.5,
            }
            columns_needed += ["EBSW_50_15"]

        """ Volume """
        # PVT (Price Volume Trend) # FIXED
        data.ta.pvt(append=True)
        if _check_enough_data("PVT", data):
            data.ta.ema(close="PVT", length=9, append=True)
            conditions["Volume"]["PVT"] = {
                OrderType.BUY: lambda x: x["EMA_9"] < x["PVT"],
                OrderType.SELL: lambda x: x["EMA_9"] > x["PVT"],
            }
            columns_needed += ["EMA_9", "PVT"]

        # CMF (Chaikin Money Flow) # FIXED
        data.ta.cmf(append=True)
        if _check_enough_data("CMF_20", data):
            cmf = {"max": data["CMF_20"].max(), "min": data["CMF_20"].min()}
            conditions["Volume"]["CMF"] = {
                OrderType.BUY: lambda x: x["CMF_20"] > cmf["max"] * 0.2,
                OrderType.SELL: lambda x: x["CMF_20"] < cmf["min"] * 0.2,
            }
            columns_needed += ["CMF_20"]

        # ADOSC (Accumulation/Distribution Oscillator) # FIXED
        data["ADOSC_direction"] = (
            data.ta.adosc(fast=30, slow=45)
            .rolling(2)
            .apply(lambda x: x.iloc[1] > x.iloc[0])
        )
        if _check_enough_data("ADOSC_direction", data):
            conditions["Volume"]["ADOSC"] = {
                OrderType.BUY: lambda x: x["ADOSC_direction"] == 1,
                OrderType.SELL: lambda x: x["ADOSC_direction"] == 0,
            }
            columns_needed += ["ADOSC_direction"]

        """ Volatility """
        # MASSI (Mass Index) # FIXED
        data.ta.massi(fast=12, slow=30, append=True)
        if _check_enough_data("MASSI_12_30", data):
            conditions["Volatility"]["MASSI"] = {
                OrderType.BUY: lambda x: 26 < x["MASSI_12_30"] < 27,
                OrderType.SELL: lambda x: 26 < x["MASSI_12_30"] < 27,
            }
            columns_needed += ["MASSI_12_30"]

        # HWC (Holt-Winter Channel) # FIXED
        data.ta.hwc(append=True)
        if _check_enough_data("HWM", data):
            conditions["Volatility"]["HWC"] = {
                OrderType.BUY: lambda x: x["Close"] > x["HWM"],
                OrderType.SELL: lambda x: x["Close"] < x["HWM"],
            }
            columns_needed += ["HWM"]

        # BBANDS (Bollinger Bands) # FIXED
        data.ta.bbands(length=20, std=2, append=True)
        if _check_enough_data("BBL_20_2.0", data):
            conditions["Volatility"]["BBANDS"] = {
                OrderType.BUY: lambda x: x["Close"] > x["BBL_20_2.0"],
                OrderType.SELL: lambda x: x["Close"] < x["BBU_20_2.0"],
            }
            columns_needed += ["BBL_20_2.0", "BBU_20_2.0"]

        # RVI (Relative Volatility Index)
        data.ta.rvi(length=30, append=True)
        if _check_enough_data("RVI_30", data):
            conditions["Volatility"]["RVI"] = {
                OrderType.BUY: lambda x: x["RVI_30"] > 50,
                OrderType.SELL: lambda x: x["RVI_30"] < 50,
            }
            columns_needed += ["RVI_30"]

        """ Trend """
        # Trend direction (2DEMA) # FIXED
        data.ta.dema(length=15, append=True)
        data.ta.dema(length=30, append=True)
        data["2DEMA"] = data.apply(
            lambda x: 1 if x["DEMA_15"] >= x["DEMA_30"] else -1,
            axis=1,
        )
        if _check_enough_data("2DEMA", data):
            conditions["Trend"]["2DEMA"] = {
                OrderType.BUY: lambda x: x["2DEMA"] == 1,
                OrderType.SELL: lambda x: x["2DEMA"] == -1,
            }
            columns_needed += ["2DEMA"]

        # PSAR (Parabolic Stop and Reverse) # FIXED
        data.ta.psar(af=0.1, max_af=0.25, append=True)
        if _check_enough_data("PSARl_0.1_0.25", data):
            conditions["Trend"]["PSAR"] = {
                OrderType.BUY: lambda x: x["Close"] > x["PSARl_0.1_0.25"],
                OrderType.SELL: lambda x: x["Close"] < x["PSARs_0.1_0.25"],
            }
            columns_needed += ["PSARl_0.1_0.25", "PSARs_0.1_0.25"]

        """ Overlap """
        # ALMA (Arnaud Legoux Moving Average)
        data.ta.alma(length=16, sigma=6.0, distribution_offset=0.85, append=True)
        if _check_enough_data("ALMA_18_6.0_0.85", data):
            conditions["Overlap"]["ALMA"] = {
                OrderType.BUY: lambda x: x["Close"] > x["ALMA_18_6.0_0.85"],
                OrderType.SELL: lambda x: x["Close"] < x["ALMA_18_6.0_0.85"],
            }
            columns_needed += ["ALMA_18_6.0_0.85"]

        # GHLA (Gann High-Low Activator) # FIXED
        data.ta.hilo(high_length=11, low_length=18, append=True)
        if _check_enough_data("HILO_11_18", data):
            conditions["Overlap"]["GHLA"] = {
                OrderType.BUY: lambda x: x["Close"] > x["HILO_11_18"],
                OrderType.SELL: lambda x: x["Close"] < x["HILO_11_18"],
            }
            columns_needed += ["HILO_11_18"]

        # SUPERT (Supertrend) # FIXED
        data.ta.supertrend(length=14, multiplier=7, append=True)
        if _check_enough_data("SUPERT_14_7.0", data):
            conditions["Overlap"]["SUPERT"] = {
                OrderType.BUY: lambda x: x["Close"] > x["SUPERT_14_7.0"],
                OrderType.SELL: lambda x: x["Close"] < x["SUPERT_14_7.0"],
            }
            columns_needed += ["SUPERT_14_7.0"]

        # LINREG (Linear Regression) # FIXED
        data.ta.linreg(length=30, append=True, r=True)
        if _check_enough_data("LRr_30", data):
            data["LRr_direction"] = (
                data["LRr_30"].rolling(2).apply(lambda x: x.iloc[1] > x.iloc[0])
            )
            conditions["Overlap"]["LINREG"] = {
                OrderType.BUY: lambda x: x["LRr_direction"] == 1,
                OrderType.SELL: lambda x: x["LRr_direction"] == 0,
            }
            columns_needed += ["LRr_direction"]

        """ Momentum """
        # RSI (Relative Strength Index) # FIXED
        data.ta.rsi(length=20, append=True)
        if _check_enough_data("RSI_20", data):
            conditions["Momentum"]["RSI"] = {
                OrderType.BUY: lambda x: x["RSI_20"] < 30,
                OrderType.SELL: lambda x: x["RSI_20"] > 70,
            }
            columns_needed += ["RSI_20"]

        # STC (Schaff Trend Cycle) # FIXED
        data.ta.stc(tclength=12, fast=14, slow=28, factor=0.6, append=True)
        if _check_enough_data("STC_12_14_28_0.6", data):
            conditions["Momentum"]["STC"] = {
                OrderType.BUY: lambda x: x["STC_12_14_28_0.6"] < 75,
                OrderType.SELL: lambda x: x["STC_12_14_28_0.6"] > 25,
            }
            columns_needed += ["STC_12_14_28_0.6"]

        # UO (Ultimate Oscillator) # FIXED
        data.ta.uo(fast=10, medium=20, slow=40, append=True)
        if _check_enough_data("UO_10_20_40", data):
            conditions["Momentum"]["UO"] = {
                OrderType.BUY: lambda x: x["UO_10_20_40"] < 30,
                OrderType.SELL: lambda x: x["UO_10_20_40"] > 70,
            }
            columns_needed += ["UO_10_20_40"]

        # RVGI (Relative Vigor Index)
        data.ta.rvgi(append=True)
        if _check_enough_data("RVGI_14_4", data):
            conditions["Momentum"]["RVGI"] = {
                OrderType.BUY: lambda x: x["RVGI_14_4"] > x["RVGIs_14_4"],
                OrderType.SELL: lambda x: x["RVGI_14_4"] < x["RVGIs_14_4"],
            }
            columns_needed += ["RVGI_14_4", "RVGIs_14_4"]

        # MACD (Moving Average Convergence Divergence)
        data.ta.macd(fast=18, slow=52, signal=14, append=True)
        if _check_enough_data("MACD_18_52_14", data):
            data["MACD_ma_diff"] = (
                data["MACDh_18_52_14"].rolling(2).apply(lambda x: x.iloc[1] > x.iloc[0])
            )
            conditions["Momentum"]["MACD"] = {
                OrderType.BUY: lambda x: x["MACD_ma_diff"] == 1,
                OrderType.SELL: lambda x: x["MACD_ma_diff"] == 0,
            }
            columns_needed += ["MACD_ma_diff"]

        # BOP (Balance Of Power)
        data.ta.bop(append=True)
        if _check_enough_data("BOP", data):
            conditions["Momentum"]["BOP"] = {
                OrderType.BUY: lambda x: x["BOP"] < -0.25,
                OrderType.SELL: lambda x: x["BOP"] > 0.25,
            }
            columns_needed += ["BOP"]

        return data, conditions, columns_needed

    def drop_columns(self, columns_needed: list) -> None:
        columns_drop = list(set(self.data.columns) - (set(columns_needed)))

        self.data.drop(columns=columns_drop, inplace=True)

    def generate_strategies_names(self) -> list:
        # + Triple indicator strategies (try every combination of different types)

        log.debug("Generating strategies list")

        strategies_component_names = []
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

        strategies_component_names = []

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

            for order_type in OrderType:
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
