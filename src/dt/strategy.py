import json
import logging
import os
import warnings
from json import JSONDecodeError
from typing import List, Tuple

import pandas as pd
import pandas_ta as ta
from avanza import OrderType

from src.utils import CustomIndicators

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None  # type: ignore
pd.set_option("display.expand_frame_repr", False)

log = logging.getLogger("main.dt.strategy")

ADDITIONAL_FILENAME_SUFFIX = ""


class Components:
    def __init__(self, data: pd.DataFrame):
        self.conditions: dict = {}
        self.columns_needed = ["Open", "High", "Low", "Close", "Volume"]

        self.data = data.groupby(data.index).last()

        self.generate_conditions_overlap()
        self.generate_conditions_momentum()
        self.generate_conditions_volume()
        self.generate_conditions_cycles()
        self.generate_conditions_volatility()
        self.generate_conditions_trend()
        self.generate_conditions_extra()

        self.data = self.clean_up_data()

    def _generate_empty_condition(self, category: str, indicator: str) -> None:
        log.debug(f'Not enough data for "{category}" -> "{indicator}"')

        self.conditions[category][indicator] = {
            OrderType.BUY: lambda x: False,
            OrderType.SELL: lambda x: False,
        }

    def generate_conditions_extra(self) -> None:
        # ATR (Average True Range) - used for SL/TP calculation
        self.data["ATR"] = self.data.ta.atr(length=14)
        self.columns_needed += ["ATR"]

        # RSI (Relative Strength Index) - used for the position exit
        self.data["RSI"] = self.data.ta.rsi(length=14)
        self.columns_needed += ["RSI"]

        # MA ([Simple] Moving Averages) - used for strategy selection
        self.data["MA"] = self.data.ta.sma(length=90)
        self.columns_needed += ["MA"]

    def generate_conditions_cycles(self) -> None:
        category = "Cycles"
        self.conditions[category] = {}

        # EBSW (Even Better Sinewave)
        try:
            self.data.ta.ebsw(length=40, bars=15, append=True)
            self.conditions[category]["EBSW"] = {
                OrderType.BUY: lambda x: x["EBSW_40_15"] > 0.5,
                OrderType.SELL: lambda x: x["EBSW_40_15"] < -0.5,
            }
            self.columns_needed += ["EBSW_40_15"]

        except:
            self._generate_empty_condition(category, "EBSW")

    def generate_conditions_volume(self) -> None:
        category = "Volume"
        self.conditions[category] = {}

        # VFI (Volume Flow Index)
        try:
            self.data = CustomIndicators.volume_flow(self.data, 20, 3, 3, 0.2, 2.5)
            self.conditions[category]["VFI"] = {
                OrderType.BUY: lambda x: (x["Volume"] != 0)
                and x["VFI_MA_20_3_3_0.2_2.5"] > 0,
                OrderType.SELL: lambda x: (x["Volume"] != 0)
                and x["VFI_MA_20_3_3_0.2_2.5"] < 0,
            }
            self.columns_needed += ["VFI_MA_20_3_3_0.2_2.5"]

        except:
            self._generate_empty_condition(category, "VFI")

        # CMF (Chaikin Money Flow)
        try:
            self.data.ta.cmf(append=True)
            cmf = {"max": self.data["CMF_20"].max(), "min": self.data["CMF_20"].min()}
            self.conditions[category]["CMF"] = {
                OrderType.BUY: lambda x: (x["Volume"] != 0)
                and (x["CMF_20"] > cmf["max"] * 0.2),
                OrderType.SELL: lambda x: (x["Volume"] != 0)
                and (x["CMF_20"] < cmf["min"] * 0.2),
            }
            self.columns_needed += ["CMF_20"]

        except:
            self._generate_empty_condition(category, "CMF")

        # ADOSC (Accumulation/Distribution Oscillator)
        try:
            self.data["ADOSC_direction"] = (
                self.data.ta.adosc(fast=30, slow=45)
                .rolling(2)
                .apply(lambda x: x.iloc[1] > x.iloc[0])
            )
            self.conditions[category]["ADOSC"] = {
                OrderType.BUY: lambda x: (x["Volume"] != 0)
                and (x["ADOSC_direction"] == 1),
                OrderType.SELL: lambda x: (x["Volume"] != 0)
                and (x["ADOSC_direction"] == 0),
            }
            self.columns_needed += ["ADOSC_direction"]

        except:
            self._generate_empty_condition(category, "ADOSC")

    def generate_conditions_volatility(self) -> None:
        category = "Volatility"
        self.conditions[category] = {}

        # STARC (Stoller Average Range Channel)
        try:
            self.data = CustomIndicators.starc_bands(
                self.data, length_sma=6, length_atr=14, multiplier_atr=1.5
            )
            self.conditions[category]["STARC"] = {
                OrderType.BUY: lambda x: x["Close"] < x["STARC_B_6_14_1.5"],
                OrderType.SELL: lambda x: x["Close"] > x["STARC_U_6_14_1.5"],
            }
            self.columns_needed += ["STARC_U_6_14_1.5", "STARC_B_6_14_1.5"]

        except:
            self._generate_empty_condition(category, "STARC")

        # HWC (Holt-Winter Channel)
        try:
            self.data.ta.hwc(append=True)
            self.conditions[category]["HWC"] = {
                OrderType.BUY: lambda x: x["Close"] > x["HWM"],
                OrderType.SELL: lambda x: x["Close"] < x["HWM"],
            }
            self.columns_needed += ["HWM"]

        except:
            self._generate_empty_condition(category, "HWC")

        # RVI (Relative Volatility Index)
        try:
            self.data.ta.rvi(length=20, append=True)
            self.conditions[category]["RVI"] = {
                OrderType.BUY: lambda x: x["RVI_20"] > 60,
                OrderType.SELL: lambda x: x["RVI_20"] < 45,
            }
            self.columns_needed += ["RVI_20"]

        except:
            self._generate_empty_condition(category, "RVI")

    def generate_conditions_trend(self) -> None:
        category = "Trend"
        self.conditions[category] = {}

        # ADX (Average Directional Movement Index)
        try:
            self.data.ta.adx(length=30, append=True)
            self.conditions[category]["ADX"] = {
                OrderType.BUY: lambda x: x["ADX_30"] > 20
                and x["DMP_30"] >= x["DMN_30"],
                OrderType.SELL: lambda x: x["ADX_30"] > 20
                and x["DMP_30"] <= x["DMN_30"],
            }
            self.columns_needed += ["ADX_30", "DMP_30", "DMN_30"]

        except:
            self._generate_empty_condition(category, "ADX")

        # PSAR (Parabolic Stop and Reverse)
        try:
            self.data.ta.psar(af=0.1, max_af=0.25, append=True)
            self.conditions[category]["PSAR"] = {
                OrderType.BUY: lambda x: x["Close"] > x["PSARl_0.1_0.25"],
                OrderType.SELL: lambda x: x["Close"] < x["PSARs_0.1_0.25"],
            }
            self.columns_needed += ["PSARl_0.1_0.25", "PSARs_0.1_0.25"]

        except:
            self._generate_empty_condition(category, "PSAR")

        # TII (Trend Intensity Index)
        try:
            self.data = CustomIndicators.trend_intensity(
                self.data, length_sma=15, length_signal=5
            )
            self.conditions[category]["TII"] = {
                OrderType.BUY: lambda x: x["TII_SIGNAL_15_5"] > x["TII_15_5"],
                OrderType.SELL: lambda x: x["TII_SIGNAL_15_5"] < x["TII_15_5"],
            }
            self.columns_needed += ["TII_15_5", "TII_SIGNAL_15_5"]

        except:
            self._generate_empty_condition(category, "TII")

        # VHF (Vertical Horizontal Filter)
        try:
            self.data["VHF_30"] = self.data.ta.ema(
                close=self.data.ta.vhf(length=30), length=10
            )
            self.conditions[category]["VHF"] = {
                OrderType.BUY: lambda x: x["VHF_30"] > 0.45,
                OrderType.SELL: lambda x: x["VHF_30"] > 0.4,
            }
            self.columns_needed += ["VHF_30"]

        except:
            self._generate_empty_condition(category, "VHF")

        # VORTEX (Vortex Indicator)
        try:
            self.data.ta.vortex(length=14, append=True)
            self.conditions[category]["VORTEX"] = {
                OrderType.BUY: lambda x: x["VTXP_14"] > x["VTXM_14"],
                OrderType.SELL: lambda x: x["VTXM_14"] < x["VTXP_14"],
            }
            self.columns_needed += ["VTXP_14", "VTXM_14"]

        except:
            self._generate_empty_condition(category, "VORTEX")

    def generate_conditions_overlap(self) -> None:
        category = "Overlap"
        self.conditions[category] = {}

        # SUPERT (Supertrend)
        try:
            self.data.ta.supertrend(length=7, multiplier=4, append=True)
            self.conditions[category]["SUPERT"] = {
                OrderType.BUY: lambda x: x["Close"] > x["SUPERT_7_4.0"],
                OrderType.SELL: lambda x: x["Close"] < x["SUPERT_7_4.0"],
            }
            self.columns_needed += ["SUPERT_7_4.0"]

        except:
            self._generate_empty_condition(category, "SUPERT")

        # SMA (Trend direction by 100 SMA)
        try:
            self.data["SMA"] = self.data.ta.sma(length=min(len(self.data) - 1, 100))
            self.conditions[category]["SMA"] = {
                OrderType.BUY: lambda x: x["Close"] > x["SMA"],
                OrderType.SELL: lambda x: x["Close"] < x["SMA"],
            }
            self.columns_needed += ["SMA"]

        except:
            self._generate_empty_condition(category, "EMA")

        # 2DEMA (Trend direction by Double EMA)
        try:
            self.data.ta.dema(length=15, append=True)
            self.data.ta.dema(length=30, append=True)
            self.data["2DEMA"] = self.data.apply(
                lambda x: 1 if x["DEMA_15"] >= x["DEMA_30"] else -1,
                axis=1,
            )
            self.conditions[category]["2DEMA"] = {
                OrderType.BUY: lambda x: x["2DEMA"] == 1,
                OrderType.SELL: lambda x: x["2DEMA"] == -1,
            }
            self.columns_needed += ["2DEMA"]

        except:
            self._generate_empty_condition(category, "2DEMA")

    def generate_conditions_momentum(self) -> None:
        category = "Momentum"
        self.conditions[category] = {}

        # STC (Schaff Trend Cycle)
        try:
            self.data.ta.stc(tclength=10, fast=20, slow=35, factor=0.65, append=True)
            self.conditions[category]["STC"] = {
                OrderType.BUY: lambda x: x["STC_10_20_35_0.65"] < 70,
                OrderType.SELL: lambda x: x["STC_10_20_35_0.65"] > 25,
            }
            self.columns_needed += ["STC_10_20_35_0.65"]

        except:
            self._generate_empty_condition(category, "STC")

        # UO (Ultimate Oscillator)
        try:
            self.data.ta.uo(fast=10, medium=15, slow=30, append=True)
            self.conditions[category]["UO"] = {
                OrderType.BUY: lambda x: x["UO_10_15_30"] < 30,
                OrderType.SELL: lambda x: x["UO_10_15_30"] > 65,
            }
            self.columns_needed += ["UO_10_15_30"]

        except:
            self._generate_empty_condition(category, "UO")

        # MACD (Moving Average Convergence Divergence)
        try:
            self.data.ta.macd(fast=18, slow=52, signal=14, append=True)

            self.data["MACD_ma_diff"] = (
                self.data["MACDh_18_52_14"]
                .rolling(2)
                .apply(lambda x: x.iloc[1] > x.iloc[0])
            )
            self.conditions[category]["MACD"] = {
                OrderType.BUY: lambda x: x["MACD_ma_diff"] == 1,
                OrderType.SELL: lambda x: x["MACD_ma_diff"] == 0,
            }
            self.columns_needed += ["MACD_ma_diff"]

        except:
            self._generate_empty_condition(category, "MACD")

        # IMPULSE (Impulse MACD)
        try:
            self.data = CustomIndicators.impulse_macd(self.data, 36, 9)
            self.conditions["Momentum"]["IMPULSE"] = {
                OrderType.BUY: lambda x: x["IMPULSE_36_9"] > x["SIGNAL_36_9"] >= 0,
                OrderType.SELL: lambda x: x["IMPULSE_36_9"] < x["SIGNAL_36_9"] <= 0,
            }
            self.columns_needed += ["SIGNAL_36_9", "IMPULSE_36_9"]

        except:
            self._generate_empty_condition(category, "IMPULSE")

    def clean_up_data(self) -> pd.DataFrame:
        return self.data.drop(
            columns=list(set(self.data.columns) - (set(self.columns_needed))),
        )


class Strategy:
    def __init__(self, data: pd.DataFrame, **kwargs):
        self.indicators_test: list = []

        self.components = Components(data)
        self.data = self.components.data

        if kwargs.get("strategies", []) != []:
            strategies_component_names = self.parse_names(kwargs["strategies"])
        else:
            strategies_component_names = self.generate_names()

        self.strategies = self.generate_functions(strategies_component_names)

    def generate_names(self) -> list:
        """
        Triple indicator strategies (try every combination of different types)
        format: [[('Trend', 'CKSP'), ('Overlap', 'SUPERT'), ('Momentum', 'STOCH')], ...]
        """

        strategies_component_names = []
        indicators_names = []

        for category, indicators in self.components.conditions.items():
            indicators_names += [(category, indicator) for indicator in indicators]

        for i_1, indicator_1 in enumerate(indicators_names):
            temp_indicators_names = indicators_names[i_1:]

            for i_2, indicator_2 in enumerate(temp_indicators_names):
                if indicator_1[0] == indicator_2[0]:
                    continue

                strategies_component_names.append([indicator_1, indicator_2])

                for indicator_3 in temp_indicators_names[i_2:]:
                    if indicator_2[0] == indicator_3[0]:
                        continue

                    if self.indicators_test and not any(
                        [
                            i[1].split("_")[0] in self.indicators_test
                            for i in [indicator_1, indicator_2, indicator_3]
                        ]
                    ):
                        continue

                    strategies_component_names.append(
                        [indicator_1, indicator_2, indicator_3]
                    )

        return strategies_component_names

    def parse_names(self, strategies_names: List[str]) -> list:
        """
        before: ["(Trend) CKSP + (Overlap) SUPERT + (Momentum) STOCH", ...]
        after: [[('Trend', 'CKSP'), ('Overlap', 'SUPERT'), ('Momentum', 'STOCH')], ...]
        """
        return [
            [
                tuple(i.strip().replace("(", "").replace(")", "").split(" "))
                for i in s.split("+")
            ]
            for s in strategies_names
        ]

    def generate_functions(
        self, strategies_component_names: List[List[Tuple[str, str]]]
    ) -> dict:
        strategies = {}

        for strategy_components_names in strategies_component_names:
            strategies[
                " + ".join([f"({i[0]}) {i[1]}" for i in strategy_components_names])
            ] = {
                order_type: [
                    self.components.conditions[strategy_component_name[0]][
                        strategy_component_name[1]
                    ][order_type]
                    for strategy_component_name in strategy_components_names
                ]
                for order_type in OrderType
            }

        return strategies

    @staticmethod
    def load(filename_suffix: str) -> dict:
        log.debug(
            f"Loading strategies_{filename_suffix}{ADDITIONAL_FILENAME_SUFFIX}.json"
        )

        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        try:
            with open(
                f"{current_dir}/data/strategies_{filename_suffix}{ADDITIONAL_FILENAME_SUFFIX}.json",
                "r",
            ) as f:
                strategies = json.load(f)

        except (JSONDecodeError, TypeError):
            strategies = {}

        return strategies

    @staticmethod
    def dump(filename_suffix: str, strategies: dict):
        log.debug(f"Dump strategies_{filename_suffix}{ADDITIONAL_FILENAME_SUFFIX}.json")

        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        with open(
            f"{current_dir}/data/strategies_{filename_suffix}{ADDITIONAL_FILENAME_SUFFIX}.json",
            "w",
        ) as f:
            json.dump(strategies, f, indent=4)
