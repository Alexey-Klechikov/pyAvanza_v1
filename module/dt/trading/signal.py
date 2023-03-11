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

        self.candle = pd.Series()
        self.last_signal = {
            "signal": None,
            "time": None,
        }

    def _get_last_signal_on_strategy(
        self, strategy: Strategy, strategy_name: str
    ) -> Tuple[Optional[OrderType], Optional[datetime]]:
        for i in range(1, 31):
            candle = strategy.data.iloc[-i]

            for signal in [OrderType.BUY, OrderType.SELL]:
                if all(
                    [i(candle) for i in strategy.strategies[strategy_name].get(signal)]
                ):
                    return signal, candle.name  # type: ignore

            if candle.name.hour < 10:  # type: ignore
                break

        return None, None

    def get(self, strategy_names: list) -> Tuple[Optional[OrderType], list]:
        if len(strategy_names) == 0:
            return None, ["No strategies"]

        strategy = Strategy(
            self.ava.get_today_history(
                self.settings["instruments"]["MONITORING"]["AVA"]
            ).iloc[:-1],
            strategies=strategy_names,
        )

        if self.candle is not None and self.candle.name == strategy.data.iloc[-1].name:
            return None, ["Duplicate candle hit"]

        self.candle = strategy.data.iloc[-1]

        if (datetime.now() - self.candle.name.replace(tzinfo=None)).seconds > 122:  # type: ignore
            return None, ["Candle is too old"]

        signals = []
        for strategy_name in strategy_names:
            (
                strategy_last_signal,
                strategy_last_signal_time,
            ) = self._get_last_signal_on_strategy(strategy, strategy_name)

            if strategy_last_signal:
                signals.append(
                    {
                        "signal": strategy_last_signal,
                        "time": strategy_last_signal_time,
                        "strategy_name": strategy_name,
                    }
                )

        if len(signals) == 0:
            return None, ["No signals"]

        current_signal = sorted(signals, key=lambda x: x["time"], reverse=True)[0]

        if (
            self.last_signal["signal"] == current_signal["signal"]
            and self.last_signal["time"] == current_signal["time"]
        ):
            return None, ["Duplicate signal hit"]

        self.last_signal = current_signal

        return current_signal["signal"], [
            f"Signal: {current_signal['signal'].name}",
            f"Candle: {str(current_signal['time'])[11:-9]}",
            f"OMX: {round(self.candle['Close'], 2)}",
            f"ATR: {round(self.candle['ATR'], 2)}",
            f"Strategy: {current_signal['strategy_name']}",
        ]

    def exit(
        self,
        instrument: Instrument,
        instrument_status: InstrumentStatus,
    ) -> bool:
        if (
            self.candle is None
            or instrument_status.acquired_price is None
            or instrument_status.price_sell is None
            or instrument_status.price_max is None
        ):
            return False

        rsi_condition = (instrument == Instrument.BULL and self.candle["RSI"] < 58) or (
            instrument == Instrument.BEAR and self.candle["RSI"] > 42
        )

        price_condition = (
            instrument_status.price_sell / instrument_status.acquired_price
            > self.settings["trading"]["exit"]
        )

        price_pullback_condition = (
            instrument_status.price_sell / instrument_status.price_max
            < self.settings["trading"]["pullback"]
        )

        return all([rsi_condition, price_condition, price_pullback_condition])
