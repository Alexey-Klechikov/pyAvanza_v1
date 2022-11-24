"""
This module is used for manual runs (checkups, improvements, tests)
"""


import logging
import traceback

import pandas as pd
from avanza import OrderType as Signal

from module.long_trading_TA import Strategy
from module.utils import Context, History, Logger, Plot, Settings

log = logging.getLogger("main")


class PortfolioAnalysis:
    def __init__(self, **kwargs):
        self.data = pd.DataFrame()
        self.visited_tickers = []
        self.counter_per_strategy = {
            "-- MAX --": {"result": 0.0, "transactions_counter": 0.0}
        }

        self.extra_tickers_plot = kwargs["extra_tickers_plot"]
        self.plot_portfolio_tickers = kwargs["plot_portfolio_tickers"]
        self.print_transactions = kwargs["print_transactions"]

        self.show_only_tickers_to_act_on = kwargs["show_only_tickers_to_act_on"]
        self.plot_tickers_to_act_on = kwargs["plot_tickers_to_act_on"]

        self.ava = self.get_settings_and_context()

        self.run_analysis(kwargs["check_only_watch_list"], kwargs["cache"])
        self.print_performance_per_strategy()
        self.print_performance_per_indicator()
        self.plot_performance_compared_to_hold(
            kwargs["plot_total_algo_performance_vs_hold"]
        )

    def plot_ticker(self, strategy: Strategy) -> None:
        log.info(f"Plotting {strategy.summary.ticker_name}")

        plot_obj = Plot(
            data=strategy.data,
            title=f"{strategy.summary.ticker_name} # {strategy.summary.max_output.strategy}",
        )
        plot_obj.create_extra_panels()
        plot_obj.add_orders_to_main_plot()
        plot_obj.show_single_ticker()

    def plot_performance_compared_to_hold(
        self, plot_total_algo_performance_vs_hold: bool
    ) -> None:
        if not plot_total_algo_performance_vs_hold:
            return

        log.info("Plotting total algo performance vs hold")

        columns = {"Close": [], "total": []}

        if not isinstance(self.data, pd.DataFrame) or self.data.empty:
            log.error("No data found")
            return

        for col in self.data.columns:
            for column_category, columns_merge in columns.items():
                if col.startswith(column_category):
                    columns_merge.append(col)

        for result_column, columns_to_merge in columns.items():
            self.data[result_column] = self.data[columns_to_merge].sum(axis=1)

        plot_obj = Plot(data=self.data, title="Total HOLD (red) vs Total algo (black)")
        plot_obj.show_entire_portfolio()

    def print_performance_per_strategy(self) -> None:
        log.info("Performance per strategy")

        result = self.counter_per_strategy.pop("-- MAX --")
        result_message = [f"-- MAX -- : {str(result)}"]
        sorted_strategies = sorted(
            self.counter_per_strategy.items(),
            key=lambda x: int(x[1]["total_sum"]),
            reverse=True,
        )

        log.info(
            "\n".join(
                result_message
                + [
                    f"{i+1}. {strategy[0]}: {strategy[1]}"
                    for i, strategy in enumerate(sorted_strategies)
                ]
            )
        )

    def print_performance_per_indicator(self) -> None:
        log.info("Performance per indicator")

        performance_per_indicator = {}

        for strategy, statistics in self.counter_per_strategy.items():
            counter = 0

            if statistics.get("win_counter") and isinstance(
                statistics["win_counter"], dict
            ):
                counter = sum(statistics["win_counter"].values())

            for indicator in strategy.split(" + "):
                performance_per_indicator.setdefault(indicator, 0)
                performance_per_indicator[indicator] += counter

        sorted_indicators = sorted(
            performance_per_indicator.items(), key=lambda x: x[1], reverse=True
        )

        log.info(
            "\n".join(
                [
                    f"{i+1}. {indicator[0]}: {indicator[1]}"
                    for i, indicator in enumerate(sorted_indicators)
                ]
            )
        )

    def record_ticker_performance(self, strategy: Strategy, ticker: str) -> None:
        log.info(f"Recording performance for {ticker}")

        self.data = (
            strategy.data
            if self.data is None
            else pd.merge(
                self.data,
                strategy.data,
                how="outer",
                left_index=True,
                right_index=True,
            )
        )

        first_value = self.data["Close"].values[0]
        if first_value:
            self.data["Close"] = self.data["Close"] / (first_value / 1000)

        self.data.rename(
            columns={
                "Close": f"Close / {ticker}",
                "total": f"total / {ticker} / {strategy.summary.max_output.strategy}",
            },
            inplace=True,
        )

        self.data = self.data[
            [
                i
                for i in self.data.columns
                if (i.startswith("Close") or i.startswith("total"))
            ]
        ]

    def get_strategy_on_ticker(
        self,
        ticker_yahoo: str,
        comment: str,
        in_portfolio: bool,
        cache: str,
    ) -> None:
        if ticker_yahoo not in self.visited_tickers:
            log.info(f"Getting strategy on {ticker_yahoo}")
            self.visited_tickers.append(ticker_yahoo)

        else:
            return

        try:
            data = History(
                ticker_yahoo, "18mo", "1d", cache="reuse" if cache else "skip"
            ).data

            strategy = Strategy(data, ticker_name=comment)

        except Exception as exc:
            log.error(
                f'There was a problem with the ticker "{ticker_yahoo}": {exc} ({traceback.format_exc()})'
            )

            return

        if self.show_only_tickers_to_act_on and (
            (in_portfolio and strategy.summary.signal == Signal.BUY)
            or (not in_portfolio and strategy.summary.signal == Signal.SELL)
        ):
            return

        # Print the result for all strategies AND count per strategy performance
        top_signal = strategy.summary.max_output.signal
        signal = strategy.summary.signal

        if top_signal != signal:
            log.warning(f"Signal override: {top_signal} ->> {signal}")

        max_output_summary = " / ".join(
            [
                "signal: " + str(signal.name),
                "result: " + str(strategy.summary.max_output.result),
                "transactions_counter: "
                + str(strategy.summary.max_output.transactions_counter),
            ]
        )

        log.info(
            f"--- {strategy.summary.ticker_name} ({max_output_summary}) (HOLD: {strategy.summary.hold_result}) ---"
        )

        self.counter_per_strategy["-- MAX --"][
            "result"
        ] += strategy.summary.max_output.result
        self.counter_per_strategy["-- MAX --"][
            "transactions_counter"
        ] += strategy.summary.max_output.transactions_counter

        for i, strategy_items in enumerate(strategy.summary.sorted_strategies):
            strategy_name, strategy_data = strategy_items[0], strategy_items[1]

            self.counter_per_strategy.setdefault(
                strategy_name, {"total_sum": 0, "transactions_counter": 0}
            )
            self.counter_per_strategy[strategy_name][
                "total_sum"
            ] += strategy_data.result
            self.counter_per_strategy[strategy_name]["transactions_counter"] += len(
                strategy_data.transactions
            )

            if i < 3:
                log.info(
                    f"Strategy: {strategy_name} -> {strategy_data.result} (number_transactions: {len(strategy_data.transactions)}) (signal: {strategy_data.signal.name})"
                )
                [
                    log.info(transaction)
                    for transaction in strategy_data.transactions
                    if self.print_transactions
                ]

                win_counter = self.counter_per_strategy[strategy_name].get(
                    "win_counter", {}
                )
                if not isinstance(win_counter, dict):
                    win_counter = {}

                win_counter[f"{i+1}"] = win_counter.get(f"{i+1}", 0) + 1
                self.counter_per_strategy[strategy_name]["win_counter"] = win_counter  # type: ignore

        # Plot
        plot_conditions = [
            ticker_yahoo in self.extra_tickers_plot,
            in_portfolio and self.plot_portfolio_tickers,
            (in_portfolio and signal == Signal.SELL) and self.plot_tickers_to_act_on,
            (not in_portfolio and signal == Signal.BUY) and self.plot_tickers_to_act_on,
        ]
        if any(plot_conditions):
            self.plot_ticker(strategy)

        # Create a DF with all best strategies vs HOLD
        self.record_ticker_performance(strategy, ticker_yahoo)

    def get_settings_and_context(self) -> Context:
        log.info("Getting settings and context")

        settings = Settings().load()

        return Context(
            user=list(settings.keys())[0],
            accounts=list(settings.values())[0]["1"]["accounts"],
        )

    def run_analysis(self, check_only_watch_list: bool, cache: str) -> None:
        log.info("Running analysis")

        if check_only_watch_list:
            log.info("Checking watch_list")
            for watch_list_name, watch_list in self.ava.watch_lists.items():
                for ticker in watch_list["tickers"]:
                    self.get_strategy_on_ticker(
                        ticker["ticker_yahoo"],
                        f"Watchlist ({watch_list_name}): {ticker['ticker_yahoo']}",
                        in_portfolio=False,
                        cache=cache,
                    )
        else:
            log.info("Checking portfolio")
            if self.ava.portfolio.positions.df is not None:
                for _, row in self.ava.portfolio.positions.df.iterrows():
                    self.get_strategy_on_ticker(
                        row["ticker_yahoo"],
                        f"Stock: {row['name']} - {row['ticker_yahoo']}",
                        in_portfolio=True,
                        cache=cache,
                    )

            log.info("Checking budget_lists")
            for budget_rule_name, watch_list in self.ava.budget_rules.items():
                for ticker in watch_list["tickers"]:
                    self.get_strategy_on_ticker(
                        ticker["ticker_yahoo"],
                        f"Budget ({budget_rule_name}K): {ticker['ticker_yahoo']}",
                        in_portfolio=False,
                        cache=cache,
                    )


if __name__ == "__main__":
    Logger(logger_name="main", file_prefix="manual_long_trading")

    PortfolioAnalysis(
        check_only_watch_list=False,
        show_only_tickers_to_act_on=False,
        print_transactions=False,
        extra_tickers_plot=[],
        plot_portfolio_tickers=True,
        plot_total_algo_performance_vs_hold=False,
        plot_tickers_to_act_on=False,
        cache=False,
    )
