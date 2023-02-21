import logging
import time
import traceback
from datetime import date
from http.client import RemoteDisconnected
from typing import Optional, Tuple

import pandas as pd
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
        self.ava = Context(settings["user"], settings["accounts"], process_lists=False)
        self.order = Order(self.ava, settings)

        self.log_data = {k: 0.0 for k in ["balance_before", "balance_after", "budget"]}

    def get_balance_before(self) -> None:
        transactions = self.ava.ctx.get_transactions(
            account_id=str(self.settings["accounts"]["DT"]),
            transactions_from=date.today(),
        )

        self.log_data["balance_before"] = (
            self.ava.portfolio.total_own_capital
            if not transactions or not transactions["transactions"]
            else sum(
                [
                    sum(self.ava.portfolio.buying_power.values()),
                    sum([i["sum"] for i in transactions["transactions"]]),
                ]
            )
        )

        log.info(f"Balance before: {round(self.log_data['balance_before'])}")

    def get_balance_after(self) -> None:
        self.log_data["balance_after"] = sum(
            self.ava.get_portfolio().buying_power.values()
        )

        log.info(f'Balance after: {round(self.log_data["balance_after"])}')

    def get_trade_history(self) -> Tuple[dict, list]:
        transactions = self.ava.ctx.get_transactions(
            account_id=str(self.settings["accounts"]["DT"]),
            transactions_from=date.today(),
        )

        if not transactions:
            return {}, []

        transactions_df = (
            pd.DataFrame(transactions["transactions"]).set_index("id").iloc[::-1]
        )
        transactions_df["orderbook"] = transactions_df["orderbook"].apply(
            lambda x: x["name"]
        )

        trades = []
        buy_price = 0
        sell_price = 0

        for _, row in transactions_df.iterrows():
            if buy_price and sell_price and row["transactionType"] == "BUY":
                trades.append([sell_price, buy_price])
                buy_price = 0
                sell_price = 0

            if row["transactionType"] == "SELL":
                sell_price += row["sum"]

            elif row["transactionType"] == "BUY":
                buy_price += row["sum"]

        if buy_price and sell_price:
            trades.append([sell_price, buy_price])

        profits = [round((1 - abs(i[1] / i[0])) * 100, 2) for i in trades]
        trades_stats = {
            "good": len([i for i in profits if i > 0]),
            "bad": len([i for i in profits if i < 0]),
        }

        return trades_stats, profits

    def update_budget(self) -> None:
        self.settings["trading"]["budget"] = max(
            round((self.log_data["balance_before"] * 0.8 / 100)) * 100,
            self.settings["trading"]["budget"],
        )

        self.log_data["budget"] = self.settings["trading"]["budget"]

        log.info(f'Trading budget: {self.settings["trading"]["budget"]}')

    def update_instrument_status(
        self, market_direction: Instrument
    ) -> InstrumentStatus:
        i_type, i_id = self.settings["instruments"]["TRADING"][market_direction]

        instrument_info = self.ava.get_instrument_info(
            InstrumentType[i_type],
            str(i_id),
        )

        self.instrument_status[market_direction].extract(instrument_info)

        return self.instrument_status[market_direction]

    def buy_instrument(self, market_direction: Instrument) -> None:
        if self.dry:
            return

        for _ in range(5):
            instrument_status = self.update_instrument_status(market_direction)

            if instrument_status.position:
                return

            if not instrument_status.active_order:
                self.order.place(OrderType.BUY, market_direction, instrument_status)

            else:
                self.order.update(OrderType.BUY, market_direction, instrument_status)

            time.sleep(10)

    def sell_instrument(
        self, market_direction: Instrument, custom_price: Optional[float] = None
    ) -> None:
        if self.dry:
            return

        for _ in range(5):
            instrument_status = self.update_instrument_status(market_direction)

            if not instrument_status.active_order and not instrument_status.position:
                return

            elif instrument_status.active_order and not instrument_status.position:
                self.order.delete()

            elif not instrument_status.active_order and instrument_status.position:
                self.order.place(
                    OrderType.SELL, market_direction, instrument_status, custom_price
                )

            elif instrument_status.active_order and instrument_status.position:
                if instrument_status.active_order["price"] == custom_price:
                    return

                self.order.update(
                    OrderType.SELL, market_direction, instrument_status, custom_price
                )

                if custom_price:
                    break

            time.sleep(10)


class Day_Trading:
    def __init__(self, dry: bool):
        settings = Settings().load("DT")
        self.helper = Helper(settings, dry)
        self.signal = Signal(self.helper.ava, settings)

        log.warning(("Dry run, no o" if dry else "O") + "rders will be placed")

        log.info("Strategies: ")
        [log.info(f"> [{index + 1}] {i}") for index, i in enumerate(Strategy.load("DT").get("use", []))]  # type: ignore

        while True:
            try:
                self.run_analysis(settings["log_to_telegram"])

                break

            except (ReadTimeout, ConnectionError, RemoteDisconnected):
                log.error("AVA Connection error, retrying in 5 seconds")

                self.helper.ava.ctx = self.helper.ava.get_ctx(settings["user"])

    def action_morning(self) -> None:
        for market_direction in Instrument:
            instrument_status = self.helper.update_instrument_status(market_direction)

            if instrument_status.position:
                log.info(
                    " ".join(
                        [
                            f"{market_direction} {self.helper.settings['instruments']['TRADING'][market_direction]} has position.",
                            f"Acquired price: {instrument_status.acquired_price},",
                            f"Current price: {instrument_status.price_sell},",
                            f"Profit: {instrument_status.get_profit()}%",
                        ]
                    )
                )

                instrument_status.update_limits(0.7)

    def action_day(self) -> None:
        signal, message = self.signal.get(Strategy.load("DT").get("use", []))
        self.helper.order.settings = self.helper.settings = Settings().load("DT")

        def _action_signal(signal: OrderType, atr: float) -> None:
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

            instrument_status.update_limits(atr)

            self.helper.sell_instrument(
                instrument_buy,
                instrument_status.take_profit,
            )

        def _action_no_signal(atr: float, rsi: float) -> None:
            for market_direction in Instrument:
                instrument_status = self.helper.update_instrument_status(
                    market_direction
                )

                if instrument_status.position and not instrument_status.stop_loss:
                    self.helper.instrument_status[market_direction].update_limits(atr)

                if not (
                    instrument_status.position
                    and instrument_status.price_sell
                    and instrument_status.stop_loss
                    and instrument_status.take_profit
                ):
                    continue

                if instrument_status.position and not instrument_status.active_order:
                    self.helper.sell_instrument(
                        market_direction,
                        instrument_status.take_profit,
                    )

                if instrument_status.price_sell <= instrument_status.stop_loss:
                    log.debug(
                        f"{market_direction} hit SL {instrument_status.price_sell} <= {instrument_status.stop_loss}"
                    )
                    self.helper.sell_instrument(market_direction)

                if self.signal.exit(market_direction, instrument_status):
                    log.info(
                        f"Signal: Exit | RSI: {round(rsi, 2)}",
                    )

                    self.helper.sell_instrument(market_direction)

        if self.signal.last_candle is None or message == ["Duplicate candle hit"]:
            return

        if signal:
            _action_signal(signal, self.signal.last_candle["ATR"])

        else:
            _action_no_signal(
                self.signal.last_candle["ATR"], self.signal.last_candle["RSI"]
            )

    def action_evening(self) -> None:
        for market_direction in Instrument:
            self.helper.sell_instrument(market_direction)

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
            trades_stats, profits = self.helper.get_trade_history()

            TeleLog(
                day_trading_stats=self.helper.log_data,
                trades_stats=trades_stats,
                profits=profits,
            )


def run(dry: bool) -> None:
    try:
        Day_Trading(dry)

    except Exception as e:
        log.error(f">>> {e}: {traceback.format_exc()}")

        TeleLog(crash_report=f"DT: script has crashed: {e}")
