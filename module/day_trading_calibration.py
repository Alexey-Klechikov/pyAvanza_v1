import logging
import platform
import traceback
import pandas as pd
import yfinance as yf

from dataclasses import dataclass
from typing import Optional, Literal, List, Tuple
from datetime import datetime
from pandas_ta.candles.cdl_pattern import ALL_PATTERNS

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
        self.time_buy = index

        self.on_balance = True
        self.price_buy = ((row["Low"] + row["High"]) / 2) * (
            1.00015 if self.instrument == "BULL" else 0.99985
        )

    def sell(self, row, index, enforce=False):
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
            stop_loss_normalized = (
                self.price_buy if self.price_buy is not None else stop_loss_normalized
            )
            take_profit_normalized = (
                self.price_buy if self.price_buy is not None else take_profit_normalized
            )

        self.price_sell = (row["Low"] + row["High"]) / 2

        if (self.price_sell <= stop_loss_normalized and self.instrument == "BULL") or (
            self.price_sell >= stop_loss_normalized and self.instrument == "BEAR"
        ):
            self.verdict = "bad"

            return

        self.price_sell = row["Low"] if self.instrument == "BULL" else row["High"]

        if (
            self.price_sell >= take_profit_normalized and self.instrument == "BULL"
        ) or (self.price_sell <= take_profit_normalized and self.instrument == "BEAR"):
            self.verdict = "good"

            return

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

        self.strategies_efficiency: dict = dict()

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

            strategy_name = f"{column} + {ta_indicator_name} - {instrument}"

            self.strategies_efficiency[strategy_name] = (
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
                    self.strategies_efficiency[strategy_name] >= self.success_limit
                    and self.stats_strategy["good"][instrument]
                    - self.stats_strategy["bad"][instrument]
                    >= 2
                )
                else False
            )

            message = " ".join(
                [
                    f"{strategy_name}: {self.strategies_efficiency[strategy_name]}%",
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

    # Test_strategies functions
    def print_stats_instruments(self) -> List[str]:
        log.info("Stats per instrument:")

        telelog_message = list()

        for verdict, instruments_counters in self.stats_strategy.items():
            message = [
                f'> {verdict} ({instruments_counters["BULL"] + instruments_counters["BEAR"]}):',
                f'BULL: {instruments_counters["BULL"]}',
                f'/ BEAR: {instruments_counters["BEAR"]}',
            ]

            telelog_message.append(" ".join(message))

            log.info(telelog_message[-1])

        return telelog_message


class Calibration:
    def __init__(self, settings: dict, user: str):
        self.settings = settings

        self.ava = Context(user, settings["accounts"], skip_lists=True)

    def update(self) -> dict:
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
        
        #history.data = history.data[history.data.index < "2022-09-21"]

        strategy = Strategy_DT(
            history.data,
            order_price_limits=self.settings["trading"]["limits_percent"],
            iterate_candlestick_patterns=True
        )

        helper = Helper(self.settings)
        daily_volumes = history.data.groupby([history.data.index.date]).sum()["Volume"].values.tolist()  # type: ignore

        log.info(
            f"Dates range: {history.data.index[0].strftime('%Y.%m.%d')} - {history.data.index[-1].strftime('%Y.%m.%d')} "  # type: ignore
            + f"({history.data.shape[0]} rows) "
            + f"({len([i for i in daily_volumes if i > 0])} / {len(daily_volumes)} days with Volume)"
        )

        for i, pattern in enumerate(ALL_PATTERNS):
            data, column = strategy.get_one_candlestick_pattern(pattern)

            log.info(f'Pattern [{i+1}/{len(ALL_PATTERNS)}]: {column}')

            if (data[column] == 0).all():
                continue

            for ta_indicator_name, ta_indicator in strategy.ta_indicators.items():
                last_candle_signal = None

                for index, row in data[
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

        strategy.dump("DT", helper.filtered_strategies)

        return helper.strategies_efficiency

    def test(self, strategies_efficiency: dict) -> Tuple[pd.DataFrame, list]:
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

                        if signal is not None and (
                            signal == ("BUY" if instrument == "BULL" else "SELL")
                        ):
                            strategy_name = (
                                f"{cs_column} + {ta_indicator_name} - {instrument}"
                            )

                            log.warning(
                                f"{str(index)[5:16]} / {round(row['Close'], 2)} / {strategy_name} ({strategies_efficiency.get(strategy_name, '?')} %)"
                            )

                            signal_result = signal

            signals.append(signal_result)

        strategy.data["signal"] = signals

        telelog_message = helper.print_stats_instruments()

        return strategy.data, telelog_message

    def plot(self, data: pd.DataFrame) -> None:
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

                strategies_efficiency = dict()

                if setting_per_setup["calibration"]["update"]:
                    strategies_efficiency = calibration.update()

                data, telelog_message = calibration.test(strategies_efficiency)
                calibration.plot(data)

                TeleLog(
                    message=("DT calibration: done.\n" + "\n".join(telelog_message))
                )

            except Exception as e:
                log.error(f">>> {e}: {traceback.format_exc()}")

                TeleLog(crash_report=f"DT calibration: script has crashed: {e}")

            return
