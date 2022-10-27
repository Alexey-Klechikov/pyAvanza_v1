"""
This module contains all candlesticks related functions
"""


import json
import logging
import os
import warnings
from json import JSONDecodeError
from typing import Tuple

import numpy as np
import pandas as pd
from avanza import OrderType as Signal

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None  # type: ignore
pd.set_option("display.max_rows", None)
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
        columns["needed"] = ["TREND"]

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

        self.data.ta.dema(length=20, append=True)
        for long_dema_len in range(40, 30, -1):
            self.data.ta.dema(length=long_dema_len, append=True)

            if np.isnan(self.data.iloc[-1][f"DEMA_{long_dema_len}"]):
                continue

            self.data["TREND"] = self.data.apply(
                lambda x: 1 if x["DEMA_20"] >= x[f"DEMA_{long_dema_len}"] else -1,
                axis=1,
            )

            break

        """ Volume """
        if "Volume" in self.data.columns:
            # CMF (Chaikin Money Flow)
            self.data.ta.cmf(length=20, append=True)
            ta_indicators["CMF"] = {
                Signal.BUY: lambda x: x["CMF_24"] > 0,
                Signal.SELL: lambda x: x["CMF_24"] < 0,
                "columns": ["CMF_24"],
            }

            # EFI (Elder's Force Index)
            self.data.ta.efi(length=15, mamode="dema", append=True)
            ta_indicators["EFI"] = {
                Signal.BUY: lambda x: x["EFI_15"] > 0,
                Signal.SELL: lambda x: x["EFI_15"] < 0,
                "columns": ["EFI_15"],
            }

            # ADOSC (Accumulation/Distribution Oscillator)
            self.data["ADOSC_direction"] = (
                self.data.ta.adosc(fast=2, slow=5)
                .rolling(2)
                .apply(lambda x: x.iloc[1] > x.iloc[0])
            )
            ta_indicators["ADOSC"] = {
                Signal.BUY: lambda x: x["ADOSC_direction"] == 1,
                Signal.SELL: lambda x: x["ADOSC_direction"] == 0,
                "columns": ["ADOSC_direction"],
            }

        else:
            for indicator in ["EFI", "ADOSC"]:
                ta_indicators[indicator] = {
                    Signal.BUY: lambda x: False,
                    Signal.SELL: lambda x: False,
                    "columns": [],
                }

        """ Trend """
        # PSAR (Parabolic Stop and Reverse)
        self.data.ta.psar(af=0.015, max_af=0.12, append=True)
        ta_indicators["PSAR"] = {
            Signal.BUY: lambda x: x["Close"] > x["PSARl_0.015_0.12"],
            Signal.SELL: lambda x: x["Close"] < x["PSARs_0.015_0.12"],
            "columns": ["PSARl_0.015_0.12", "PSARs_0.015_0.12"],
        }

        # AROON (Aroon Indicator)
        self.data.ta.aroon(length=12, append=True)
        ta_indicators["AROON"] = {
            Signal.BUY: lambda x: x["AROONOSC_12"] > 0,
            Signal.SELL: lambda x: x["AROONOSC_12"] < 0,
            "columns": ["AROONOSC_12"],
        }

        """ Overlap """
        # ALMA (Arnaud Legoux Moving Average)
        self.data.ta.alma(length=15, sigma=6.0, distribution_offset=0.85, append=True)
        ta_indicators["ALMA"] = {
            Signal.BUY: lambda x: x["Close"] > x["ALMA_15_6.0_0.85"],
            Signal.SELL: lambda x: x["Close"] < x["ALMA_15_6.0_0.85"],
            "columns": ["ALMA_15_6.0_0.85"],
        }

        # GHLA (Gann High-Low Activator)
        self.data.ta.hilo(high_length=11, low_length=20, append=True)
        self.data.ta.hilo(high_length=11, low_length=18, append=True)
        ta_indicators["GHLA"] = {
            Signal.BUY: lambda x: x["Close"] > x["HILO_11_20"],
            Signal.SELL: lambda x: x["Close"] < x["HILO_11_18"],
            "columns": ["HILO_11_20", "HILO_11_18"],
        }

        # SUPERT (Supertrend)
        self.data.ta.supertrend(length=7, multiplier=3, append=True)
        self.data.ta.supertrend(length=5, multiplier=3, append=True)
        ta_indicators["SUPERT"] = {
            Signal.BUY: lambda x: x["Close"] > x["SUPERT_5_3.0"],
            Signal.SELL: lambda x: x["Close"] < x["SUPERT_7_3.0"],
            "columns": ["SUPERT_7_3.0", "SUPERT_5_3.0"],
        }

        # LINREG (Linear Regression)
        self.data.ta.linreg(append=True, r=True)
        self.data["LRr_direction"] = (
            self.data["LRr_14"].rolling(2).apply(lambda x: x.iloc[1] > x.iloc[0])
        )
        ta_indicators["LINREG"] = {
            Signal.BUY: lambda x: x["LRr_direction"] == 1,
            Signal.SELL: lambda x: x["LRr_direction"] == 0,
            "columns": ["LRr_direction"],
        }

        """ Volatility """
        # ACCBANDS (Acceleration Bands)
        self.data.ta.accbands(length=10, append=True)
        self.data.ta.accbands(length=12, append=True)
        ta_indicators["ACCBANDS"] = {
            Signal.BUY: lambda x: x["Close"] > x["ACCBU_12"],
            Signal.SELL: lambda x: x["Close"] < x["ACCBL_10"],
            "columns": ["ACCBU_12", "ACCBL_10"],
        }

        # RVI (Relative Volatility Index)
        self.data.ta.rvi(length=14, append=True)
        ta_indicators["RVI"] = {
            Signal.BUY: lambda x: x["RVI_14"] > 50,
            Signal.SELL: lambda x: x["RVI_14"] < 50,
            "columns": ["RVI_14"],
        }

        """ Momentum """
        # STC (Schaff Trend Cycle)
        self.data.ta.stc(tclength=12, fast=14, slow=28, factor=0.6, append=True)
        ta_indicators["STC"] = {
            Signal.BUY: lambda x: x["STC_12_14_28_0.6"] < 75,
            Signal.SELL: lambda x: x["STC_12_14_28_0.6"] > 25,
            "columns": ["STC_12_14_28_0.6"],
        }

        # BOP (Balance Of Power)
        self.data.ta.bop(append=True)
        ta_indicators["BOP"] = {
            Signal.BUY: lambda x: x["BOP"] < -0.25,
            Signal.SELL: lambda x: x["BOP"] > 0.3,
            "columns": ["BOP"],
        }
        ta_indicators["BOP(R)"] = {
            Signal.BUY: lambda x: x["BOP"] > 0,
            Signal.SELL: lambda x: x["BOP"] < 0,
            "columns": ["BOP"],
        }

        # RSI (Relative Strength Index)
        self.data.ta.rsi(length=15, append=True)
        ta_indicators["RSI"] = {
            Signal.BUY: lambda x: x["RSI_15"] > 50,
            Signal.SELL: lambda x: x["RSI_15"] < 50,
            "columns": ["RSI_15"],
        }

        # STOCH (Stochastic Oscillator)
        self.data.ta.stoch(k=6, d=4, smooth_k=3, append=True)
        ta_indicators["STOCH"] = {
            Signal.BUY: lambda x: x["STOCHd_6_4_3"] > 20 and x["STOCHk_6_4_3"] > 20,
            Signal.SELL: lambda x: x["STOCHd_6_4_3"] < 80 and x["STOCHk_6_4_3"] < 80,
            "columns": ["STOCHd_6_4_3", "STOCHk_6_4_3"],
        }

        # UO (Ultimate Oscillator)
        self.data.ta.uo(fast=7, medium=14, slow=28, append=True)
        ta_indicators["UO"] = {
            Signal.BUY: lambda x: x["UO_7_14_28"] < 30,
            Signal.SELL: lambda x: x["UO_7_14_28"] > 70,
            "columns": ["UO_7_14_28"],
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
