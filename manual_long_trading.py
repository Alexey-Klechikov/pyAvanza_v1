import logging
import traceback

import pandas as pd
from avanza import OrderType as Signal

from module.lt.strategy import Strategy
from module.utils import Context, History, Logger, Plot, Settings, Cache

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

        settings = Settings().load("LT")
        self.ava = Context(
            user=settings["user"],
            accounts=settings["accounts"],
        )

        self.run_analysis(kwargs["check_only_watch_list"], kwargs["cache"])

        self.print_performance_per_strategy()
        self.print_performance_per_indicator()
        self.plot_performance_compared_to_hold(
            kwargs["plot_total_algo_performance_vs_hold"]
        )

    def _plot_ticker(self, strategy: Strategy) -> None:
        log.info(f"Plotting {strategy.summary.ticker_name}")

        plot = Plot(
            data=strategy.data,
            title=f"{strategy.summary.ticker_name} # {strategy.summary.max_output.strategy}",
        )
        plot.create_extra_panels()
        plot.add_orders_to_main_plot()
        plot.show_single_ticker()

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
                if col.startswith(column_category):  # type: ignore
                    columns_merge.append(col)

        for result_column, columns_to_merge in columns.items():
            self.data[result_column] = self.data[columns_to_merge].sum(axis=1)

        plot_obj = Plot(data=self.data, title="Total HOLD (red) vs Total algo (black)")
        plot_obj.show_entire_portfolio()

    def print_performance_per_strategy(self) -> None:
        log.info("Performance per strategy")

        for i, (strategy_name, strategy_stats) in enumerate(
            [["-- MAX --", str(self.counter_per_strategy.pop("-- MAX --"))]]
            + sorted(
                self.counter_per_strategy.items(),
                key=lambda x: int(x[1]["total_sum"]),
                reverse=True,
            )
        ):
            log.info(f"> {i+1}. {strategy_name}: {strategy_stats}")

    def print_performance_per_indicator(self) -> None:
        log.info("Performance per indicator")

        performance_per_indicator = {}

        for strategy, statistics in self.counter_per_strategy.items():
            counter = sum(statistics.get("win_counter", {0: 0}).values())  # type: ignore

            for indicator in strategy.split(" + "):
                performance_per_indicator.setdefault(indicator, 0)
                performance_per_indicator[indicator] += counter

        for i, (indicator_name, indicator_counter) in enumerate(
            sorted(performance_per_indicator.items(), key=lambda x: x[1], reverse=True)
        ):
            log.info(f"> {i+1}. {indicator_name}: {indicator_counter}")

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
                if (i.startswith("Close") or i.startswith("total"))  # type: ignore
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
            strategy = Strategy(
                History(
                    ticker_yahoo,
                    "18mo",
                    "1d",
                    cache=Cache.REUSE if cache else Cache.SKIP,
                    even=False,
                ).data,
                ticker_name=comment,
            )

        except Exception as exc:
            log.error(
                f'There was a problem with the ticker "{ticker_yahoo}": {exc} ({traceback.format_exc()})'
            )

            return

        if self.show_only_tickers_to_act_on and any(
            [
                strategy.summary.signal == Signal.BUY and in_portfolio,
                strategy.summary.signal == Signal.SELL and not in_portfolio,
            ]
        ):
            return

        # Print the result for all strategies AND count per strategy performance
        top_signal = strategy.summary.max_output.signal
        signal = strategy.summary.signal

        if top_signal != signal:
            log.warning(f"Signal override: {top_signal} ->> {signal}")

        max_output_summary = " / ".join(
            [
                f"signal: {signal.name}",
                f"result: {strategy.summary.max_output.result}",
                f"transactions_counter: {strategy.summary.max_output.transactions_counter}",
            ]
        )

        log.info(
            f"--- {strategy.summary.ticker_name} ({max_output_summary}) (HOLD: {strategy.summary.hold_result}) ---"
        )

        def _increment_counter(key1, key2, increment_value):
            self.counter_per_strategy.setdefault(key1, {}).setdefault(key2, 0)
            self.counter_per_strategy[key1][key2] += increment_value

        for key in ["result", "transactions_counter"]:
            _increment_counter("-- MAX --", key, strategy.summary.max_output.__getattribute__(key))  # type: ignore

        for i, (strategy_name, strategy_data) in enumerate(
            strategy.summary.sorted_strategies
        ):
            _increment_counter(strategy_name, "total_sum", strategy_data.result)
            _increment_counter(
                strategy_name, "transactions_counter", len(strategy_data.transactions)
            )

            if i < 20:
                log.info(
                    " ".join(
                        [
                            f"Strategy: {strategy_name} -> {strategy_data.result}",
                            f"(number_transactions: {len(strategy_data.transactions)})",
                            f"(signal: {strategy_data.signal.name})",
                        ]
                    )
                )
                if self.print_transactions:
                    for transaction in strategy_data.transactions:
                        log.info(transaction)

                win_counter: dict = self.counter_per_strategy[strategy_name].get(
                    "win_counter", {}
                )  # type: ignore

                win_counter[f"{i+1}"] = win_counter.get(f"{i+1}", 0) + 1
                self.counter_per_strategy[strategy_name]["win_counter"] = win_counter  # type: ignore

        # Plot
        if any(
            [
                self.plot_portfolio_tickers and in_portfolio,
                self.plot_tickers_to_act_on
                and any(
                    [
                        signal == Signal.SELL and in_portfolio,
                        signal == Signal.BUY and not in_portfolio,
                    ]
                ),
                ticker_yahoo in self.extra_tickers_plot,
            ]
        ):
            self._plot_ticker(strategy)

        # Create a DF with all best strategies vs HOLD
        self.record_ticker_performance(strategy, ticker_yahoo)

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
        plot_portfolio_tickers=False,
        plot_total_algo_performance_vs_hold=False,
        plot_tickers_to_act_on=False,
        cache=False,
    )
