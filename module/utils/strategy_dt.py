"""
This module contains all candlesticks related functions
"""


from datetime import datetime
import os
import json
import logging
import warnings
import pandas as pd

from copy import copy
from typing import Tuple, Optional, Literal
from dataclasses import dataclass, field

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

        self.get_candlestick_patterns()

        self.ta_indicators = self.get_ta_indicators()

    def get_candlestick_patterns(self) -> None:
        self.data = pd.merge(
            left=self.data,
            right=self.data.ta.cdl_pattern(name="all"),
            left_index=True,
            right_index=True,
        )

        self.data.drop(columns=["CDL_LADDERBOTTOM"], inplace=True)

    def get_ta_indicators(self) -> dict:
        ta_indicators = dict()

        """ Volume """
        """
        # CMF (Chaikin Money Flow)
        self.data.ta.cmf(append=True)
        ta_indicators["CMF"] = {
            "buy": lambda x: x["CMF_20"] < 0,
            "sell": lambda x: x["CMF_20"] > 0,
            "columns": ["CMF_20"],
        }

        # EFI (Elder's Force Index)
        self.data.ta.efi(append=True)
        ta_indicators["EFI"] = {
            "buy": lambda x: x["EFI_13"] < 0,
            "sell": lambda x: x["EFI_13"] > 0,
            "columns": ["EFI_13"],
        }
        ta_indicators["EFI_R"] = {
            "buy": lambda x: x["EFI_13"] > 0,
            "sell": lambda x: x["EFI_13"] < 0,
            "columns": ["EFI_13"],
        }
        """

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
            "buy": lambda x: x["RVI_14"] < 50,
            "sell": lambda x: x["RVI_14"] > 50,
            "columns": ["RVI_14"],
        }

        """ Momentum """
        # STC (Schaff Trend Cycle)
        self.data.ta.stc(append=True)
        ta_indicators["STC"] = {
            "buy": lambda x: x["STC_10_12_26_0.5"] < 75,
            "sell": lambda x: x["STC_10_12_26_0.5"] > 25,
            "columns": ["STC_10_12_26_0.5"],
        }
        ta_indicators["STC_R"] = {
            "buy": lambda x: x["STC_10_12_26_0.5"] > 75,
            "sell": lambda x: x["STC_10_12_26_0.5"] < 25,
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

        # CCI (Commodity Channel Index)
        self.data.ta.cci(length=20, append=True, offset=1)
        self.data["CCI_20_0.015_lag"] = self.data["CCI_20_0.015"]
        self.data.ta.cci(length=20, append=True)
        ta_indicators["CCI"] = {
            "buy": lambda x: x["CCI_20_0.015"] < -100
            and x["CCI_20_0.015"] > x["CCI_20_0.015_lag"],
            "sell": lambda x: x["CCI_20_0.015"] > 100
            and x["CCI_20_0.015"] < x["CCI_20_0.015_lag"],
            "columns": ["CCI_20_0.015", "CCI_20_0.015_lag"],
        }

        # RSI (Relative Strength Index)
        self.data.ta.rsi(length=14, append=True)
        ta_indicators["RSI"] = {
            "buy": lambda x: x["RSI_14"] > 50,
            "sell": lambda x: x["RSI_14"] < 50,
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
