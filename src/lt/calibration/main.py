import logging
import traceback

from src.lt.strategy import Strategy
from src.utils import Cache, Context, History, Settings, TeleLog

log = logging.getLogger("main.lt.calibration")


class Calibration:
    def __init__(self):
        settings = Settings().load("LT")

        self.ava = Context(settings["user"], settings["accounts"])
        self.logs = ["LT calibration:\n"]
        self.top_strategies_per_ticker: dict = {}

        self.run_analysis(settings["log_to_telegram"])

    def record_strategies(
        self, watch_list_name: str, ticker: str, strategy: Strategy
    ) -> None:
        max_output = strategy.summary.max_output.result

        self.top_strategies_per_ticker[ticker] = {
            "watch_list": watch_list_name,
            "max_output": max_output,
            "strategies": [i[0] for i in strategy.summary.sorted_strategies[:20]],
        }

    def run_analysis(self, log_to_telegram: bool) -> None:
        log.info("Run analysis")

        for watch_list_name, watch_list_item in self.ava.watch_lists.items():
            for ticker in watch_list_item["tickers"]:
                log.info(f'Ticker "{watch_list_name} / {ticker["ticker_yahoo"]}"')

                try:
                    data = History(
                        ticker["ticker_yahoo"],
                        "18mo",
                        "1d",
                        cache=Cache.SKIP,
                    ).data

                    if str(data.iloc[-1]["Close"]) == "nan":
                        self.ava.update_todays_ochl(data, ticker["order_book_id"])

                    strategy = Strategy(data)

                except Exception as e:
                    log.error(f"Error (run_analysis): {e} ({traceback.format_exc()})")

                    continue

                self.record_strategies(
                    watch_list_name, ticker["ticker_yahoo"], strategy
                )

        Strategy.dump("LT", self.top_strategies_per_ticker)

        if log_to_telegram:
            TeleLog(watch_lists_analysis_log=self.logs)


def run() -> None:
    try:
        Calibration()

    except Exception as e:
        log.error(f">>> {e}: {traceback.format_exc()}")

        TeleLog(crash_report=f"LT calibration: script has crashed: {e}")
