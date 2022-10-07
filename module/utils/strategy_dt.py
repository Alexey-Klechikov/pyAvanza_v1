"""
This module contains all candlesticks related functions
"""


import json
import logging
import os
import warnings
from pprint import pprint
from typing import Tuple

import pandas as pd

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None  # type: ignore
pd.set_option("display.max_rows", 0)
pd.set_option("display.expand_frame_repr", False)

log = logging.getLogger("main.utils.strategy_dt")


class Strategy_DT:
    def __init__(self, data: pd.DataFrame, **kwargs):
        self.data = data.groupby(data.index).last()

        self.order_price_limits = {
            k: abs(round((1 - v) / 20, 5))
            for k, v in kwargs.get("order_price_limits", dict()).items()
        }

        if not kwargs.get("iterate_candlestick_patterns"):
            self.get_all_candlestick_patterns()

        columns = {"before": list(self.data.columns)}

        self.ta_indicators = self.get_ta_indicators()

        self.drop_columns(columns)

    def drop_columns(self, columns: dict) -> None:
        columns["needed"] = list()

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
        ta_indicators = dict()

        """ Volume """
        if "Volume" in self.data.columns:
            # CMF (Chaikin Money Flow)
            self.data.ta.cmf(append=True)
            cmf = {"max": self.data["CMF_20"].max(), "min": self.data["CMF_20"].min()}
            ta_indicators["CMF"] = {
                "buy": lambda x: x["CMF_20"] > cmf["max"] * 0.2,
                "sell": lambda x: x["CMF_20"] < cmf["min"] * 0.2,
                "columns": ["CMF_20"],
            }

            # EFI (Elder's Force Index)
            self.data.ta.efi(append=True)
            ta_indicators["EFI"] = {
                "buy": lambda x: x["EFI_13"] < 0,
                "sell": lambda x: x["EFI_13"] > 0,
                "columns": ["EFI_13"],
            }

        else:
            for indicator in ["CMF", "EFI"]:
                ta_indicators[indicator] = {
                    "buy": lambda x: False,
                    "sell": lambda x: False,
                    "columns": [],
                }

        """ Trend """
        # PSAR (Parabolic Stop and Reverse) ???
        self.data.ta.psar(append=True)
        ta_indicators["PSAR"] = {
            "buy": lambda x: x["Close"] > x["PSARl_0.02_0.2"],
            "sell": lambda x: x["Close"] < x["PSARs_0.02_0.2"],
            "columns": ["PSARl_0.02_0.2", "PSARs_0.02_0.2"],
        }

        """ Overlap """
        # ALMA (Arnaud Legoux Moving Average)
        self.data.ta.alma(length=15, append=True)
        ta_indicators["ALMA"] = {
            "buy": lambda x: x["Close"] > x["ALMA_15_6.0_0.85"],
            "sell": lambda x: x["Close"] < x["ALMA_15_6.0_0.85"],
            "columns": ["ALMA_15_6.0_0.85"],
        }

        # GHLA (Gann High-Low Activator)
        self.data.ta.hilo(append=True)
        ta_indicators["GHLA"] = {
            "buy": lambda x: x["Close"] > x["HILO_13_21"],
            "sell": lambda x: x["Close"] < x["HILO_13_21"],
            "columns": ["HILO_13_21"],
        }

        # SUPERT (Supertrend)
        self.data.ta.supertrend(append=True)
        ta_indicators["SUPERT"] = {
            "buy": lambda x: x["Close"] > x["SUPERT_7_3.0"],
            "sell": lambda x: x["Close"] < x["SUPERT_7_3.0"],
            "columns": ["SUPERT_7_3.0"],
        }

        # LINREG (Linear Regression) ???
        self.data.ta.linreg(append=True, r=True)
        self.data["LRr_direction"] = (
            self.data["LRr_14"].rolling(2).apply(lambda x: x.iloc[1] > x.iloc[0])
        )
        ta_indicators["LINREG"] = {
            "buy": lambda x: x["LRr_direction"] == 1,
            "sell": lambda x: x["LRr_direction"] == 0,
            "columns": ["LRr_direction"],
        }

        """ Volatility """
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
            "buy": lambda x: x["RVI_14"] > 50,
            "sell": lambda x: x["RVI_14"] < 50,
            "columns": ["RVI_14"],
        }

        """ Momentum """
        # MACD (Moving Average Convergence Divergence)
        self.data.ta.macd(fast=8, slow=21, signal=5, append=True)
        self.data["MACD_ma_diff"] = (
            self.data["MACDh_8_21_5"].rolling(2).apply(lambda x: x.iloc[1] > x.iloc[0])
        )
        ta_indicators["MACD"] = {
            "buy": lambda x: x["MACD_ma_diff"] == 1,
            "sell": lambda x: x["MACD_ma_diff"] == 0,
            "columns": ["MACD_ma_diff"],
        }

        # STC (Schaff Trend Cycle)
        self.data.ta.stc(append=True)
        ta_indicators["STC"] = {
            "buy": lambda x: x["STC_10_12_26_0.5"] < 75,
            "sell": lambda x: x["STC_10_12_26_0.5"] > 25,
            "columns": ["STC_10_12_26_0.5"],
        }

        # BOP (Balance Of Power)
        self.data.ta.bop(append=True)
        ta_indicators["BOP"] = {
            "buy": lambda x: x["BOP"] < -0.25,
            "sell": lambda x: x["BOP"] > 0.3,
            "columns": ["BOP"],
        }
        ta_indicators["BOP_R"] = {
            "buy": lambda x: x["BOP"] > 0,
            "sell": lambda x: x["BOP"] < 0,
            "columns": ["BOP"],
        }

        # RSI (Relative Strength Index)
        self.data.ta.rsi(length=14, append=True)
        ta_indicators["RSI"] = {
            "buy": lambda x: x["RSI_14"] > 50,
            "sell": lambda x: x["RSI_14"] < 50,
            "columns": ["RSI_14"],
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
