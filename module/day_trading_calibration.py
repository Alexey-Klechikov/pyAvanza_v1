import logging
import platform
import traceback
import pandas as pd
import yfinance as yf

from .utils import Plot
from .utils import Context
from .utils import History
from .utils import TeleLog
from .utils import Settings
from .utils import Instrument
from .utils import Strategy_DT


log = logging.getLogger("main.day_trading_calibration")


class Calibration:
    def __init__(self, instrument_ids: dict, settings: dict, user: str):
        self.settings_price_limits = settings["trading"]["limits"]
        self.calibration = settings["calibration"]

        self.instrument_ids = instrument_ids

        self.ava = Context(user, settings["accounts"], skip_lists=True)

        self.update_strategies()
        data = self.test_strategies()
        self.plot_strategies(data)

    def update_strategies(self) -> None:
        if not self.calibration["update"]:
            return

        log.info(
            f"Updating strategies: "
            + str(self.settings_price_limits)
            + f' success_limit: {self.calibration["success_limit"]}'
        )

        extra_data = self.ava.get_today_history(self.instrument_ids["AVA"])

        history = History(
            self.instrument_ids["YAHOO"],
            "90d",
            "1m",
            cache="append",
            extra_data=extra_data,
        )

        log.info(
            f"Dates range: {history.data.index[0].strftime('%Y.%m.%d')} - {history.data.index[-1].strftime('%Y.%m.%d')} ({history.data.shape[0]} rows)"  # type: ignore
        )

        strategy = Strategy_DT(
            history.data,
            order_price_limits=self.settings_price_limits,
        )

        strategies = strategy.get_successful_strategies(
            self.calibration["success_limit"]
        )

        strategy.dump("DT", strategies)

    def test_strategies(self) -> pd.DataFrame:
        log.info(f"Testing strategies")

        history = History(self.instrument_ids["YAHOO"], "2d", "1m", cache="skip")

        strategy = Strategy_DT(
            history.data,
            order_price_limits=self.settings_price_limits,
        )

        strategies = strategy.load("DT")

        strategy.backtest_strategies(strategies)

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
                instrument = Instrument(setting_per_setup["trading"]["multiplier"])

                Calibration(instrument.ids["MONITORING"], setting_per_setup, user)

                TeleLog(message=f"DT calibration: done.")

            except Exception as e:
                log.error(f">>> {e}: {traceback.format_exc()}")

                TeleLog(crash_report=f"DT calibration: script has crashed: {e}")

            return
