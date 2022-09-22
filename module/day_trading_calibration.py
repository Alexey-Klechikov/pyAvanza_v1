import random
import logging
import platform
import traceback
import pandas as pd
import yfinance as yf
from dataclasses import dataclass
from typing import Optional, Literal
from datetime import datetime

from .utils import Plot
from .utils import Context
from .utils import History
from .utils import TeleLog
from .utils import Settings
from .utils import Strategy_DT


log = logging.getLogger("main.day_trading_calibration")


SIGNAL = Literal["BUY", "SELL"]
ORDER_TYPE = Literal["BULL", "BEAR"]


@dataclass
class CalibrationOrder:
    instrument: str
    settings: dict

    on_balance: bool = False
    price_buy: Optional[float] = None
    price_sell: Optional[float] = None
    time_buy: Optional[datetime] = None
    time_sell: Optional[datetime] = None
    verdict: Optional[str] = None

    def buy(self, row, index):
        self.on_balance = True
        self.price_buy
        self.price_buy = random.uniform(row["High"], row["Low"]) * (
            1.00015 if self.instrument == "BULL" else 0.99985
        )
        self.time_buy = index
        
    def sell(self, row, index, enforce=False):
        self.price_sell = random.uniform(row["High"], row["Low"])
        self.time_sell = index

        stop_loss_normalized = self.price_buy * (
            1
            - (1 if self.instrument == "BULL" else -1)
            * (
                abs(1 - self.settings["trading"]["limits_percent"]["stop_loss"])
                / self.settings["instruments"]["multiplier"]
            )
        )

        take_profit_normalized = self.price_buy * (
            1
            + (1 if self.instrument == "BULL" else -1)
            * (
                abs(1 - self.settings["trading"]["limits_percent"]["take_profit"])
                / self.settings["instruments"]["multiplier"]
            )
        )

        if enforce:
            stop_loss_normalized = self.price_buy if self.price_buy is not None else stop_loss_normalized
            take_profit_normalized = self.price_buy if self.price_buy is not None else take_profit_normalized
            
        if (self.price_sell <= stop_loss_normalized and self.instrument == "BULL") or (
            self.price_sell >= stop_loss_normalized and self.instrument == "BEAR"
        ):
            self.verdict = "bad"

        elif (
            self.price_sell >= take_profit_normalized and self.instrument == "BULL"
        ) or (self.price_sell <= take_profit_normalized and self.instrument == "BEAR"):
            self.verdict = "good"

    def pop_result(self) -> dict:
        result = {
            "instrument": self.instrument,
            "price_buy": self.price_buy,
            "price_sell": self.price_sell,
            "time_buy": self.time_buy,
            "time_sell": self.time_sell,
            "verdict": self.verdict,
        }
        
        self.on_balance = False
        self.price_buy = None
        self.price_sell = None
        self.time_buy = None
        self.time_sell = None
        self.verdict = None
        
        return result


class Helper:
    def __init__(self, settings: dict) -> None:
        self.strategies: dict = {
            "BULL": dict(),
            "BEAR": dict(),
        }

        self.orders: dict = {
            "BULL": CalibrationOrder("BULL", settings),
            "BEAR": CalibrationOrder("BEAR", settings),
        }

        self.orders_history: list[dict] = list()

        self.stats_strategy: dict = {
            "good": {"BULL": 0, "BEAR": 0},
            "bad": {"BULL": 0, "BEAR": 0},
        }

        # Update_strategies variables
        self.success_limit = settings["calibration"]["success_limit"]
        
        self.stats_patterns: dict = dict()

        self.filtered_strategies = {"BULL": dict(), "BEAR": dict()}

    def buy_order(
        self,
        last_candle_signal: Optional[SIGNAL],
        index: datetime,
        row: pd.Series,
        is_realistic: bool = False,
    ) -> Optional[ORDER_TYPE]:
        instrument_buy = None

        if last_candle_signal == "BUY" and not self.orders["BULL"].on_balance:
            instrument_buy = "BULL"

        elif last_candle_signal == "SELL" and not self.orders["BEAR"].on_balance:
            instrument_buy = "BEAR"

        if instrument_buy is not None:
            if is_realistic:
                instrument_sell = "BULL" if instrument_buy == "BEAR" else "BEAR"
                self.sell_order(index, row, enforce_sell_instrument=instrument_sell)


            self.orders[instrument_buy].buy(row, index)

        return instrument_buy

    def sell_order(
        self,
        index: datetime,
        row: pd.Series,
        enforce_sell_instrument: Optional[ORDER_TYPE] = None,
    ) -> None:
        for instrument, instrument_order in self.orders.items():
            if not instrument_order.on_balance:
                continue

            enforce = (
                enforce_sell_instrument is not None
                and enforce_sell_instrument == instrument
            )

            instrument_order.sell(row, index, enforce)

            if instrument_order.verdict is None:
                continue
            
            self.stats_strategy[instrument_order.verdict][instrument] += 1
            self.orders_history.append(instrument_order.pop_result())


    def get_signal(
        self, value: int, ta_indicator: dict, row: pd.Series
    ) -> Optional[SIGNAL]:
        signal = None

        if value > 0 and ta_indicator["buy"](row):
            signal = "BUY"

        elif value < 0 and ta_indicator["sell"](row):
            signal = "SELL"

        return signal

    # Update_strategies functions
    def save_strategy(self, ta_indicator_name: str, column: str) -> None:
        for instrument in self.strategies:
            number_transactions = (
                self.stats_strategy["good"][instrument]
                + self.stats_strategy["bad"][instrument]
            )

            efficiency_percent = (
                0
                if number_transactions == 0
                else round(
                    (self.stats_strategy["good"][instrument] / number_transactions)
                    * 100
                )
            )

            self.stats_strategy["keep"] = (
                True
                if (
                    efficiency_percent >= self.success_limit
                    and self.stats_strategy["good"][instrument]
                    - self.stats_strategy["bad"][instrument]
                    >= 2
                )
                else False
            )

            message = " ".join(
                [
                    f"{ta_indicator_name} + {column} - {instrument}:",
                    f"{efficiency_percent}%",
                    f"({self.stats_strategy['good'][instrument]} Good / {self.stats_strategy['bad'][instrument]} Bad)",
                ]
            )

            if self.stats_strategy["keep"]:
                self.filtered_strategies[instrument].setdefault(
                    ta_indicator_name, list()
                )
                self.filtered_strategies[instrument][ta_indicator_name].append(column)

                log.info(message)

            else:
                log.debug(message)

    def save_stats_patterns(self, column: str) -> None:
        self.stats_patterns.setdefault(
            column,
            {
                "total_good": {"BULL": 0, "BEAR": 0},
                "total_bad": {"BULL": 0, "BEAR": 0},
                "keep_good": {"BULL": 0, "BEAR": 0},
                "keep_bad": {"BULL": 0, "BEAR": 0},
            },
        )

        for verdict in ["good", "bad"]:
            for instrument in ["BULL", "BEAR"]:
                self.stats_patterns[column][f"total_{verdict}"][
                    instrument
                ] += self.stats_strategy[verdict][instrument]

                if not self.stats_strategy["keep"]:
                    continue

                self.stats_patterns[column][f"keep_{verdict}"][
                    instrument
                ] += self.stats_strategy[verdict][instrument]

        self.stats_strategy = {
            "good": {"BULL": 0, "BEAR": 0},
            "bad": {"BULL": 0, "BEAR": 0},
        }

    def print_stats_patterns(self) -> None:
        log.warning("Stats per pattern:")

        for column, stats in self.stats_patterns.items():
            message = [
                column,
                f"- Total: {sum(stats['keep_good'].values())} / {sum(stats['total_good'].values())}",
                f'- BULL: {stats["keep_good"]["BULL"]} / {stats["total_good"]["BULL"]}',
                f'- BEAR: {stats["keep_good"]["BEAR"]} / {stats["total_good"]["BEAR"]}',
            ]

            log.info(" ".join(message))

    # Test_strategies funnctions
    def print_stats_instruments(self) -> None:
        log.info("Stats per instrument:")

        for verdict, instruments_counters in self.stats_strategy.items():
            message = [
                f'{verdict} ({instruments_counters["BULL"] + instruments_counters["BEAR"]}):',
                f'BULL: {instruments_counters["BULL"]}',
                f'/ BEAR: {instruments_counters["BEAR"]}',
            ]

            log.info(" ".join(message))

class Calibration:
    def __init__(self, settings: dict, user: str):
        self.settings = settings

        self.ava = Context(user, settings["accounts"], skip_lists=True)

    def update_strategies(self) -> None:
        log.info(
            f"Updating strategies: "
            + str(self.settings["trading"]["limits_percent"])
            + f' success_limit: {self.settings["calibration"]["success_limit"]}'
        )

        extra_data = self.ava.get_today_history(
            self.settings["instruments"]["MONITORING"]["AVA"]
        )

        history = History(
            self.settings["instruments"]["MONITORING"]["YAHOO"],
            "90d",
            "1m",
            cache="append",
            extra_data=extra_data,
        )

        strategy = Strategy_DT(
            history.data,
            order_price_limits=self.settings["trading"]["limits_percent"],
        )

        helper = Helper(self.settings)
        daily_volumes = history.data.groupby([history.data.index.date]).sum()["Volume"].values.tolist()  # type: ignore

        log.info(
            f"Dates range: {history.data.index[0].strftime('%Y.%m.%d')} - {history.data.index[-1].strftime('%Y.%m.%d')} "  # type: ignore
            + f"({history.data.shape[0]} rows) "
            + f"({len([i for i in daily_volumes if i > 0])} / {len(daily_volumes)} days with Volume)"
        )

        for ta_indicator_name, ta_indicator in strategy.ta_indicators.items():
            for column in strategy.data.columns:
                if not column.startswith("CDL") or (strategy.data[column] == 0).all():
                    continue

                last_candle_signal = None

                for index, row in strategy.data[
                    ["High", "Low", "Open", "Close", column] + ta_indicator["columns"]
                ].iterrows():

                    instrument_buy = helper.buy_order(last_candle_signal, index, row)
                    if instrument_buy is not None:
                        continue

                    helper.sell_order(index, row)

                    last_candle_signal = helper.get_signal(
                        row[column], ta_indicator, row
                    )

                helper.save_strategy(
                    ta_indicator_name,
                    column,
                )

                helper.save_stats_patterns(column)

        helper.print_stats_patterns()

        strategy.dump("DT", helper.filtered_strategies)

    def test_strategies(self) -> pd.DataFrame:
        log.info(f"Testing strategies")

        history = History(
            self.settings["instruments"]["MONITORING"]["YAHOO"],
            "4d",
            "1m",
            cache="skip",
        )

        strategy = Strategy_DT(
            history.data,
            order_price_limits=self.settings["trading"]["limits_percent"],
        )

        strategies = strategy.load("DT")

        helper = Helper(self.settings)

        signals = list()

        for index, row in strategy.data.iterrows():
            instrument_buy = helper.buy_order(None if not signals else signals[-1], index, row, is_realistic=True)  # type: ignore

            if instrument_buy is None:
                helper.sell_order(index, row)  # type: ignore

            if helper.orders_history:
                last_order = helper.orders_history.pop()

                log.info(
                    f"{str(index)[5:16]} / {round(row['Close'], 2)} -> {last_order['instrument']}: {last_order['verdict']}"
                )

            signal_result = None

            for instrument in ["BULL", "BEAR"]:
                for ta_indicator_name, ta_indicator in strategy.ta_indicators.items():
                    cs_columns = strategies[instrument].get(ta_indicator_name, list())

                    for cs_column in cs_columns:
                        signal = helper.get_signal(
                            row[cs_column], ta_indicator, row  # type: ignore
                        )
           
                        if signal is not None and (signal == ('BUY' if instrument == 'BULL' else 'SELL')):
                            log.warning(
                                f"{str(index)[5:16]} / {round(row['Close'], 2)} / {instrument}-{ta_indicator_name}-{cs_column}"
                            )

                            signal_result = signal

            signals.append(signal_result)

        strategy.data["signal"] = signals

        helper.print_stats_instruments()

        return strategy.data

    def plot_strategies(self, data: pd.DataFrame) -> None:
        if platform.system() != "Darwin":
            return

        data["buy_signal"] = data.apply(
            lambda x: x["High"] if x["signal"] == "BUY" else None, axis=1
        )
        data["sell_signal"] = data.apply(
            lambda x: x["Low"] if x["signal"] == "SELL" else None, axis=1
        )

        plot = Plot(
            data=data,
            title=f"Signals",
        )
        plot.add_orders_to_main_plot()
        plot.show_single_ticker()


def run() -> None:
    settings = Settings().load()

    for user, settings_per_user in settings.items():
        for setting_per_setup in settings_per_user.values():
            if not setting_per_setup.get("run_day_trading", False):
                continue

            try:
                calibration = Calibration(setting_per_setup, user)

                if setting_per_setup["calibration"]["update"]:
                    calibration.update_strategies()

                data = calibration.test_strategies()
                #calibration.plot_strategies(data)

                TeleLog(message=f"DT calibration: done.")

            except Exception as e:
                log.error(f">>> {e}: {traceback.format_exc()}")

                TeleLog(crash_report=f"DT calibration: script has crashed: {e}")

            return
