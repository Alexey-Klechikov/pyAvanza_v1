import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from avanza import OrderType
from requests import ReadTimeout

from module.day_trading_TA import (
    DayTime,
    Instrument,
    InstrumentStatus,
    Strategy,
    TradingTime,
)
from module.day_trading_TA.main_calibration import run as run_day_trading_ta_calibration
from module.utils import Context, Settings, TeleLog

log = logging.getLogger("main.day_trading_ta")


class Helper:
    def __init__(self, user, accounts: dict, settings: dict):
        self.settings = settings

        self.trading_done = False
        self.accounts = accounts

        self.ava = Context(user, accounts, skip_lists=True)
        self.trading_time = TradingTime()
        self.instrument_status = InstrumentStatus()

        self._update_budget()

        self.strategy_name = Strategy.load("DT_TA").get("use")

        self.log_data = {
            "balance_before": 0,
            "balance_after": 0,
            "number_errors": 0,
            "budget": self.settings["trading"]["budget"],
        }

    def _update_budget(self) -> None:
        own_capital = self.ava.get_portfolio().total_own_capital
        floating_budget = (own_capital // 500 - 1) * 500

        self.settings["trading"]["budget"] = max(
            floating_budget, self.settings["trading"]["budget"]
        )

    def signal_to_instrument(self, signal: OrderType) -> dict:
        return {
            OrderType.BUY: Instrument.BULL
            if signal == OrderType.BUY
            else Instrument.BEAR,
            OrderType.SELL: Instrument.BEAR
            if signal == OrderType.BUY
            else Instrument.BULL,
        }

    def get_signal(self) -> Optional[OrderType]:
        history = self.ava.get_today_history(
            self.settings["instruments"]["MONITORING"]["AVA"]
        )

        strategy = Strategy(history, strategies=[self.strategy_name])

        last_full_candle_index = -2

        if (datetime.now() - strategy.data.iloc[last_full_candle_index].name.replace(tzinfo=None)).seconds > 122:  # type: ignore
            return None

        for signal in [OrderType.BUY, OrderType.SELL]:
            if all(
                [
                    i(strategy.data.iloc[last_full_candle_index])
                    for i in list(strategy.strategies.values())[0][signal]
                ]
            ):
                log.info(f"Signal: {signal.name}")

                return signal

        return None

    def place_order(self, signal: OrderType, instrument_type: Instrument) -> None:
        if (
            (signal == OrderType.BUY and self.instrument_status.position)
            or (signal == OrderType.SELL and not self.instrument_status.position)
            or self.instrument_status.price_buy is None
            or self.instrument_status.price_sell is None
        ):
            return

        if self.instrument_status.spread is None or self.instrument_status.spread > 0.7:
            log.error(
                f"{instrument_type} - (place_order) HIGH SPREAD: {self.instrument_status.spread}"
            )

            self.log_data["number_errors"] += 1

            return

        order_data = {
            "name": instrument_type,
            "signal": signal,
            "account_id": list(self.accounts.values())[0],
            "order_book_id": self.settings["instruments"]["TRADING"][instrument_type],
        }

        if signal == OrderType.BUY:
            order_data.update(
                {
                    "price": self.instrument_status.price_buy,
                    "volume": int(
                        self.settings["trading"]["budget"]
                        // self.instrument_status.price_buy
                    ),
                    "budget": self.settings["trading"]["budget"],
                }
            )

        elif signal == OrderType.SELL:
            order_data.update(
                {
                    "price": self.instrument_status.price_sell,
                    "volume": self.instrument_status.position["volume"],
                }
            )

        self.ava.create_orders(
            [order_data],
            signal,
        )

        log.info(
            f'{instrument_type} - (SET {signal.name.upper()} order): {order_data["price"]}'
        )

    def update_order(self, signal: OrderType, instrument_type: Instrument) -> None:
        if (
            self.instrument_status.price_buy is None
            or self.instrument_status.price_sell is None
            or self.instrument_status.spread is None
        ):
            return

        if self.instrument_status.spread > 0.7:
            log.error(
                f"{instrument_type} - (update_order) HIGH SPREAD: "
                + f"{self.instrument_status.spread}"
            )

            self.log_data["number_errors"] += 1

            return

        price = (
            self.instrument_status.price_buy
            if signal == OrderType.BUY
            else self.instrument_status.price_sell
        )

        log.info(
            f"{instrument_type} - (UPD {signal.name.upper()} order): "
            + f'{self.instrument_status.active_order["price"]} -> {price}'
        )

        self.ava.update_order(self.instrument_status.active_order, price)

    def delete_order(self) -> None:
        self.ava.remove_active_orders(account_ids=[self.settings["accounts"]["DT"]])

    def update_instrument_status(self, instrument_type: Instrument) -> None:
        instrument_id = str(self.settings["instruments"]["TRADING"][instrument_type])

        certificate_info = self.ava.get_certificate_info(instrument_id)

        active_order = self.ava.get_active_order(instrument_id)

        self.instrument_status.get_status(certificate_info, active_order)


class Day_Trading:
    def __init__(self, user: str, accounts: dict, settings: dict):
        self.settings = settings

        self.helper = Helper(user, accounts, settings)

        log.info(f"Strategy: {self.helper.strategy_name}")

        while True:
            try:
                self.run_analysis(settings["log_to_telegram"])

                break

            except (ReadTimeout, ConnectionError):
                log.error("AVA Connection error, retrying in 5 seconds")
                self.helper.log_data["number_errors"] += 1

                self.helper.ava.ctx = self.helper.ava.get_ctx(user)

    def buy_instrument(self, instrument_type: Instrument) -> None:
        for _ in range(5):
            self.helper.update_instrument_status(instrument_type)

            if self.helper.instrument_status.position:
                return

            elif self.helper.instrument_status.active_order:
                self.helper.update_order(OrderType.BUY, instrument_type)

            else:
                self.helper.place_order(OrderType.BUY, instrument_type)

            time.sleep(10)

    def sell_instrument(self, instrument_type: Instrument) -> None:
        for _ in range(5):
            self.helper.update_instrument_status(instrument_type)

            if (
                not self.helper.instrument_status.active_order
                and not self.helper.instrument_status.position
            ):
                return

            elif (
                self.helper.instrument_status.active_order
                and not self.helper.instrument_status.position
            ):
                self.helper.delete_order()

            elif (
                not self.helper.instrument_status.active_order
                and self.helper.instrument_status.position
            ):
                self.helper.place_order(OrderType.SELL, instrument_type)

            elif (
                self.helper.instrument_status.active_order
                and self.helper.instrument_status.position
            ):
                self.helper.update_order(OrderType.SELL, instrument_type)

            time.sleep(10)

    # MAIN method
    def run_analysis(self, log_to_telegram: bool) -> None:
        self.helper.log_data["balance_before"] = sum(
            self.helper.ava.get_portfolio().buying_power.values()
        )

        log.info(
            f'Running trading for account(s): {" & ".join(self.helper.accounts)} [{self.helper.log_data["balance_before"]}]'
        )

        while True:
            self.helper.trading_time.update_day_time()

            if self.helper.trading_time.day_time == DayTime.MORNING:
                pass

            elif self.helper.trading_time.day_time == DayTime.EVENING:
                for instrument_type in Instrument:
                    self.sell_instrument(instrument_type)

                if not self.helper.instrument_status.position:
                    break

            else:
                signal = self.helper.get_signal()

                if signal is not None:
                    self.sell_instrument(
                        self.helper.signal_to_instrument(signal)[OrderType.SELL]
                    )

                    self.buy_instrument(
                        self.helper.signal_to_instrument(signal)[OrderType.BUY]
                    )

            time.sleep(45)

        self.helper.log_data["balance_after"] = sum(
            self.helper.ava.get_portfolio().buying_power.values()
        )

        log.info(f'End of the day. [{self.helper.log_data["balance_after"]}]')

        if log_to_telegram:
            TeleLog(day_trading_stats=self.helper.log_data)

        run_day_trading_ta_calibration(print_orders_history=False)


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

                TeleLog(crash_report=f"DT_TA: script has crashed: {e}")

            return
