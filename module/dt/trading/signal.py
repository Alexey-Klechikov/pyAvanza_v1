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

        self.last_candle = None
        self.target_candle = None
        self.last_strategy = {
            "name": None,
            "logic": None,
        }

        self.signal: Optional[OrderType] = None

    def _get_signal_on_strategy(self, row: pd.Series) -> Optional[OrderType]:
        if self.last_strategy["logic"] is None:
            return None

        for signal in [OrderType.BUY, OrderType.SELL]:
            if not all([i(row) for i in self.last_strategy["logic"].get(signal)]):
                continue

            return signal

        return None

    def _get_last_signal_on_strategy(self, data: pd.DataFrame) -> Optional[OrderType]:
        signal = None

        if self.last_strategy["name"] is None:
            return None

        for i in range(1, 16):
            signal = self._get_signal_on_strategy(data.iloc[-i])

            if signal is None:
                continue

            self.target_candle = data.iloc[-i]
            break

        if (
            self.last_candle
            and self.target_candle
            and any(
                [
                    (
                        signal == OrderType.BUY
                        and self.last_candle["Close"] > self.target_candle["Close"]
                    ),
                    (
                        signal == OrderType.SELL
                        and self.last_candle["Close"] < self.target_candle["Close"]
                    ),
                ]
            )
        ):
            self.last_candle = self.target_candle

            return signal

        return None

    def get(self, strategy_names: list) -> Tuple[Optional[OrderType], list]:
        strategy = Strategy(
            self.ava.get_today_history(
                self.settings["instruments"]["MONITORING"]["AVA"]
            ).iloc[:-1],
            strategies=strategy_names,
        )

        self.target_candle = strategy.data.iloc[-1]

        message: list = []

        if self.last_candle and self.last_candle.name == self.target_candle.name:
            # if I hit the same candle multiple times
            return None, message

        if (datetime.now() - self.target_candle.name.replace(tzinfo=None)).seconds > 122:  # type: ignore
            # if last candle is too old
            return self.signal, message

        self.last_candle = self.target_candle

        if strategy_names[0] == self.last_strategy["name"]:
            self.signal = self._get_signal_on_strategy(self.last_candle)

        else:
            self.last_strategy = {
                "name": strategy_names[0],
                "logic": strategy.strategies[strategy_names[0]],
            }

            self.signal = self._get_last_signal_on_strategy(strategy.data)

        if self.signal and self.last_candle:
            message = [
                f"Signal: {self.signal.name}",
                f"Candle: {str(self.last_candle.name)[11:-9]}",
                f"OMX: {round(self.last_candle['Close'], 2)}",
                f"ATR: {round(self.last_candle['ATR'], 2)}",
                f"Strategy: {strategy_names[0]}",
            ]

        return self.signal, message

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

        if all([rsi_condition, price_condition, price_pullback_condition]):
            log.info(
                " | ".join(
                    ["Signal: Exit", f'RSI: {round(self.last_candle["RSI"], 2)}']
                )
            )

            return True

        return False
