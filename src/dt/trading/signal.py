import logging
import warnings
from datetime import datetime
from typing import List, Optional, Tuple

import pandas as pd
import pandas_ta as ta
from avanza import OrderType

from src.dt import Strategy
from src.dt.common_types import Instrument
from src.dt.trading.status import InstrumentStatus

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
            "time": datetime.now(),
        }

    def _check_candle_is_valid(
        self, strategy_names: list
    ) -> Tuple[Optional[str], Strategy]:
        strategy = Strategy(
            self.ava.get_today_history(
                self.settings["instruments"]["MONITORING"]["AVA"]
            ).iloc[:-1],
            strategies=strategy_names,
        )

        skip_message = None

        if self.candle is not None and self.candle.name == strategy.data.iloc[-1].name:
            skip_message = "Duplicate candle hit"

        self.candle = strategy.data.iloc[-1]

        if len(strategy_names) == 0:
            skip_message = "No strategies"

        if (datetime.now() - self.candle.name.replace(tzinfo=None)).seconds > 122:  # type: ignore
            skip_message = "Candle is too old"

        return skip_message, strategy

    def _get_last_signal_on_strategy(
        self, strategy: Strategy, strategy_name: str
    ) -> Tuple[Optional[OrderType], Optional[datetime]]:
        for i in range(1, 24):
            candle = strategy.data.iloc[-i]

            for signal in [OrderType.BUY, OrderType.SELL]:
                if all(
                    [i(candle) for i in strategy.strategies[strategy_name].get(signal)]
                ):
                    return signal, candle.name  # type: ignore

            if candle.name.hour < 10:  # type: ignore
                break

        return None, None

    def _extract_signal_from_list(
        self, signals: list
    ) -> Tuple[OrderType, datetime, str]:
        latest_signal_time = max([s["time"] for s in signals])
        latest_signals = {
            "all": [s for s in signals if s["time"] == latest_signal_time]
        }

        [
            log.debug(f"> {s['signal'].value}: {s['strategy_name']}")  # type: ignore
            for s in latest_signals["all"]
        ]

        for signal in [OrderType.BUY, OrderType.SELL]:
            latest_signals[signal.name.lower()] = [
                s for s in latest_signals["all"] if s["signal"] == signal
            ]

        current_signal = latest_signals["all"][0]["signal"]
        if len(latest_signals["sell"]) != len(latest_signals["buy"]):
            current_signal = (
                OrderType.SELL
                if len(latest_signals["sell"]) > len(latest_signals["buy"])
                else OrderType.BUY
            )

        return (
            current_signal,
            latest_signal_time,
            " / ".join(
                [
                    f"{s}: {len(latest_signals[s.lower()])}"
                    for s in ["BUY", "SELL"]
                    if len(latest_signals[s.lower()]) > 0
                ]
            ),
        )

    def get(self, strategy_names: list) -> Tuple[Optional[OrderType], list]:
        skip_message, strategy = self._check_candle_is_valid(strategy_names)
        if skip_message:
            return None, [skip_message]

        signals: list = []
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

        (
            current_signal,
            latest_signal_time,
            signals_summary,
        ) = self._extract_signal_from_list(signals)

        if (
            self.last_signal["signal"] == current_signal
            and self.last_signal["time"] >= latest_signal_time
        ):
            log.debug(
                f"Outdated signal: {current_signal.name} at {latest_signal_time.strftime('%H:%M')}"
            )

            return None, ["Outdated signal"]

        self.last_signal = {"signal": current_signal, "time": latest_signal_time}  # type: ignore

        return current_signal, [
            f"Signal: {current_signal.name}",
            f"Candle: {str(latest_signal_time)[11:-9]}",
            f"OMX: {round(self.candle['Close'], 2)}",
            f"ATR: {round(self.candle['ATR'], 2)}",
            f"Counts: {signals_summary}",
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
