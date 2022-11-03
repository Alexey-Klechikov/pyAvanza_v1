import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple

import pandas as pd
from avanza import OrderType as Signal
from requests import ReadTimeout

from module.day_trading import DayTime, Instrument, InstrumentStatus
from module.day_trading import StatusDT as Status
from module.day_trading import StrategyDT
from module.utils import Context, History, Settings, TeleLog

log = logging.getLogger("main.day_trading")


@dataclass
class StdOutput:
    last_log_index: Optional[int] = None
    messages: list = field(default_factory=list)

    def update_in_console(self) -> None:
        new_last_log_index = log.parent.handlers[0].formatter.messages_counter  # type: ignore

        if self.last_log_index == new_last_log_index:
            LINE_UP = "\033[1A"
            LINE_CLEAR = "\x1b[2K"

            print(LINE_UP, end=LINE_CLEAR)

        print(f'[{datetime.now().strftime("%H:%M")}] {" ||| ".join(self.messages)}')

        self.last_log_index = new_last_log_index


class Helper:
    def __init__(self, user, accounts: dict, settings: dict):
        self.settings = settings

        self.trading_done = False
        self.accounts = accounts

        self.strategies = StrategyDT.load("DT")
        self.status = Status(self.settings["trading"])

        self.std_output: StdOutput = StdOutput()

        self.ava = Context(user, accounts, skip_lists=True)

        self._update_budget()

        self.log_data = {
            "balance_before": 0,
            "balance_after": 0,
            "number_errors": 0,
            "number_trades": 0,
            "budget": self.settings["trading"]["budget"],
        }

    def _check_last_candle_buy(
        self,
        strategy: StrategyDT,
        row: pd.Series,
        strategies: dict,
        instrument_type: Instrument,
    ) -> bool:
        def _get_trend_direction(row: pd.Series) -> Instrument:
            return Instrument.BULL if row["TREND"] == 1 else Instrument.BEAR

        def _get_signal_ta(row: pd.Series, indicator_ta: str) -> Optional[Instrument]:
            signal_ta = None

            if strategy.ta_indicators[indicator_ta][Signal.BUY](row):
                signal_ta = Instrument.BULL

            elif strategy.ta_indicators[indicator_ta][Signal.SELL](row):
                signal_ta = Instrument.BEAR

            return signal_ta

        def _get_signal_cs(
            row: pd.Series, patterns: list
        ) -> Tuple[Optional[Instrument], Optional[str]]:
            signal_cs, pattern_cs = None, None

            for pattern in patterns:
                if row[pattern] > 0:
                    signal_cs = Instrument.BULL
                elif row[pattern] < 0:
                    signal_cs = Instrument.BEAR

                if signal_cs is not None:
                    pattern_cs = pattern
                    break

            return signal_cs, pattern_cs

        if instrument_type != _get_trend_direction(row):
            return False

        indicator_ta, pattern_cs = None, None
        for indicator_ta in strategies:
            signal_ta = _get_signal_ta(row, indicator_ta)
            if signal_ta is None:
                continue

            signal_cs, pattern_cs = _get_signal_cs(
                row,
                strategies.get(indicator_ta, []),
            )
            if signal_cs is None:
                continue

            if signal_cs == signal_ta:
                log.warning(
                    f">>> ({round(row['Close'], 2)}) {instrument_type} - {indicator_ta}-{pattern_cs} at {str(row.name)[11:-9]}"
                )
                return True

        return False

    def _update_budget(self) -> None:
        own_capital = self.ava.get_portfolio().total_own_capital
        floating_budget = (own_capital // 500 - 1) * 500

        self.settings["trading"]["budget"] = max(
            floating_budget, self.settings["trading"]["budget"]
        )

    def get_signal_is_buy(self, strategies: dict, instrument_type: Instrument) -> bool:
        history = self.ava.get_today_history(
            self.settings["instruments"]["MONITORING"]["AVA"]
        )

        strategy = StrategyDT(
            history,
            order_price_limits=self.settings["trading"]["limits_percent"],
        )

        strategies = strategies if strategies else strategy.load("DT")

        last_full_candle_index = -2

        if (datetime.now() - strategy.data.iloc[last_full_candle_index].name.replace(tzinfo=None)).seconds > 122:  # type: ignore
            return False

        last_candle_signal_buy = self._check_last_candle_buy(
            strategy,
            strategy.data.iloc[last_full_candle_index],
            strategies[instrument_type],
            instrument_type,
        )

        return last_candle_signal_buy

    def update_instrument_status(self, instrument_type: Instrument) -> InstrumentStatus:
        instrument_id = str(self.settings["instruments"]["TRADING"][instrument_type])

        certificate_info = self.ava.get_certificate_info(instrument_id)

        active_order = self.ava.get_active_order(instrument_id)

        instrument_status = self.status.update_instrument(
            instrument_type, certificate_info, active_order
        )

        return instrument_status

    def place_order(
        self,
        signal: Signal,
        instrument_type: Instrument,
        instrument_status: InstrumentStatus,
    ) -> None:
        if (signal == Signal.BUY and instrument_status.has_position) or (
            signal == Signal.SELL and not instrument_status.has_position
        ):
            return

        if instrument_status.spread is None or instrument_status.spread > 0.65:
            log.error(
                f"{instrument_type} - (place_order) HIGH SPREAD: {instrument_status.spread}"
            )

            self.log_data["number_errors"] += 1

            return

        certificate_info = self.ava.get_certificate_info(
            self.settings["instruments"]["TRADING"][instrument_type],
        )

        order_data = {
            "name": instrument_type,
            "signal": signal,
            "account_id": list(self.accounts.values())[0],
            "order_book_id": self.settings["instruments"]["TRADING"][instrument_type],
            "max_return": 0,
        }

        if certificate_info[signal] is None:
            return

        if signal == Signal.BUY:
            self.log_data["number_trades"] += 1

            order_data.update(
                {
                    "price": certificate_info[signal],
                    "volume": int(
                        self.settings["trading"]["budget"] // certificate_info[signal]
                    ),
                    "budget": self.settings["trading"]["budget"],
                }
            )

        elif signal == Signal.SELL:
            price = (
                certificate_info[signal]
                if certificate_info[signal] < instrument_status.price_stop_loss
                else instrument_status.price_take_profit_super
            )

            if len(certificate_info["positions"]) == 0:
                return

            order_data.update(
                {
                    "price": price,
                    "volume": certificate_info["positions"][0]["volume"],
                    "profit": certificate_info["positions"][0]["profitPercent"],
                }
            )

        self.ava.create_orders(
            [order_data],
            signal,
        )

        log.info(
            f'{instrument_type} - (SET {signal.name.upper()} order): {order_data["price"]}'
        )

    def update_order(
        self,
        signal: Signal,
        instrument_type: Instrument,
        instrument_status: InstrumentStatus,
        price: Optional[float],
        enforce_sell_bool: bool = False,
    ) -> None:

        if price is None or instrument_status.spread is None:
            return

        if (
            instrument_status.spread > 0.65 and self.status.day_time != DayTime.EVENING
        ) or (instrument_status.spread > 3 and self.status.day_time == DayTime.EVENING):
            log.error(
                f"{instrument_type} - (update_order) HIGH SPREAD: {instrument_status.spread}"
            )

            self.log_data["number_errors"] += 1

            return

        instrument_type = instrument_status.active_order["orderbook"]["name"].split(
            " "
        )[0]

        log.info(
            f'{instrument_type} - (UPD {signal.name.upper()} order): {instrument_status.active_order["price"]} -> {price} {"(Enforce)" if enforce_sell_bool else ""}'
        )

        self.ava.update_order(instrument_status.active_order, price)

    def delete_order(self) -> None:
        self.ava.remove_active_orders(account_ids=[self.settings["accounts"]["DT"]])

    def add_std_output_message(self, instrument_type: str) -> None:
        instrument_status = getattr(self.status, instrument_type)

        if instrument_status.has_position:
            self.std_output.messages.append(
                f"{instrument_type} - {instrument_status.price_stop_loss} < {instrument_status.price_current} < {instrument_status.price_take_profit}"
            )


class Day_Trading:
    def __init__(self, user: str, accounts: dict, settings: dict):
        self.settings = settings

        self.helper = Helper(user, accounts, settings)

        while True:
            try:
                self.run_analysis(settings["log_to_telegram"])

                break

            except (ReadTimeout, ConnectionError):
                log.error("AVA Connection error, retrying in 5 seconds")
                self.helper.log_data["number_errors"] += 1

                self.helper.ava.ctx = self.helper.ava.get_ctx(user)

    def buy_instrument(self, instrument_type: Instrument) -> None:
        for _ in range(3):
            instrument_status = self.helper.update_instrument_status(instrument_type)

            if instrument_status.has_position:
                return

            elif instrument_status.active_order:
                instrument_price_buy = self.helper.ava.get_certificate_info(
                    self.settings["instruments"]["TRADING"][instrument_type]
                ).get(Signal.BUY)

                self.helper.update_order(
                    Signal.BUY,
                    instrument_type,
                    instrument_status,
                    instrument_price_buy,
                )

            else:
                self.helper.place_order(Signal.BUY, instrument_type, instrument_status)

            time.sleep(2)

    def sell_instrument(
        self, instrument_type: Instrument, enforce_sell_bool: bool = False
    ) -> None:
        for _ in range(3):
            instrument_status = self.helper.update_instrument_status(instrument_type)

            if (
                not instrument_status.has_position
                and not instrument_status.active_order
            ):
                return

            elif not instrument_status.has_position and instrument_status.active_order:
                self.helper.delete_order()

            elif instrument_status.has_position and not instrument_status.active_order:
                self.helper.place_order(Signal.SELL, instrument_type, instrument_status)

            # Update order
            if instrument_status.has_position and instrument_status.active_order:
                price_sell = None
                current_price_sell = self.helper.ava.get_certificate_info(
                    self.settings["instruments"]["TRADING"][instrument_type]
                )[Signal.SELL]

                if any(
                    [
                        current_price_sell <= instrument_status.price_stop_loss,
                        current_price_sell >= instrument_status.price_take_profit,
                        enforce_sell_bool,
                    ]
                ):
                    price_sell = current_price_sell

                self.helper.update_order(
                    Signal.SELL,
                    instrument_type,
                    instrument_status,
                    price_sell,
                    enforce_sell_bool,
                )

            time.sleep(2)

    # MAIN method
    def run_analysis(self, log_to_telegram: bool) -> None:
        self.helper.log_data["balance_before"] = sum(
            self.helper.ava.get_portfolio().buying_power.values()
        )

        log.info(
            f'> Running trading for account(s): {" & ".join(self.helper.accounts)} [{self.helper.log_data["balance_before"]}]'
        )

        strategies: dict = {}

        while True:
            self.helper.status.update_day_time()
            self.helper.std_output.messages = []

            if self.helper.status.day_time in [
                DayTime.MORNING,
                DayTime.PAUSE,
            ]:
                pass

            elif self.helper.status.day_time == DayTime.NIGHT:
                break

            else:
                # Walk through instruments
                for instrument_type in Instrument:

                    if (
                        self.helper.status.day_time != DayTime.EVENING
                        and self.helper.get_signal_is_buy(strategies, instrument_type)
                    ):

                        self.sell_instrument(
                            Instrument.BEAR
                            if instrument_type == Instrument.BULL
                            else Instrument.BULL,
                            enforce_sell_bool=True,
                        )

                        self.buy_instrument(instrument_type)

                    self.sell_instrument(instrument_type)

                    self.helper.add_std_output_message(instrument_type)

                self.helper.std_output.update_in_console()

            time.sleep(60)

        self.helper.log_data["balance_after"] = sum(
            self.helper.ava.get_portfolio().buying_power.values()
        )

        log.info(f'> End of the day. [{self.helper.log_data["balance_after"]}]')

        if log_to_telegram:
            TeleLog(day_trading_stats=self.helper.log_data)


def run() -> None:
    settings = Settings().load()

    for user, settings_per_user in settings.items():
        for setting_per_setup in settings_per_user.values():
            if not setting_per_setup.get("run_day_trading", False):
                continue

            try:
                Day_Trading(user, setting_per_setup["accounts"], setting_per_setup)

            except Exception as e:
                log.error(f">>> {e}: {traceback.format_exc()}")

                TeleLog(crash_report=f"DT: script has crashed: {e}")

            return
