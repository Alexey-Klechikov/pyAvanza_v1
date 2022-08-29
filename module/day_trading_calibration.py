import logging
import platform
import traceback
import yfinance as yf

from .utils import Plot
from .utils import History
from .utils import TeleLog
from .utils import Settings
from .utils import Instrument
from .utils import Strategy_DT


log = logging.getLogger("main.day_trading_calibration")


class Calibration:
    def __init__(self, instrument_id, settings_dict):
        self.settings_price_limits_dict = settings_dict["trade_dict"]["limits_dict"]
        self.recalibrate_dict = settings_dict["recalibrate_dict"]

        self.instrument_id = instrument_id

        self.update_strategies()
        history_df = self.test_strategies()
        self.plot_strategies(history_df)

    def update_strategies(self):
        if not self.recalibrate_dict["update_bool"]:
            return

        log.info(
            f"Updating strategies_dict: "
            + str(self.settings_price_limits_dict)
            + f' success_limit: {self.recalibrate_dict["success_limit"]}'
        )

        history_obj = History(self.instrument_id, "90d", "1m", cache="append")

        log.info(
            f"Dates range: {history_obj.history_df.index[0].strftime('%Y.%m.%d')} - {history_obj.history_df.index[-1].strftime('%Y.%m.%d')}"  # type: ignore
        )

        strategy_obj = Strategy_DT(
            history_obj.history_df,
            order_price_limits_dict=self.settings_price_limits_dict,
        )

        strategies_dict = strategy_obj.get_successful_strategies(
            self.recalibrate_dict["success_limit"]
        )

        strategy_obj.dump("DT", strategies_dict)

    def test_strategies(self):
        log.info(f"Testing strategies")

        history_obj = History(self.instrument_id, "2d", "1m", cache="skip")

        strategy_obj = Strategy_DT(
            history_obj.history_df,
            order_price_limits_dict=self.settings_price_limits_dict,
        )

        strategies_dict = strategy_obj.load("DT")

        strategy_obj.backtest_strategies(strategies_dict)

        return strategy_obj.history_df

    def plot_strategies(self, history_df):
        if platform.system() != "Darwin":
            return

        history_df["buy_signal"] = history_df.apply(
            lambda x: x["High"] if x["signal"] == "BUY" else None, axis=1
        )
        history_df["sell_signal"] = history_df.apply(
            lambda x: x["Low"] if x["signal"] == "SELL" else None, axis=1
        )

        plot_obj = Plot(
            data_df=history_df,
            title=f"Signals",
        )
        plot_obj.add_orders_to_main_plot()
        plot_obj.show_single_ticker()


def run():
    settings_json = Settings().load()

    for _, settings_per_account_dict in settings_json.items():
        for settings_dict in settings_per_account_dict.values():
            if not settings_dict.get("run_day_trading", False):
                continue

            try:
                settings_trade_dict = settings_dict["trade_dict"]
                instruments_obj = Instrument(settings_trade_dict["multiplier"])

                Calibration(
                    instruments_obj.ids_dict["MONITORING"]["YAHOO"], settings_dict
                )

                TeleLog(message=f"DT calibration is done.")

            except Exception as e:
                log.error(f">>> {e}: {traceback.format_exc()}")

                TeleLog(crash_report=f"DT_calibration script has crashed: {e}")

            return
