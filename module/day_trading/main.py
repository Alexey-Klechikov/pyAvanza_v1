import logging
import time
import traceback
from datetime import date
from typing import Optional

import pandas as pd
from avanza import OrderType
from requests import ReadTimeout

from module.day_trading import (
    DayTime,
    Instrument,
    InstrumentStatus,
    Signal,
    Strategy,
    TradingTime,
)
from module.day_trading.main_calibration import run as run_day_trading_ta_calibration
from module.utils import Context, Settings, TeleLog

log = logging.getLogger("main.day_trading.main")


class Order:
    def __init__(self, ava: Context, settings: dict, accounts: dict):
        self.ava = ava
        self.settings = settings
        self.accounts = accounts

    def place(
        self,
        signal: OrderType,
        instrument_type: Instrument,
        instrument_status: InstrumentStatus,
        custom_price: Optional[float] = None,
    ) -> None:
        if (
            (signal == OrderType.BUY and instrument_status.position)
            or (signal == OrderType.SELL and not instrument_status.position)
            or instrument_status.price_buy is None
            or instrument_status.price_sell is None
        ):
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
                    "price": instrument_status.price_buy,
                    "volume": int(
                        self.settings["trading"]["budget"]
                        // instrument_status.price_buy
                    ),
                    "budget": self.settings["trading"]["budget"],
                }
            )

        elif signal == OrderType.SELL:
            order_data.update(
                {
                    "price": instrument_status.price_sell,
                    "volume": instrument_status.position["volume"],
                }
            )

        if custom_price is not None:
            order_data["price"] = custom_price

        self.ava.create_orders(
            [order_data],
            signal,
        )

        log.debug(
            f'{instrument_type} - (SET {signal.name.upper()} order): {order_data["price"]}'
        )

    def update(
        self,
        signal: OrderType,
        instrument_type: Instrument,
        instrument_status: InstrumentStatus,
        custom_price: Optional[float] = None,
    ) -> None:
        if (
            instrument_status.price_buy is None
            or instrument_status.price_sell is None
            or instrument_status.spread is None
        ):
            return

        price = (
            instrument_status.price_buy
            if signal == OrderType.BUY
            else instrument_status.price_sell
        )

        if custom_price is not None:
            price = custom_price

        log.debug(
            f'{instrument_type} - (UPD {signal.name.upper()} order): {instrument_status.active_order["price"]} -> {price} '
        )

        self.ava.update_order(instrument_status.active_order, price)

    def delete(self) -> None:
        self.ava.delete_active_orders(account_ids=[self.settings["accounts"]["DT"]])


class Helper:
    def __init__(self, user, accounts: dict, settings: dict):
        self.settings = settings
        self.accounts = accounts

        self.trading_done = False

        self.trading_time = TradingTime()
        self.instrument_status: dict = {
            instrument: InstrumentStatus(self.settings["trading"])
            for instrument in Instrument
        }
        self.strategy_names = Strategy.load("DT").get("use", [])
        self.ava = Context(user, accounts, skip_lists=True)
        self.order = Order(self.ava, settings, accounts)

        self.log_data = {
            k: 0.0
            for k in ["balance_before", "balance_after", "number_errors", "budget"]
        }

    def get_balance_before(self) -> None:
        transactions = self.ava.ctx.get_transactions(
            account_id=str(self.accounts["DT"]),
            transactions_from=date.today(),
        )

        if transactions and transactions["transactions"]:
            self.log_data["balance_before"] = sum(
                [
                    sum(self.ava.get_portfolio().buying_power.values()),
                    sum([i["sum"] for i in transactions["transactions"]]),
                ]
            )

        else:
            self.log_data["balance_before"] = self.ava.get_portfolio().total_own_capital

        log.info(f"Balance before: {round(self.log_data['balance_before'])}")

    def get_balance_after(self) -> None:
        self.log_data["balance_after"] = sum(
            self.ava.get_portfolio().buying_power.values()
        )

        log.info(f'Balance after: {round(self.log_data["balance_after"])}')

    def update_budget(self) -> None:
        self.settings["trading"]["budget"] = max(
            round((self.log_data["balance_before"] * 0.8 / 100)) * 100,
            self.settings["trading"]["budget"],
        )

        self.log_data["budget"] = self.settings["trading"]["budget"]

        log.info(f'Trading budget: {self.settings["trading"]["budget"]}')

    def update_instrument_status(self, instrument_type: Instrument) -> InstrumentStatus:
        instrument_id = str(self.settings["instruments"]["TRADING"][instrument_type])

        certificate_info = self.ava.get_certificate_info(instrument_id)

        self.instrument_status[instrument_type].get_status(certificate_info)

        return self.instrument_status[instrument_type]

    def buy_instrument(self, instrument_type: Instrument) -> None:
        for _ in range(5):
            instrument_status = self.update_instrument_status(instrument_type)

            if instrument_status.position:
                return

            elif not instrument_status.active_order:
                self.order.place(OrderType.BUY, instrument_type, instrument_status)

            else:
                self.order.update(OrderType.BUY, instrument_type, instrument_status)

            time.sleep(10)

    def sell_instrument(
        self, instrument_type: Instrument, custom_price: Optional[float] = None
    ) -> None:
        for _ in range(5):
            instrument_status = self.update_instrument_status(instrument_type)

            if not instrument_status.active_order and not instrument_status.position:
                return

            elif instrument_status.active_order and not instrument_status.position:
                self.order.delete()

            elif not instrument_status.active_order and instrument_status.position:
                self.order.place(
                    OrderType.SELL, instrument_type, instrument_status, custom_price
                )

            elif instrument_status.active_order and instrument_status.position:
                if instrument_status.active_order["price"] == custom_price:
                    return

                self.order.update(
                    OrderType.SELL, instrument_type, instrument_status, custom_price
                )

                if custom_price is not None:
                    break

            time.sleep(10)


class Day_Trading:
    def __init__(self, user: str, accounts: dict, settings: dict):
        self.settings = settings

        self.helper = Helper(user, accounts, settings)
        self.signal = Signal(self.helper.ava, self.settings, self.helper.strategy_names)

        log.info("Strategies: ")
        [log.info(f"> [{index + 1}] {i}") for index, i in enumerate(self.helper.strategy_names)]  # type: ignore

        while True:
            try:
                self.run_analysis(settings["log_to_telegram"])

                break

            except (ReadTimeout, ConnectionError):
                log.error("AVA Connection error, retrying in 5 seconds")
                self.helper.log_data["number_errors"] += 1

                self.helper.ava.ctx = self.helper.ava.get_ctx(user)

    def action_day(self) -> None:
        signal = self.signal.get()

        if self.signal.last_candle is None:
            return

        if signal is None:
            for instrument_type in Instrument:
                instrument_status = self.helper.update_instrument_status(
                    instrument_type
                )

                if instrument_status.position and instrument_status.stop_loss is None:
                    self.helper.instrument_status[instrument_type].update_limits(
                        self.signal.last_candle["ATR"]
                    )

                    log.info(
                        f"{instrument_type} limits are: SL {instrument_status.stop_loss}, TP {instrument_status.take_profit}"
                    )

                if (
                    not instrument_status.position
                    or instrument_status.price_sell is None
                    or instrument_status.stop_loss is None
                ):
                    continue

                if instrument_status.price_sell <= instrument_status.stop_loss:
                    self.helper.sell_instrument(instrument_type)

                if self.signal.exit(instrument_type, instrument_status):
                    self.helper.sell_instrument(instrument_type)

        else:
            instrument_sell = Instrument.from_signal(signal)[OrderType.SELL]
            self.helper.sell_instrument(instrument_sell)

            instrument_buy = Instrument.from_signal(signal)[OrderType.BUY]
            self.helper.buy_instrument(instrument_buy)

            self.helper.instrument_status[instrument_buy].update_limits(
                self.signal.last_candle["ATR"]
            )

            self.helper.sell_instrument(
                instrument_buy,
                self.helper.instrument_status[instrument_buy].take_profit,
            )

    def action_evening(self) -> None:
        for instrument_type in Instrument:
            self.helper.sell_instrument(instrument_type)

    # MAIN method
    def run_analysis(self, log_to_telegram: bool) -> None:
        self.helper.get_balance_before()
        self.helper.update_budget()

        while True:
            self.helper.trading_time.update_day_time()

            if self.helper.trading_time.day_time == DayTime.MORNING:
                pass

            elif self.helper.trading_time.day_time == DayTime.DAY:
                self.action_day()

            elif self.helper.trading_time.day_time == DayTime.EVENING:
                self.action_evening()

                if (
                    not self.helper.instrument_status[Instrument.BEAR].position
                    and not self.helper.instrument_status[Instrument.BULL].position
                ):
                    break

            time.sleep(30)

        self.helper.get_balance_after()

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

                TeleLog(crash_report=f"DT: script has crashed: {e}")

            return
