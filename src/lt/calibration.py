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
        self.top_strategies_per_ticket: dict = {}

        self.run_analysis(
            settings["log_to_telegram"], settings["budget_list_thresholds"]
        )

    def record_strategies(self, ticker: str, strategy: Strategy) -> None:
        log.debug("Record strategies")

        for strategy_item in strategy.summary.sorted_strategies[:20]:
            self.top_strategies_per_ticket.setdefault(ticker, []).append(
                strategy_item[0]
            )

    def move_ticker_to_suitable_budget_list(
        self,
        initial_watch_list_name: str,
        ticker: dict,
        max_output: float,
        budget_list_thresholds: dict,
    ) -> str:
        max_outputs = [int(i) for i in budget_list_thresholds if max_output > int(i)]
        target_watch_list_name = (
            "skip"
            if len(max_outputs) == 0
            else budget_list_thresholds[str(max(max_outputs))]
        )

        def _get_watch_list_id(watch_list_name: str) -> str:
            if watch_list_name in self.ava.watch_lists:
                return self.ava.watch_lists[watch_list_name]["watch_list_id"]

            return self.ava.budget_rules[watch_list_name]["watch_list_id"]

        if target_watch_list_name != initial_watch_list_name:
            log.info("Move ticker to suitable budget list")

            self.ava.ctx.add_to_watchlist(
                ticker["order_book_id"], _get_watch_list_id(target_watch_list_name)
            )

            self.ava.ctx.remove_from_watchlist(
                ticker["order_book_id"], _get_watch_list_id(initial_watch_list_name)
            )

            message = f'"{initial_watch_list_name}" -> "{target_watch_list_name}" ({ticker["name"]}) [{max_output}]'

            log.warning(f"> {message}")

            self.logs.append(message)

        return target_watch_list_name

    def run_analysis(self, log_to_telegram: bool, budget_list_thresholds: dict) -> None:
        log.info("Run analysis")

        watch_lists = [
            ("budget rules", self.ava.budget_rules),
            ("watch_lists", self.ava.watch_lists),
        ]

        for watch_list_type, watch_list in watch_lists:
            log.info(f"Walk through {watch_list_type}")

            for watch_list_name, watch_list_item in watch_list.items():
                for ticker in watch_list_item["tickers"]:
                    log.info(f'Ticker "{ticker["ticker_yahoo"]}"')

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
                        log.error(
                            f"Error (run_analysis): {e} ({traceback.format_exc()})"
                        )

                        continue

                    max_output = strategy.summary.max_output.result
                    log.info(f"{watch_list_name}: Max output = {max_output}")

                    target_watch_list_name = self.move_ticker_to_suitable_budget_list(
                        initial_watch_list_name=watch_list_name,
                        ticker=ticker,
                        max_output=max_output,
                        budget_list_thresholds=budget_list_thresholds,
                    )

                    if target_watch_list_name != "skip":
                        self.record_strategies(ticker["ticker_yahoo"], strategy)

        Strategy.dump("LT", self.top_strategies_per_ticket)

        if log_to_telegram:
            TeleLog(watch_lists_analysis_log=self.logs)


def run() -> None:
    try:
        Calibration()

    except Exception as e:
        log.error(f">>> {e}: {traceback.format_exc()}")

        TeleLog(crash_report=f"LT calibration: script has crashed: {e}")
