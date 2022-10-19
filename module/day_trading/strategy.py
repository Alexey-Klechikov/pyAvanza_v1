"""
This module contains all candlesticks related functions
"""


import json
import logging
import os
import warnings
from json import JSONDecodeError
from typing import Tuple

import pandas as pd
from avanza import OrderType as Signal

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None  # type: ignore
pd.set_option("display.max_rows", 0)
pd.set_option("display.expand_frame_repr", False)

log = logging.getLogger("main.utils.strategy_dt")


class StrategyDT:
    def __init__(self, data: pd.DataFrame, **kwargs):
        self.data = data.groupby(data.index).last()

        self.order_price_limits = {
            k: abs(round((1 - v) / 20, 5))
            for k, v in kwargs.get("order_price_limits", {}).items()
        }

        if not kwargs.get("iterate_candlestick_patterns"):
            self.get_all_candlestick_patterns()

        columns = {"before": list(self.data.columns)}

        self.ta_indicators = self.get_ta_indicators()

        self.drop_columns(columns)

    def drop_columns(self, columns: dict) -> None:
        columns["needed"] = []

        for ta_indicator in self.ta_indicators.values():
            columns["needed"] += ta_indicator["columns"]

        columns["drop"] = list(
            set(self.data.columns) - (set(columns["before"]) | set(columns["needed"]))
        )

        self.data.drop(columns=columns["drop"], inplace=True)

    def get_all_candlestick_patterns(self) -> None:
        self.data = pd.merge(
            left=self.data,
            right=self.data.ta.cdl_pattern(name="all"),
            left_index=True,
            right_index=True,
        )

    def get_one_candlestick_pattern(self, pattern: str) -> Tuple[pd.DataFrame, str]:
        data = pd.merge(
            left=self.data,
            right=self.data.ta.cdl_pattern(name=pattern),
            left_index=True,
            right_index=True,
        )

        column = list(data.columns)[-1]

        return data, column

    def get_ta_indicators(self) -> dict:
        ta_indicators = {}

        self.data.ta.ema(length=21, append=True)
        self.data.ta.ema(length=50, append=True)
        self.data["EMA_diff"] = self.data.apply(
            lambda x: 1 if x["EMA_21"] - x["EMA_50"] >= 0 else 0, axis=1
        )

        """ Volume """
        if "Volume" in self.data.columns:
            # CMF (Chaikin Money Flow)
            self.data.ta.cmf(append=True)
            cmf = {"max": self.data["CMF_20"].max(), "min": self.data["CMF_20"].min()}
            ta_indicators["CMF_EMA"] = {
                Signal.BUY: lambda x: x["CMF_20"] > cmf["max"] * 0.27
                and x["EMA_diff"] == 1,
                Signal.SELL: lambda x: x["CMF_20"] < cmf["min"] * 0.27
                and x["EMA_diff"] == 0,
                "columns": ["CMF_20", "EMA_diff"],
            }

            # EFI (Elder's Force Index)
            self.data.ta.efi(append=True)
            ta_indicators["EFI_EMA"] = {
                Signal.BUY: lambda x: x["EFI_13"] > 0 and x["EMA_diff"] == 1,
                Signal.SELL: lambda x: x["EFI_13"] < 0 and x["EMA_diff"] == 0,
                "columns": ["EFI_13", "EMA_diff"],
            }

        else:
            for indicator in ["CMF", "EFI"]:
                ta_indicators[indicator] = {
                    Signal.BUY: lambda x: False,
                    Signal.SELL: lambda x: False,
                    "columns": [],
                }

        """ Trend """
        # PSAR (Parabolic Stop and Reverse) (mod 2022.10.10)
        self.data.ta.psar(af=0.015, max_af=0.12, append=True)
        ta_indicators["PSAR_EMA"] = {
            Signal.BUY: lambda x: x["Close"] > x["PSARl_0.015_0.12"]
            and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["Close"] < x["PSARs_0.015_0.12"]
            and x["EMA_diff"] == 0,
            "columns": ["PSARl_0.015_0.12", "PSARs_0.015_0.12", "EMA_diff"],
        }

        """ Overlap """
        # ALMA (Arnaud Legoux Moving Average) (mod 2022.10.10)
        self.data.ta.alma(length=15, sigma=6.0, distribution_offset=0.85, append=True)
        ta_indicators["ALMA_EMA"] = {
            Signal.BUY: lambda x: x["Close"] > x["ALMA_15_6.0_0.85"]
            and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["Close"] < x["ALMA_15_6.0_0.85"]
            and x["EMA_diff"] == 0,
            "columns": ["ALMA_15_6.0_0.85", "EMA_diff"],
        }

        # GHLA (Gann High-Low Activator) (mod 2022.10.10)
        self.data.ta.hilo(high_length=11, low_length=20, append=True)
        self.data.ta.hilo(high_length=11, low_length=18, append=True)
        ta_indicators["GHLA_EMA"] = {
            Signal.BUY: lambda x: x["Close"] > x["HILO_11_20"] and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["Close"] < x["HILO_11_18"] and x["EMA_diff"] == 0,
            "columns": ["HILO_11_20", "HILO_11_18", "EMA_diff"],
        }

        # SUPERT (Supertrend) (mod 2022.10.09)
        self.data.ta.supertrend(length=7, multiplier=3, append=True)
        self.data.ta.supertrend(length=5, multiplier=3, append=True)
        ta_indicators["SUPERT_EMA"] = {
            Signal.BUY: lambda x: x["Close"] > x["SUPERT_5_3.0"] and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["Close"] < x["SUPERT_7_3.0"]
            and x["EMA_diff"] == 0,
            "columns": ["SUPERT_7_3.0", "SUPERT_5_3.0", "EMA_diff"],
        }

        # LINREG (Linear Regression) (mod 2022.10.10)
        self.data.ta.linreg(append=True, r=True)
        self.data["LRr_direction"] = (
            self.data["LRr_14"].rolling(2).apply(lambda x: x.iloc[1] > x.iloc[0])
        )
        ta_indicators["LINREG_EMA"] = {
            Signal.BUY: lambda x: x["LRr_direction"] == 1 and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["LRr_direction"] == 0 and x["EMA_diff"] == 0,
            "columns": ["LRr_direction", "EMA_diff"],
        }

        """ Volatility """
        # ACCBANDS (Acceleration Bands) (mod 2022.10.11)
        self.data.ta.accbands(length=10, append=True)
        self.data.ta.accbands(length=12, append=True)
        ta_indicators["ACCBANDS_EMA"] = {
            Signal.BUY: lambda x: x["Close"] > x["ACCBU_12"] and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["Close"] < x["ACCBL_10"] and x["EMA_diff"] == 0,
            "columns": ["ACCBU_12", "ACCBL_10", "EMA_diff"],
        }

        # KC (Keltner Channel) (mod 2022.10.11)
        self.data.ta.kc(length=14, scalar=2.3, append=True)
        ta_indicators["KC_EMA"] = {
            Signal.BUY: lambda x: x["Close"] > x["KCUe_14_2.3"] and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["Close"] < x["KCLe_14_2.3"] and x["EMA_diff"] == 0,
            "columns": ["KCLe_14_2.3", "KCUe_14_2.3", "EMA_diff"],
        }

        # RVI (Relative Volatility Index) (mod 2022.10.10)
        self.data.ta.rvi(length=14, append=True)
        ta_indicators["RVI_EMA"] = {
            Signal.BUY: lambda x: x["RVI_14"] > 50 and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["RVI_14"] < 45 and x["EMA_diff"] == 0,
            "columns": ["RVI_14", "EMA_diff"],
        }

        """ Momentum """
        # MACD (Moving Average Convergence Divergence) (mod 2022.10.10)
        self.data.ta.macd(fast=8, slow=21, signal=5, append=True)
        self.data["MACD_ma_diff"] = (
            self.data["MACDh_8_21_5"].rolling(2).apply(lambda x: x.iloc[1] > x.iloc[0])
        )
        ta_indicators["MACD_EMA"] = {
            Signal.BUY: lambda x: x["MACD_ma_diff"] == 1 and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["MACD_ma_diff"] == 0 and x["EMA_diff"] == 0,
            "columns": ["MACD_ma_diff", "EMA_diff"],
        }

        # STC (Schaff Trend Cycle) (mod 2022.10.10)
        self.data.ta.stc(tclength=12, fast=14, slow=28, factor=0.6, append=True)
        ta_indicators["STC_EMA"] = {
            Signal.BUY: lambda x: x["STC_12_14_28_0.6"] < 75 and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["STC_12_14_28_0.6"] > 25 and x["EMA_diff"] == 0,
            "columns": ["STC_12_14_28_0.6", "EMA_diff"],
        }

        # BOP (Balance Of Power)
        self.data.ta.bop(append=True)
        ta_indicators["BOP"] = {
            Signal.BUY: lambda x: x["BOP"] < -0.25,
            Signal.SELL: lambda x: x["BOP"] > 0.3,
            "columns": ["BOP"],
        }
        ta_indicators["BOP(R)_EMA"] = {
            Signal.BUY: lambda x: x["BOP"] > 0 and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["BOP"] < 0 and x["EMA_diff"] == 0,
            "columns": ["BOP", "EMA_diff"],
        }

        # RSI (Relative Strength Index) (mod 2022.10.10)
        self.data.ta.rsi(length=15, append=True)
        ta_indicators["RSI_EMA"] = {
            Signal.BUY: lambda x: x["RSI_15"] > 50 and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["RSI_15"] < 40 and x["EMA_diff"] == 0,
            "columns": ["RSI_15", "EMA_diff"],
        }

        # STOCH (Stochastic Oscillator) (mod 2022.10.10)
        self.data.ta.stoch(k=6, d=4, smooth_k=3, append=True)
        ta_indicators["STOCH_EMA"] = {
            Signal.BUY: lambda x: x["STOCHd_6_4_3"] > 20
            and x["STOCHk_6_4_3"] > 20
            and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["STOCHd_6_4_3"] < 80
            and x["STOCHk_6_4_3"] < 80
            and x["EMA_diff"] == 0,
            "columns": ["STOCHd_6_4_3", "STOCHk_6_4_3", "EMA_diff"],
        }

        # UO (Ultimate Oscillator) (mod 2022.10.09)
        self.data.ta.uo(fast=7, medium=14, slow=28, append=True)
        self.data.ta.uo(fast=9, medium=18, slow=36, append=True)
        ta_indicators["UO_EMA"] = {
            Signal.BUY: lambda x: x["UO_7_14_28"] < 30 and x["EMA_diff"] == 1,
            Signal.SELL: lambda x: x["UO_9_18_36"] > 70 and x["EMA_diff"] == 0,
            "columns": ["UO_7_14_28", "UO_9_18_36", "EMA_diff"],
        }

        return ta_indicators

    @staticmethod
    def load(filename_suffix: str) -> dict:
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
    def dump(filename_suffix: str, strategies: dict) -> None:
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(f"{current_dir}/data/strategies_{filename_suffix}.json", "w") as f:
            json.dump(strategies, f, indent=4)
