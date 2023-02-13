import json
import logging
import os
import warnings
from copy import copy
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Dict

import numpy as np
import pandas as pd
import pandas_ta as ta
from avanza import OrderType

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None  # type: ignore
pd.set_option("display.expand_frame_repr", False)

log = logging.getLogger("main.lt.strategy")


@dataclass
class StrategyInfo:
    transactions: list = field(default_factory=list)
    result: float = 0
    signal: OrderType = OrderType.SELL
    transactions_counter: int = 0


@dataclass
class MaxOutput:
    strategy: str = ""
    result: float = 0
    signal: OrderType = OrderType.SELL
    transactions_counter: int = 0


@dataclass
class Summary:
    ticker_name: str
    signal: OrderType = OrderType.SELL
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


class Components:
    def __init__(self, data: pd.DataFrame, skip_points: int) -> None:
        self.data = data

        self.conditions: dict = {
            "Blank": {
                "HOLD": {
                    OrderType.BUY: lambda x: True,
                    OrderType.SELL: lambda x: False,
                }
            }
        }

        self.columns_needed = ["Open", "High", "Low", "Close", "Volume"]

        self.generate_conditions_cycles()
        self.generate_conditions_volume()
        self.generate_conditions_volatility()
        self.generate_conditions_candle()
        self.generate_conditions_trend()
        self.generate_conditions_overlap()
        self.generate_conditions_momentum()

        self.data = self.clean_up_data(skip_points)

    def generate_conditions_cycles(self) -> None:
        self.conditions["Cycles"] = {}

        # EBSW (Even Better Sinewave)
        self.data.ta.ebsw(append=True)
        if "EBSW_40_10" in self.data.columns:
            self.conditions["Cycles"]["EBSW"] = {
                OrderType.BUY: lambda x: x["EBSW_40_10"] > 0.5,
                OrderType.SELL: lambda x: x["EBSW_40_10"] < -0.5,
            }
            self.columns_needed += ["EBSW_40_10"]

    def generate_conditions_volume(self) -> None:
        self.conditions["Volume"] = {}

        # PVT (Price Volume Trend)
        self.data.ta.pvt(append=True)
        if "PVT" in self.data.columns:
            self.data.ta.sma(close="PVT", length=9, append=True)
            self.conditions["Volume"]["PVT"] = {
                OrderType.BUY: lambda x: x["SMA_9"] < x["PVT"],
                OrderType.SELL: lambda x: x["SMA_9"] > x["PVT"],
            }
            self.columns_needed += ["SMA_9", "PVT"]

        # ADOSC (Accumulation/Distribution Oscillator)
        self.data["ADOSC_direction"] = (
            self.data.ta.adosc(fast=30, slow=45)
            .rolling(2)
            .apply(lambda x: x.iloc[1] > x.iloc[0])
        )
        if "ADOSC_direction" in self.data.columns:
            self.conditions["Volume"]["ADOSC"] = {
                OrderType.BUY: lambda x: x["ADOSC_direction"] == 1,
                OrderType.SELL: lambda x: x["ADOSC_direction"] == 0,
            }
            self.columns_needed += ["ADOSC_direction"]

        # CMF (Chaikin Money Flow)
        self.data.ta.cmf(append=True)
        if "CMF_20" in self.data.columns:
            cmf = {"max": self.data["CMF_20"].max(), "min": self.data["CMF_20"].min()}
            self.conditions["Volume"]["CMF"] = {
                OrderType.BUY: lambda x: x["CMF_20"] > cmf["max"] * 0.2,
                OrderType.SELL: lambda x: x["CMF_20"] < cmf["min"] * 0.2,
            }
            self.columns_needed += ["CMF_20"]

        # EFI (Elder's Force Index)
        self.data.ta.cmf(append=True)
        if "EFI_13" in self.data.columns:
            self.conditions["Volume"]["EFI"] = {
                OrderType.BUY: lambda x: x["EFI_13"] < 0,
                OrderType.SELL: lambda x: x["EFI_13"] > 0,
            }
            self.columns_needed += ["EFI_13"]

        # KVO (Klinger Volume Oscillator)
        try:
            self.data.ta.kvo(append=True)
            if "KVO_34_55_13" in self.data.columns:
                self.conditions["Volume"]["KVO"] = {
                    OrderType.BUY: lambda x: x["KVO_34_55_13"] > x["KVOs_34_55_13"],
                    OrderType.SELL: lambda x: x["KVO_34_55_13"] < x["KVOs_34_55_13"],
                }
                self.columns_needed += ["KVO_34_55_13", "KVOs_34_55_13"]

        except Exception as exc:
            log.warning(f"KVO not available: {exc}")

    def generate_conditions_volatility(self) -> None:
        self.conditions["Volatility"] = {}

        # MASSI (Mass Index)
        self.data.ta.massi(append=True)
        if "MASSI_9_25" in self.data.columns:
            self.conditions["Volatility"]["MASSI"] = {
                OrderType.BUY: lambda x: 26 < x["MASSI_9_25"] < 27,
                OrderType.SELL: lambda x: 26 < x["MASSI_9_25"] < 27,
            }
            self.columns_needed += ["MASSI_9_25"]

        # HWC (Holt-Winter Channel)
        self.data.ta.hwc(append=True)
        if "HWM" in self.data.columns:
            self.conditions["Volatility"]["HWC"] = {
                OrderType.BUY: lambda x: x["Close"] > x["HWM"],
                OrderType.SELL: lambda x: x["Close"] < x["HWM"],
            }
            self.columns_needed += ["HWM"]

        # BBANDS (Bollinger Bands)
        self.data.ta.bbands(length=20, std=2, append=True)
        if "BBL_20_2.0" in self.data.columns:
            self.conditions["Volatility"]["BBANDS"] = {
                OrderType.BUY: lambda x: x["Close"] > x["BBL_20_2.0"],
                OrderType.SELL: lambda x: x["Close"] < x["BBU_20_2.0"],
            }
            self.columns_needed += ["BBL_20_2.0", "BBU_20_2.0"]

        # ACCBANDS (Acceleration Bands)
        self.data.ta.accbands(append=True)
        if "ACCBU_20" in self.data.columns:
            self.conditions["Volatility"]["ACCBANDS"] = {
                OrderType.BUY: lambda x: x["Close"] > x["ACCBU_20"],
                OrderType.SELL: lambda x: x["Close"] < x["ACCBU_20"],
            }
            self.columns_needed += ["ACCBU_20"]

    def generate_conditions_candle(self) -> None:
        self.conditions["Candle"] = {}

        # HA (Heikin-Ashi)
        self.data.ta.ha(append=True)
        if "HA_open" in self.data.columns:
            self.conditions["Candle"]["HA"] = {
                OrderType.BUY: lambda x: (x["HA_open"] < x["HA_close"])
                and (x["HA_low"] == x["HA_open"]),
                OrderType.SELL: lambda x: (x["HA_open"] > x["HA_close"])
                and (x["HA_high"] == x["HA_open"]),
            }
            self.columns_needed += ["HA_open", "HA_close", "HA_low", "HA_high"]

    def generate_conditions_trend(self) -> None:
        self.conditions["Trend"] = {}

        # TTM_TREND (Trend based on TTM Squeeze)
        self.data.ta.ttm_trend(length=8, append=True)
        if "TTM_TRND_8" in self.data.columns:
            self.conditions["Trend"]["TTM_TREND"] = {
                OrderType.BUY: lambda x: x["TTM_TRND_8"] == 1,
                OrderType.SELL: lambda x: x["TTM_TRND_8"] == -1,
            }
            self.columns_needed += ["TTM_TRND_8"]

        # VHF (Vertical Horizontal Filter)
        self.data["VHF_30"] = self.data.ta.ema(
            close=self.data.ta.vhf(length=30), length=10
        )
        if "VHF_30" in self.data.columns:
            self.conditions["Trend"]["VHF"] = {
                OrderType.BUY: lambda x: x["VHF_30"] > 0.45,
                OrderType.SELL: lambda x: x["VHF_30"] > 0.4,
            }
            self.columns_needed += ["VHF_30"]

        # VORTEX (Vortex Indicator)
        self.data.ta.vortex(length=14, append=True)
        if "VTXP_14" in self.data.columns:
            self.conditions["Trend"]["VORTEX"] = {
                OrderType.BUY: lambda x: x["VTXP_14"] > x["VTXM_14"],
                OrderType.SELL: lambda x: x["VTXM_14"] < x["VTXP_14"],
            }
            self.columns_needed += ["VTXP_14", "VTXM_14"]

        # PSAR (Parabolic Stop and Reverse)
        self.data.ta.psar(append=True)
        if "PSARl_0.02_0.2" in self.data.columns:
            self.conditions["Trend"]["PSAR"] = {
                OrderType.BUY: lambda x: x["Close"] > x["PSARl_0.02_0.2"],
                OrderType.SELL: lambda x: x["Close"] < x["PSARs_0.02_0.2"],
            }
            self.columns_needed += ["PSARl_0.02_0.2", "PSARs_0.02_0.2"]

        # CHOP (Choppiness Index)
        self.data.ta.chop(append=True)
        if "CHOP_14_1_100" in self.data.columns:
            self.conditions["Trend"]["CHOP"] = {
                OrderType.BUY: lambda x: x["CHOP_14_1_100"] < 61.8,
                OrderType.SELL: lambda x: x["CHOP_14_1_100"] > 61.8,
            }
            self.columns_needed += ["CHOP_14_1_100"]

        # CKSP (Chande Kroll Stop)
        self.data.ta.cksp(append=True)
        if "CKSPl_10_3_20" in self.data.columns:
            self.conditions["Trend"]["CKSP"] = {
                OrderType.BUY: lambda x: x["CKSPl_10_3_20"] > x["CKSPs_10_3_20"],
                OrderType.SELL: lambda x: x["CKSPl_10_3_20"] < x["CKSPs_10_3_20"],
            }
            self.columns_needed += ["CKSPl_10_3_20", "CKSPs_10_3_20"]

    def generate_conditions_overlap(self) -> None:
        self.conditions["Overlap"] = {}

        # 2DEMA (Trend direction by Double EMA)
        self.data.ta.dema(length=15, append=True)
        self.data.ta.dema(length=30, append=True)
        self.data["2DEMA"] = self.data.apply(
            lambda x: 1 if x["DEMA_15"] >= x["DEMA_30"] else -1,
            axis=1,
        )
        if "2DEMA" in self.data.columns:
            self.conditions["Overlap"]["2DEMA"] = {
                OrderType.BUY: lambda x: x["2DEMA"] == 1,
                OrderType.SELL: lambda x: x["2DEMA"] == -1,
            }
            self.columns_needed += ["2DEMA"]

        # GHLA (Gann High-Low Activator)
        self.data.ta.hilo(append=True)
        if "HILO_13_21" in self.data.columns:
            self.conditions["Overlap"]["GHLA"] = {
                OrderType.BUY: lambda x: x["Close"] > x["HILO_13_21"],
                OrderType.SELL: lambda x: x["Close"] < x["HILO_13_21"],
            }
            self.columns_needed += ["HILO_13_21"]

        # SUPERT (Supertrend)
        self.data.ta.supertrend(append=True)
        if "SUPERT_7_3.0" in self.data.columns:
            self.conditions["Overlap"]["SUPERT"] = {
                OrderType.BUY: lambda x: x["Close"] > x["SUPERT_7_3.0"],
                OrderType.SELL: lambda x: x["Close"] < x["SUPERT_7_3.0"],
            }
            self.columns_needed += ["SUPERT_7_3.0"]

        # LINREG (Linear Regression)
        self.data.ta.linreg(append=True, r=True)
        if "LRr_14" in self.data.columns:
            self.data["LRr_direction"] = (
                self.data["LRr_14"].rolling(2).apply(lambda x: x.iloc[1] > x.iloc[0])
            )
            self.conditions["Overlap"]["LINREG"] = {
                OrderType.BUY: lambda x: x["LRr_direction"] == 1,
                OrderType.SELL: lambda x: x["LRr_direction"] == 0,
            }
            self.columns_needed += ["LRr_direction"]

    def generate_conditions_momentum(self) -> None:
        self.conditions["Momentum"] = {}

        # STC (Schaff Trend Cycle)
        self.data.ta.stc(append=True)
        if "STC_10_12_26_0.5" in self.data.columns:
            self.conditions["Momentum"]["STC"] = {
                OrderType.BUY: lambda x: x["STC_10_12_26_0.5"] < 75,
                OrderType.SELL: lambda x: x["STC_10_12_26_0.5"] > 25,
            }
            self.columns_needed += ["STC_10_12_26_0.5"]

        # UO (Ultimate Oscillator)
        self.data.ta.uo(fast=10, medium=15, slow=30, append=True)
        if "UO_10_15_30" in self.data.columns:
            self.conditions["Momentum"]["UO"] = {
                OrderType.BUY: lambda x: x["UO_10_15_30"] < 30,
                OrderType.SELL: lambda x: x["UO_10_15_30"] > 65,
            }
            self.columns_needed += ["UO_10_15_30"]

        # CCI (Commodity Channel Index)
        self.data.ta.cci(length=20, append=True, offset=1)
        if "CCI_20_0.015" in self.data.columns:
            self.data["CCI_direction"] = (
                self.data["CCI_20_0.015"]
                .rolling(2)
                .apply(lambda x: x.iloc[1] > x.iloc[0])
            )
            self.conditions["Overlap"]["LINREG"] = {
                OrderType.BUY: lambda x: x["CCI_20_0.015"] < -100
                and x["CCI_direction"] == 1,
                OrderType.SELL: lambda x: x["CCI_20_0.015"] > 100
                and x["CCI_direction"] == 0,
            }
            self.columns_needed += ["CCI_20_0.015", "CCI_direction"]

        # RVGI (Relative Vigor Index)
        self.data.ta.rvgi(append=True)
        if "RVGI_14_4" in self.data.columns:
            self.conditions["Momentum"]["RVGI"] = {
                OrderType.BUY: lambda x: x["RVGI_14_4"] > x["RVGIs_14_4"],
                OrderType.SELL: lambda x: x["RVGI_14_4"] < x["RVGIs_14_4"],
            }
            self.columns_needed += ["RVGI_14_4", "RVGIs_14_4"]

        # MACD (Moving Average Convergence Divergence)
        self.data.ta.macd(fast=8, slow=21, signal=5, append=True)
        if "MACD_8_21_5" in self.data.columns:
            self.data["MACD_ma_diff"] = (
                self.data["MACDh_8_21_5"]
                .rolling(2)
                .apply(lambda x: x.iloc[1] > x.iloc[0])
            )
            self.conditions["Momentum"]["MACD"] = {
                OrderType.BUY: lambda x: x["MACD_ma_diff"] == 1,
                OrderType.SELL: lambda x: x["MACD_ma_diff"] == 0,
            }
            self.columns_needed += ["MACD_ma_diff"]

        # STOCH (Stochastic Oscillator)
        self.data.ta.stoch(k=14, d=3, append=True)
        if "STOCHd_14_3_3" in self.data.columns:
            self.conditions["Momentum"]["STOCH"] = {
                OrderType.BUY: lambda x: x["STOCHd_14_3_3"] < 80
                and x["STOCHk_14_3_3"] < 80,
                OrderType.SELL: lambda x: x["STOCHd_14_3_3"] > 20
                and x["STOCHk_14_3_3"] > 20,
            }
            self.columns_needed += ["STOCHd_14_3_3", "STOCHk_14_3_3"]

    def clean_up_data(self, skip_points: int) -> pd.DataFrame:
        return self.data.iloc[skip_points:].drop(
            columns=list(set(self.data.columns) - (set(self.columns_needed))),
        )


class Strategy:
    def __init__(self, data: pd.DataFrame, **kwargs):
        self.components = Components(data, kwargs.get("skip_points", 100))
        self.data = self.components.data

        strategies = self.generate_functions(
            self.parse_names(kwargs["strategies"])
            if kwargs.get("strategies", []) != []
            else self.generate_names()
        )

        self.summary = self.get_signal(kwargs.get("ticker_name", False), strategies)

    def generate_names(self) -> list:
        """
        Triple indicator strategies (try every combination of different types)
        format: [[('Trend', 'CKSP'), ('Overlap', 'SUPERT'), ('Momentum', 'STOCH')], ...]
        """

        log.debug("Generating strategy names")

        strategies_component_names = [[("Blank", "HOLD")]]
        indicators_names = []

        for category, indicators in self.components.conditions.items():
            indicators_names += [
                (category, indicator) for indicator in indicators if indicator != "HOLD"
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

    def parse_names(self, strategies_names: list[str]) -> list:
        log.debug("Parsing strategy names")

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
        ] + [[("Blank", "HOLD")]]

    def generate_functions(
        self, strategies_component_names: list[list[tuple[str, str]]]
    ) -> dict:
        log.debug("Generating strategies functions")

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
                    map(lambda x: x(row), strategies[strategy][OrderType.SELL])
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
                    map(lambda x: x(row), strategies[strategy][OrderType.BUY])
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
                OrderType.SELL if np.isnan(balance.market) else OrderType.BUY
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
                OrderType.BUY
                if sorted_signals[:3].count(OrderType.BUY) >= 2
                else OrderType.SELL
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
