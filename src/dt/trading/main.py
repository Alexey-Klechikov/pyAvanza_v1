import logging
import time
import traceback
from http.client import RemoteDisconnected
from typing import Optional

import pandas_ta as ta
from avanza import InstrumentType, OrderType
from requests import ReadTimeout
from requests.exceptions import HTTPError

from src.dt import DayTime, Instrument, TradingTime
from src.dt.trading.balance import Balance
from src.dt.trading.order import Order
from src.utils import Cache, Context, History, Settings, TeleLog

log = logging.getLogger("main.dt.trading.main")


class Helper:
    def __init__(self, settings: dict, dry: bool):
        self.settings = settings
        self.dry = dry

        self.trading_done = False

        self.ava = Context(settings["user"], settings["accounts"], process_lists=False)

        self.balance = Balance(
            before=self.get_balance_before(),
            tradable=settings["trading"]["budget"],
            daily_target=settings["trading"]["daily_target"],
            daily_limit=settings["trading"]["daily_limit"],
        )

        self.trading_time = TradingTime()

        self.order = Order(self.ava, settings)

    def get_balance_before(self) -> float:
        balance_before = sum(self.ava.portfolio.buying_power.values())

        for instrument in Instrument:
            instrument_status = self.get_instrument_status(instrument)

            if instrument_status["position"]:
                balance_before += (
                    instrument_status["position"]["acquiredPrice"]
                    * instrument_status["position"]["volume"]
                )

        return balance_before

    def get_balance_after(self) -> None:
        self.balance.after = (
            sum(self.ava.get_portfolio().buying_power.values())
            - self.balance.not_tradable
        )

        log.info(f"Balance after: {round(self.balance.after)}")

    def get_instrument_status(self, market_direction: str) -> dict:
        i_type, i_id = self.settings["instruments"]["TRADING"][market_direction]

        return self.ava.get_instrument_info(
            InstrumentType[i_type],
            str(i_id),
        )

    def buy_instrument(self, market_direction: Instrument) -> None:
        if self.dry:
            return

        for _ in range(5):
            instrument_status = self.get_instrument_status(market_direction)

            if instrument_status["position"]:
                return

            if not instrument_status["order"]:
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
            instrument_status = self.get_instrument_status(market_direction)

            if not instrument_status["order"] and not instrument_status["position"]:
                return

            elif instrument_status["order"] and not instrument_status["position"]:
                self.order.delete()

            elif not instrument_status["order"] and instrument_status["position"]:
                self.order.place(
                    OrderType.SELL, market_direction, instrument_status, custom_price
                )

            elif instrument_status["order"] and instrument_status["position"]:
                if instrument_status["order"]["price"] == custom_price:
                    return

                self.order.update(
                    OrderType.SELL, market_direction, instrument_status, custom_price
                )

                if custom_price:
                    break

            time.sleep(10)

    def traverse_instruments(
        self, market_direction: Instrument, instruments_pool: dict
    ) -> list:
        instruments = []

        for instrument_id, instrument_type in instruments_pool[market_direction]:
            instrument_info = self.ava.get_instrument_info(
                InstrumentType[instrument_type],
                str(instrument_id),
            )

            log_prefix = (
                f"Instrument {market_direction} ({instrument_type} - {instrument_id})"
            )

            if instrument_info["position"] or instrument_info["order"]:
                log.debug(f"{log_prefix} is in use")

                return [
                    {
                        "identifier": [instrument_type, instrument_id],
                        "numbers": {
                            "score": 0,
                        },
                    }
                ]

            elif instrument_info["is_deprecated"]:
                log.debug(f"{log_prefix} is deprecated")

            elif market_direction != {
                "Lång": Instrument.BULL,
                "Kort": Instrument.BEAR,
            }.get(instrument_info["key_indicators"]["direction"]):
                log.debug(
                    f"{log_prefix} is in wrong category: {instrument_info['key_indicators']['direction']}"
                )

            elif (
                not instrument_info[OrderType.BUY]
                or instrument_info[OrderType.BUY] > 280
            ):
                log.debug(
                    f"{log_prefix} has bad price: {instrument_info[OrderType.BUY]}"
                )

            elif not instrument_info["spread"] or not (
                0.1 < instrument_info["spread"] < 0.9
            ):
                log.debug(f"{log_prefix} has bad spread: {instrument_info['spread']}")

            elif (
                not instrument_info["key_indicators"].get("leverage")
                or instrument_info["key_indicators"]["leverage"] < 18
            ):
                log.debug(
                    f"{log_prefix} has bad leverage: {instrument_info['key_indicators'].get('leverage')}"
                )

            else:
                instruments.append(
                    {
                        "identifier": [instrument_type, instrument_id],
                        "numbers": {
                            "spread": instrument_info["spread"],
                            "leverage": instrument_info["key_indicators"]["leverage"],
                            "score": round(
                                instrument_info["key_indicators"]["leverage"]
                                / instrument_info["spread"]
                            )
                            // 3,
                        },
                    }
                )

        return instruments

    def update_trading_settings(self) -> None:
        settings = Settings().load("DT")

        instruments_pool = self.ava.retrieve_dt_instruments_from_watch_lists()

        instruments_info: dict = {}

        for market_direction in Instrument:
            instruments_info[market_direction] = []

            instruments_info[market_direction] = self.traverse_instruments(
                market_direction, instruments_pool
            )

            top_instruments = sorted(
                filter(
                    lambda x: x["numbers"]["score"]
                    == max(
                        [
                            i["numbers"]["score"]
                            for i in instruments_info[market_direction]
                        ]
                    ),
                    instruments_info[market_direction],
                ),
                key=lambda x: x["identifier"],
            )

            if top_instruments and (
                settings["instruments"]["TRADING"].get(market_direction)
                not in [i["identifier"] for i in top_instruments]
            ):
                log.info(
                    f'Change instrument {market_direction} -> {top_instruments[0]["identifier"]} ({top_instruments[0]["numbers"]})'
                )

                settings["instruments"]["TRADING"][market_direction] = top_instruments[
                    0
                ]["identifier"]

        Settings().dump(settings, "DT")

        self.settings = settings

    def get_target_instrument_from_combined_omx(self) -> Instrument:
        date = None
        omx_signal = 0
        for ticker_yahoo, ticker in self.settings["omx_weights"].items():
            data = History(ticker_yahoo, "18mo", "1d", cache=Cache.APPEND).data

            if str(data.iloc[-1]["Close"]) == "nan":
                self.ava.update_todays_ochl(data, ticker["order_book_id"])

            data.ta.sma(length=5, append=True)

            signal = (
                OrderType.BUY
                if data.iloc[-1]["Close"] > data.iloc[-1]["SMA_5"]
                else OrderType.SELL
            )

            omx_signal += (
                (1 if signal == OrderType.BUY else -1) * ticker["weight_calc"] / 100
            )

            date = data.iloc[-1].name.date()  # type: ignore

        log.info(
            f"Instrument tomorrow: {Instrument.BULL if omx_signal > 0 else Instrument.BEAR} (omx_signal: {round(omx_signal, 2)}, date: {date})"
        )

        return Instrument.BULL if omx_signal > 0 else Instrument.BEAR

    def save_omx_data(self) -> None:
        log.info("Load and save OMX30 data")

        History(
            self.settings["instruments"]["MONITORING"]["YAHOO"],
            period="1d",
            interval="1m",
            cache=Cache.APPEND,
            extra_data=self.ava.get_today_history(
                self.settings["instruments"]["MONITORING"]["AVA"]
            ),
        )


class Day_Trading:
    def __init__(self, dry: bool):
        settings = Settings().load("DT")
        self.helper = Helper(settings, dry)

        log.warning(("Dry run, no orders" if dry else "Orders") + " will be placed")

        while True:
            try:
                self.run_analysis(settings["log_to_telegram"])

                break

            except (ReadTimeout, ConnectionError, RemoteDisconnected, HTTPError):
                log.warning("AVA Connection error, reconnecting...")

                self.helper.ava.ctx = self.helper.ava.get_ctx(settings["user"])

    def action_morning(self) -> Optional[Instrument]:
        instrument_today = None
        for instrument in Instrument:
            instrument_status = self.helper.get_instrument_status(instrument)
            if instrument_status["position"]:
                instrument_today = instrument

        return instrument_today

    def action_day(self, instrument_today: Optional[Instrument]) -> None:
        if not instrument_today:
            return

        instrument_status = self.helper.get_instrument_status(instrument_today)

        custom_price = None
        if not instrument_status["order"]:
            custom_price = round(
                instrument_status[OrderType.SELL]
                * self.helper.settings["trading"]["daily_target"],
                2,
            )

        if (
            instrument_status["position"].get("acquiredPrice")
            and instrument_status["position"].get("acquiredPrice")
            * self.helper.settings["trading"]["daily_limit"]
            > instrument_status[OrderType.SELL]
        ):
            custom_price = instrument_status[OrderType.SELL]

        if instrument_status["position"].get("acquiredPrice"):
            log.debug(
                f'Acquired price: {round(instrument_status["position"].get("acquiredPrice"), 2)}, '
                + f"current price: {instrument_status[OrderType.SELL]} "
                + f'(change: {round(100 * (instrument_status[OrderType.SELL] - instrument_status["position"].get("acquiredPrice")) / instrument_status["position"].get("acquiredPrice"), 2)}%)'
            )

        if custom_price:
            self.helper.sell_instrument(instrument_today, custom_price)

    def action_evening(self, instrument_today: Optional[Instrument]) -> Instrument:
        self.helper.save_omx_data()

        instrument_tomorrow = self.helper.get_target_instrument_from_combined_omx()

        if instrument_today == instrument_tomorrow:
            return instrument_tomorrow

        if instrument_today:
            self.helper.sell_instrument(instrument_today)

        self.helper.update_trading_settings()

        self.helper.buy_instrument(instrument_tomorrow)

        instrument_status = self.helper.get_instrument_status(instrument_tomorrow)
        self.helper.sell_instrument(
            instrument_tomorrow,
            custom_price=round(
                instrument_status[OrderType.SELL]
                * self.helper.settings["trading"]["daily_target"],
                2,
            ),
        )

        return instrument_tomorrow

    # MAIN method
    def run_analysis(self, log_to_telegram: bool) -> None:
        self.helper.get_balance_before()

        instrument_today = None
        instrument_tomorrow = None

        while True:
            if self.helper.trading_time.day_time == DayTime.MORNING:
                instrument_today = self.action_morning()

            self.helper.trading_time.update_day_time()

            if self.helper.trading_time.day_time == DayTime.DAY:
                self.action_day(instrument_today)

            if self.helper.trading_time.day_time == DayTime.EVENING:
                instrument_tomorrow = self.action_evening(instrument_today)

                break

            time.sleep(120)

        self.helper.balance.update_after(
            self.helper.ava.get_portfolio().total_own_capital
        )

        if log_to_telegram:
            TeleLog(
                day_trading_stats=self.helper.balance.summarize(),
                instruments=f"{instrument_today} -> {instrument_tomorrow}",
            )


def run(dry: bool) -> None:
    try:
        Day_Trading(dry)

    except Exception as e:
        log.error(f">>> {e}: {traceback.format_exc()}")

        TeleLog(crash_report=f"DT: script has crashed: {e}")
