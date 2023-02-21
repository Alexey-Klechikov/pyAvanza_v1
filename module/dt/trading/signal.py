import logging
import warnings
from datetime import datetime
from typing import List, Optional, Tuple

import pandas as pd
import pandas_ta as ta
from avanza import OrderType

from module.dt import Strategy
from module.dt.common_types import Instrument
from module.dt.trading.status import InstrumentStatus

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None  # type: ignore
pd.set_option("display.expand_frame_repr", False)

log = logging.getLogger("main.dt.trading.signal")


class Signal:
    def __init__(self, ava, settings: dict) -> None:
        self.ava = ava
        self.settings = settings

        self.strategy = {
            "name": None,
            "logic": None,
        }

        self.last_candle = None
        self.last_signal = {
            "signal": None,
            "time": None,
        }

    def _get_signal_on_strategy(self, row: pd.Series) -> Optional[OrderType]:
        if not self.strategy["logic"]:
            return None

        for signal in [OrderType.BUY, OrderType.SELL]:
            if not all([i(row) for i in self.strategy["logic"].get(signal)]):
                continue

            return signal

        return None

    def _get_last_signal_on_strategy(
        self, data: pd.DataFrame
    ) -> Tuple[Optional[OrderType], Optional[pd.Series]]:
        if not self.strategy["name"]:
            return None, None

        signal = None
        candle = None

        for i in range(1, 31):
            signal = self._get_signal_on_strategy(data.iloc[-i])

            if not signal:
                continue

            candle = data.iloc[-i]
            break

        if candle is not None and any(
            [
                (signal == OrderType.BUY and data.iloc[-1]["Close"] > candle["Close"]),
                (signal == OrderType.SELL and data.iloc[-1]["Close"] < candle["Close"]),
            ]
        ):
            return signal, candle

        return None, None

    def get(self, strategy_names: list) -> Tuple[Optional[OrderType], list]:
        strategy = Strategy(
            self.ava.get_today_history(
                self.settings["instruments"]["MONITORING"]["AVA"]
            ).iloc[:-1],
            strategies=strategy_names,
        )

        candle = strategy.data.iloc[-1]
        message: list = []

        if self.last_candle is not None and self.last_candle.name == candle.name:
            return None, ["Duplicate candle hit"]

        if (datetime.now() - candle.name.replace(tzinfo=None)).seconds > 122:  # type: ignore
            return None, ["Candle is too old"]

        if strategy_names[0] == self.strategy["name"]:
            # Same strategy as before
            signal = self._get_signal_on_strategy(candle)

            if signal:
                self.last_signal = {
                    "signal": signal,
                    "time": candle.name,
                }

        else:
            # Strategy has changed
            self.strategy = {
                "name": strategy_names[0],
                "logic": strategy.strategies[strategy_names[0]],
            }

            signal, candle = self._get_last_signal_on_strategy(strategy.data)

            if (
                self.last_signal["signal"] == signal
                and candle.name <= self.last_signal["time"]  # type: ignore
            ):
                # Signal on new strategy is the same, but older than the last one
                signal = None

        if signal and candle is not None:
            message = [
                f"Signal: {signal.name}",
                f"Candle: {str(candle.name)[11:-9]}",
                f"OMX: {round(candle['Close'], 2)}",
                f"ATR: {round(candle['ATR'], 2)}",
                f"Strategy: {strategy_names[0]}",
            ]

        self.last_candle = candle

        return signal, message

    def exit(
        self,
        instrument: Instrument,
        instrument_status: InstrumentStatus,
    ) -> bool:
        if (
            self.last_candle is None
            or instrument_status.acquired_price is None
            or instrument_status.price_sell is None
            or instrument_status.price_max is None
        ):
            return False

        rsi_condition = (
            instrument == Instrument.BULL and self.last_candle["RSI"] < 60
        ) or (instrument == Instrument.BEAR and self.last_candle["RSI"] > 40)

        price_condition = (
            instrument_status.price_sell / instrument_status.acquired_price
            > self.settings["trading"]["exit"]
        )

        price_pullback_condition = (
            instrument_status.price_sell / instrument_status.price_max
            < self.settings["trading"]["pullback"]
        )

        return all([rsi_condition, price_condition, price_pullback_condition])
