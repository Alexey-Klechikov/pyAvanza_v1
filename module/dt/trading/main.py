import logging
import time
import traceback
from datetime import date
from typing import Optional

from avanza import InstrumentType, OrderType
from requests import ReadTimeout

from module.dt import DayTime, Strategy, TradingTime
from module.dt.common_types import Instrument
from module.dt.trading.order import Order
from module.dt.trading.signal import Signal
from module.dt.trading.status import InstrumentStatus
from module.utils import Context, Settings, TeleLog, displace_message

log = logging.getLogger("main.dt.trading.main")

DISPLACEMENTS = (12, 14, 13, 12, 9, 0)


class Helper:
    def __init__(self, settings: dict, dry: bool):
        self.settings = settings
        self.dry = dry

        self.trading_done = False

        self.trading_time = TradingTime()
        self.instrument_status: dict = {
            instrument: InstrumentStatus(instrument, settings["trading"])
            for instrument in Instrument
        }
        self.strategy_names = Strategy.load("DT").get("use", [])
        self.ava = Context(settings["user"], settings["accounts"], skip_lists=True)
        self.order = Order(self.ava, settings)

        self.log_data = {
            k: 0.0
            for k in ["balance_before", "balance_after", "number_errors", "budget"]
        }

    def get_balance_before(self) -> None:
        transactions = self.ava.ctx.get_transactions(
            account_id=str(self.settings["accounts"]["DT"]),
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

        instrument_info = self.ava.get_instrument_info(
            InstrumentType.WARRANT, instrument_id
        )

        self.instrument_status[instrument_type].extract(instrument_info)

        return self.instrument_status[instrument_type]

    def buy_instrument(self, instrument_type: Instrument) -> None:
        if self.dry:
            return

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
        if self.dry:
            return

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
    def __init__(self, settings: dict, dry: bool):
        if dry:
            log.warning("Dry run, no orders will be placed")

        self.helper = Helper(settings, dry)
        self.signal = Signal(self.helper.ava, settings)

        log.info("Strategies: ")
        [log.info(f"> [{index + 1}] {i}") for index, i in enumerate(Strategy.load("DT").get("use", []))]  # type: ignore

        while True:
            try:
                self.run_analysis(settings["log_to_telegram"])

                break

            except (ReadTimeout, ConnectionError):
                log.error("AVA Connection error, retrying in 5 seconds")
                self.helper.log_data["number_errors"] += 1

                self.helper.ava.ctx = self.helper.ava.get_ctx(settings["user"])

    def action_morning(self) -> None:
        for instrument_type in Instrument:
            instrument_status = self.helper.update_instrument_status(instrument_type)

            if instrument_status.position:
                log.info(
                    " ".join(
                        [
                            f"{instrument_type} ({self.helper.settings['instruments']['TRADING'][instrument_type]}) has position.",
                            f"Acquired price: {instrument_status.acquired_price},",
                            f"Current price: {instrument_status.price_sell},",
                            f"Profit: {instrument_status.get_profit()}%",
                        ]
                    )
                )

    def action_day(self) -> None:
        signal, message = self.signal.get(Strategy.load("DT").get("use", []))
        self.helper.settings = Settings().load("DT")

        if self.signal.last_candle is None:
            return

        if signal:
            instrument_sell = Instrument.from_signal(signal)[OrderType.SELL]
            self.helper.sell_instrument(instrument_sell)

            instrument_buy = Instrument.from_signal(signal)[OrderType.BUY]
            self.helper.buy_instrument(instrument_buy)

            instrument_status = self.helper.instrument_status[instrument_buy]

            message.insert(
                1,
                f"Profit: {instrument_status.get_profit()}%",
            )

            log.info(
                displace_message(DISPLACEMENTS, tuple(message)),
            )

            instrument_status.update_limits(self.signal.last_candle["ATR"])

            self.helper.sell_instrument(
                instrument_buy,
                instrument_status.take_profit,
            )

        else:
            for instrument_type in Instrument:
                instrument_status = self.helper.update_instrument_status(
                    instrument_type
                )

                if instrument_status.position and instrument_status.stop_loss is None:
                    self.helper.instrument_status[instrument_type].update_limits(
                        self.signal.last_candle["ATR"]
                    )

                if (
                    not instrument_status.position
                    or instrument_status.price_sell is None
                    or instrument_status.stop_loss is None
                    or instrument_status.take_profit is None
                ):
                    continue

                if instrument_status.position and not instrument_status.active_order:
                    self.helper.sell_instrument(
                        instrument_type,
                        instrument_status.take_profit,
                    )

                if instrument_status.price_sell <= instrument_status.stop_loss:
                    log.debug(
                        f"{instrument_type} hit SL {instrument_status.price_sell} <= {instrument_status.stop_loss}"
                    )
                    self.helper.sell_instrument(instrument_type)

                if self.signal.exit(instrument_type, instrument_status):
                    self.helper.sell_instrument(instrument_type)

    def action_evening(self) -> None:
        for instrument_type in Instrument:
            self.helper.sell_instrument(instrument_type)

    # MAIN method
    def run_analysis(self, log_to_telegram: bool) -> None:
        self.helper.get_balance_before()
        self.helper.update_budget()

        while True:

            if self.helper.trading_time.day_time == DayTime.MORNING:
                self.action_morning()

            self.helper.trading_time.update_day_time()

            if self.helper.trading_time.day_time == DayTime.DAY:
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


def run(dry: bool) -> None:
    settings = Settings().load("DT")

    try:
        Day_Trading(settings, dry)

    except Exception as e:
        log.error(f">>> {e}: {traceback.format_exc()}")

        TeleLog(crash_report=f"DT: script has crashed: {e}")
