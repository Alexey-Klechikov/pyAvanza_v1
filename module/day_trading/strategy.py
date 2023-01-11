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

from module.day_trading import Instrument
from module.day_trading.status import InstrumentStatus

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None  # type: ignore
pd.set_option("display.expand_frame_repr", False)

log = logging.getLogger("main.day_trading.strategy")


class Signal:
    def __init__(self, ava, settings: dict, strategy_names: list) -> None:
        self.ava = ava
        self.settings = settings

        self.strategy_names = strategy_names

        self.last_candle = None
        self.last_signal: Optional[OrderType] = None

    def _get_last_signal_on_strategy(
        self, row: pd.Series, strategy_logic: dict
    ) -> Optional[OrderType]:
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

        if OrderType.SELL in signals:
            return OrderType.SELL

        if OrderType.BUY in signals:
            return OrderType.BUY

        return None

    def _get_index_price_limits(self, signal: OrderType) -> str:
        if self.last_candle is None:
            return "N/A"

        atr_correction = self.last_candle["ATR"] / 20
        direction = 1 if signal == OrderType.BUY else -1

        reference_price = (
            (self.last_candle["Open"] + self.last_candle["Close"]) / 2
        ) * (1.00015 if signal == OrderType.BUY else 0.99985)

        price_stop_loss = reference_price * (
            1 - (1 - self.settings["trading"]["stop_loss"]) * atr_correction * direction
        )
        price_take_profit = reference_price * (
            1
            + (self.settings["trading"]["take_profit"] - 1) * atr_correction * direction
        )

        return " < ".join(
            [
                str(round(i, 2))
                for i in [price_stop_loss, reference_price, price_take_profit]
            ]
        )

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
            return self.last_signal

        signals = [
            self._get_last_signal_on_strategy(self.last_candle, strategy_logic)
            for strategy_logic in strategy.strategies.values()
        ]

        signal = self._get_signal_from_list(signals)

        if signal is not None and self.last_candle is not None:
            log.info(
                " | ".join(
                    [
                        f"Signal: {signal.name}",
                        f"Candle: {str(self.last_candle.name)[11:-9]}",
                        f"OMX: {self._get_index_price_limits(signal)}",
                        f"ATR: {round(self.last_candle['ATR'], 2)}",
                        "Strategies: ",
                    ]
                )
                + " & ".join(
                    [
                        str(i + 1) + ("" if s == signal else f" ({s.name})")
                        for i, s in enumerate(signals)
                        if s is not None
                    ]
                )
            )

        self.last_signal = signal

        return signal

    def exit(
        self,
        instrument: Instrument,
        instrument_status: InstrumentStatus,
    ) -> bool:
        if (
            self.last_candle is None
            or instrument_status.acquired_price is None
            or instrument_status.price_sell is None
        ):
            return False

        rsi_condition = (
            instrument == Instrument.BULL and self.last_candle["RSI"] < 50
        ) or (instrument == Instrument.BEAR and self.last_candle["RSI"] > 50)

        price_condition = (
            (instrument_status.price_sell - instrument_status.acquired_price)
            / instrument_status.acquired_price
        ) > (self.settings["trading"]["exit"] - 1)

        if rsi_condition and price_condition:
            log.info(
                " | ".join(
                    ["Signal: Exit", f'RSI: {round(self.last_candle["RSI"], 2)}']
                )
            )

            return True

        return False


class Strategy:
    def __init__(self, data: pd.DataFrame, **kwargs):
        self.data = data.groupby(data.index).last()

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

        # ATR (Average True Range) - used for SL/TP calculation
        data["ATR"] = data.ta.atr(length=14)
        columns_needed += ["ATR"]

        # RSI (Relative Strength Index) - used for the position exit
        data["RSI"] = data.ta.rsi(length=14)
        columns_needed += ["RSI"]

        """ Cycles """
        # EBSW (Even Better Sinewave)
        data.ta.ebsw(length=50, bars=15, append=True)
        if _check_enough_data("EBSW_50_15", data):
            conditions["Cycles"]["EBSW"] = {
                OrderType.BUY: lambda x: x["EBSW_50_15"] > 0.5,
                OrderType.SELL: lambda x: x["EBSW_50_15"] < -0.5,
            }
            columns_needed += ["EBSW_50_15"]

        """ Volume """
        # PVT (Price Volume Trend)
        data.ta.pvt(append=True)
        if _check_enough_data("PVT", data):
            data.ta.ema(close="PVT", length=14, append=True)
            conditions["Volume"]["PVT"] = {
                OrderType.BUY: lambda x: (x["Volume"] != 0)
                and (x["EMA_14"] < x["PVT"]),
                OrderType.SELL: lambda x: (x["Volume"] != 0)
                and (x["EMA_14"] > x["PVT"]),
            }
            columns_needed += ["EMA_14", "PVT"]

        # CMF (Chaikin Money Flow)
        data.ta.cmf(append=True)
        if _check_enough_data("CMF_20", data):
            cmf = {"max": data["CMF_20"].max(), "min": data["CMF_20"].min()}
            conditions["Volume"]["CMF"] = {
                OrderType.BUY: lambda x: (x["Volume"] != 0)
                and (x["CMF_20"] > cmf["max"] * 0.2),
                OrderType.SELL: lambda x: (x["Volume"] != 0)
                and (x["CMF_20"] < cmf["min"] * 0.2),
            }
            columns_needed += ["CMF_20"]

        # ADOSC (Accumulation/Distribution Oscillator)
        data["ADOSC_direction"] = (
            data.ta.adosc(fast=30, slow=45)
            .rolling(2)
            .apply(lambda x: x.iloc[1] > x.iloc[0])
        )
        if _check_enough_data("ADOSC_direction", data):
            conditions["Volume"]["ADOSC"] = {
                OrderType.BUY: lambda x: (x["Volume"] != 0)
                and (x["ADOSC_direction"] == 1),
                OrderType.SELL: lambda x: (x["Volume"] != 0)
                and (x["ADOSC_direction"] == 0),
            }
            columns_needed += ["ADOSC_direction"]

        """ Volatility """
        # DONCHAIN (Donchian Channel) ---
        data.ta.donchian(lower_length=15, upper_length=15, append=True)
        if _check_enough_data("DCM_15_15", data):
            conditions["Volatility"]["DONCHAIN"] = {
                OrderType.BUY: lambda x: x["Close"]
                > x["DCU_15_15"] - (x["DCU_15_15"] - x["DCM_15_15"]) * 0.4,
                OrderType.SELL: lambda x: x["Close"]
                < x["DCL_15_15"] + (x["DCM_15_15"] - x["DCL_15_15"]) * 0.6,
            }
            columns_needed += ["DCM_15_15", "DCL_15_15", "DCU_15_15"]

        # HWC (Holt-Winter Channel)
        data.ta.hwc(append=True)
        if _check_enough_data("HWM", data):
            conditions["Volatility"]["HWC"] = {
                OrderType.BUY: lambda x: x["Close"] > x["HWM"],
                OrderType.SELL: lambda x: x["Close"] < x["HWM"],
            }
            columns_needed += ["HWM"]

        # BBANDS (Bollinger Bands)
        data.ta.bbands(length=16, std=2, append=True)
        if _check_enough_data("BBL_16_2.0", data):
            conditions["Volatility"]["BBANDS"] = {
                OrderType.BUY: lambda x: x["Close"]
                > x["BBU_16_2.0"] - (x["BBU_16_2.0"] - x["BBM_16_2.0"]) * 0.4,
                OrderType.SELL: lambda x: x["Close"]
                < x["BBL_16_2.0"] + (x["BBM_16_2.0"] - x["BBL_16_2.0"]) * 0.6,
            }
            columns_needed += ["BBL_16_2.0", "BBU_16_2.0", "BBM_16_2.0"]

        # RVI (Relative Volatility Index)
        data.ta.rvi(length=20, append=True)
        if _check_enough_data("RVI_20", data):
            conditions["Volatility"]["RVI"] = {
                OrderType.BUY: lambda x: x["RVI_20"] > 60,
                OrderType.SELL: lambda x: x["RVI_20"] < 40,
            }
            columns_needed += ["RVI_20"]

        """ Trend """
        # ADX (Average Directional Movement Index)
        data.ta.adx(length=30, append=True)
        if _check_enough_data("ADX_30", data):
            conditions["Trend"]["ADX"] = {
                OrderType.BUY: lambda x: x["ADX_30"] > 20
                and x["DMP_30"] >= x["DMN_30"],
                OrderType.SELL: lambda x: x["ADX_30"] > 20
                and x["DMP_30"] <= x["DMN_30"],
            }
            columns_needed += ["ADX_30", "DMP_30", "DMN_30"]

        # PSAR (Parabolic Stop and Reverse)
        data.ta.psar(af=0.1, max_af=0.25, append=True)
        if _check_enough_data("PSARl_0.1_0.25", data):
            conditions["Trend"]["PSAR"] = {
                OrderType.BUY: lambda x: x["Close"] > x["PSARl_0.1_0.25"],
                OrderType.SELL: lambda x: x["Close"] < x["PSARs_0.1_0.25"],
            }
            columns_needed += ["PSARl_0.1_0.25", "PSARs_0.1_0.25"]

        # TTM_TREND (Trend based on TTM Squeeze)
        data.ta.ttm_trend(length=8, append=True)
        if _check_enough_data("TTM_TRND_8", data):
            conditions["Trend"]["TTM_TREND"] = {
                OrderType.BUY: lambda x: x["TTM_TRND_8"] == 1,
                OrderType.SELL: lambda x: x["TTM_TRND_8"] == -1,
            }
            columns_needed += ["TTM_TRND_8"]

        # VHF (Vertical Horizontal Filter)
        data["VHF_30"] = data.ta.ema(close=data.ta.vhf(length=30), length=10)
        if _check_enough_data("VHF_30", data):
            conditions["Trend"]["VHF"] = {
                OrderType.BUY: lambda x: x["VHF_30"] > 0.45,
                OrderType.SELL: lambda x: x["VHF_30"] > 0.45,
            }
            columns_needed += ["VHF_30"]

        # VORTEX (Vortex Indicator)
        data.ta.vortex(length=14, append=True)
        if _check_enough_data("VTXP_14", data):
            conditions["Trend"]["VORTEX"] = {
                OrderType.BUY: lambda x: x["VTXP_14"] > x["VTXM_14"],
                OrderType.SELL: lambda x: x["VTXM_14"] < x["VTXP_14"],
            }
            columns_needed += ["VTXP_14", "VTXM_14"]

        """ Overlap """
        # SUPERT (Supertrend)
        data.ta.supertrend(length=7, multiplier=4, append=True)
        if _check_enough_data("SUPERT_7_4.0", data):
            conditions["Overlap"]["SUPERT"] = {
                OrderType.BUY: lambda x: x["Close"] > x["SUPERT_7_4.0"],
                OrderType.SELL: lambda x: x["Close"] < x["SUPERT_7_4.0"],
            }
            columns_needed += ["SUPERT_7_4.0"]

        # EMA (Trend direction by 100 EMA)
        data["EMA"] = data.ta.ema(length=min(len(data) - 1, 100))
        if _check_enough_data("EMA", data):
            conditions["Trend"]["EMA"] = {
                OrderType.BUY: lambda x: x["Close"] > x["EMA"],
                OrderType.SELL: lambda x: x["Close"] < x["EMA"],
            }
            columns_needed += ["EMA"]

        # 2DEMA (Trend direction by Double EMA)
        data.ta.dema(length=15, append=True)
        data.ta.dema(length=30, append=True)
        data["2DEMA"] = data.apply(
            lambda x: 1 if x["DEMA_15"] >= x["DEMA_30"] else -1,
            axis=1,
        )
        if _check_enough_data("2DEMA", data):
            conditions["Overlap"]["2DEMA"] = {
                OrderType.BUY: lambda x: x["2DEMA"] == 1,
                OrderType.SELL: lambda x: x["2DEMA"] == -1,
            }
            columns_needed += ["2DEMA"]

        """ Momentum """
        # STC (Schaff Trend Cycle)
        data.ta.stc(tclength=10, fast=20, slow=35, factor=0.65, append=True)
        if _check_enough_data("STC_10_20_35_0.65", data):
            conditions["Momentum"]["STC"] = {
                OrderType.BUY: lambda x: x["STC_10_20_35_0.65"] < 70,
                OrderType.SELL: lambda x: x["STC_10_20_35_0.65"] > 30,
            }
            columns_needed += ["STC_10_20_35_0.65"]

        # UO (Ultimate Oscillator)
        data.ta.uo(fast=10, medium=15, slow=30, append=True)
        if _check_enough_data("UO_10_15_30", data):
            conditions["Momentum"]["UO"] = {
                OrderType.BUY: lambda x: x["UO_10_15_30"] < 30,
                OrderType.SELL: lambda x: x["UO_10_15_30"] > 70,
            }
            columns_needed += ["UO_10_15_30"]

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

        return data, conditions, columns_needed

    def drop_columns(self, columns_needed: list) -> None:
        columns_drop = list(set(self.data.columns) - (set(columns_needed)))

        self.data.drop(columns=columns_drop, inplace=True)

    def generate_strategies_names(self) -> list:
        # + Triple indicator strategies (try every combination of different types)

        log.debug("Generating strategies list")

        strategies_component_names = []
        indicators_names = []
        fine_tested_strategies: list = []  # This is used for tests

        for indicator_type, indicators_dict in self.conditions.items():
            indicators_names += [
                (indicator_type, indicator) for indicator in indicators_dict.keys()
            ]

        for i_1, indicator_1 in enumerate(indicators_names):
            temp_indicators_names = indicators_names[i_1:]

            for i_2, indicator_2 in enumerate(temp_indicators_names):
                if indicator_1[0] == indicator_2[0]:
                    continue

                for indicator_3 in temp_indicators_names[i_2:]:
                    if indicator_2[0] == indicator_3[0]:
                        continue

                    if fine_tested_strategies and not any(
                        [
                            i[1].split("_")[0] in fine_tested_strategies
                            for i in [indicator_1, indicator_2, indicator_3]
                        ]
                    ):
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
