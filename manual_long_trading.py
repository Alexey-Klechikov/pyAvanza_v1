"""
This module is used for manual runs (checkups, improvements, tests)
"""


import logging
import traceback
import pandas as pd

from module.utils import Plot
from module.utils import Logger
from module.utils import History
from module.utils import Context
from module.utils import Settings
from module.utils import Strategy_TA


log = logging.getLogger("main")


class Portfolio_Analysis:
    def __init__(self, **kwargs):
        self.total_df = None
        self.visited_tickers = list()
        self.counter_per_strategy_dict = {
            "-- MAX --": {"result": 0, "transactions_counter": 0}
        }

        self.plot_extra_tickers_list = kwargs["plot_extra_tickers_list"]
        self.plot_portfolio_tickers_bool = kwargs["plot_portfolio_tickers_bool"]
        self.print_transactions_bool = kwargs["print_transactions_bool"]

        self.show_only_tickers_to_act_on_bool = kwargs[
            "show_only_tickers_to_act_on_bool"
        ]
        self.plot_tickers_to_act_on_bool = kwargs["plot_tickers_to_act_on_bool"]

        self.ava = self.get_settings_and_context()

        self.run_analysis(kwargs["check_only_watchlist_bool"], kwargs["cache"])
        self.print_performance_per_strategy()
        self.print_performance_per_indicator()
        self.plot_performance_compared_to_hold(
            kwargs["plot_total_algo_performance_vs_hold_bool"]
        )

    def plot_ticker(self, strategy_obj):
        log.info(f'Plotting {strategy_obj.summary["ticker_name"]}')

        plot_obj = Plot(
            data_df=strategy_obj.history_df,
            title=f'{strategy_obj.summary["ticker_name"]} # {strategy_obj.summary["max_output"]["strategy"]}',
        )
        plot_obj.create_extra_panels()
        plot_obj.add_orders_to_main_plot()
        plot_obj.show_single_ticker()

    def plot_performance_compared_to_hold(
        self, plot_total_algo_performance_vs_hold_bool
    ):
        if not plot_total_algo_performance_vs_hold_bool:
            return

        log.info(f"Plotting total algo performance vs hold")

        columns_dict = {"Close": list(), "total": list()}

        if not isinstance(self.total_df, pd.DataFrame) or self.total_df.empty:
            log.error("No total_df found")
            return

        for col in self.total_df.columns:
            for column_to_merge in columns_dict:
                if col.startswith(column_to_merge):
                    columns_dict[column_to_merge].append(col)

        for result_column, columns_to_merge_list in columns_dict.items():
            self.total_df[result_column] = self.total_df[columns_to_merge_list].sum(
                axis=1
            )

        plot_obj = Plot(
            data_df=self.total_df, title=f"Total HOLD (red) vs Total algo (black)"
        )
        plot_obj.show_entire_portfolio()

    def print_performance_per_strategy(self):
        log.info(f"Performance per strategy")

        result_dict = self.counter_per_strategy_dict.pop("-- MAX --")
        result_message = [f"-- MAX -- : {str(result_dict)}"]
        sorted_strategies_list = sorted(
            self.counter_per_strategy_dict.items(),
            key=lambda x: int(x[1]["total_sum"]),
            reverse=True,
        )

        log.info(
            "\n".join(
                result_message
                + [
                    f"{i+1}. {strategy[0]}: {strategy[1]}"
                    for i, strategy in enumerate(sorted_strategies_list)
                ]
            )
        )

    def print_performance_per_indicator(self):
        log.info(f"Performance per indicator")

        performance_per_indicator_dict = dict()
        for strategy, statistics_dict in self.counter_per_strategy_dict.items():
            counter = 0
            if statistics_dict.get("win_counter") and isinstance(statistics_dict["win_counter"], dict):
                counter = sum(statistics_dict["win_counter"].values())

            for indicator in strategy.split(" + "):
                performance_per_indicator_dict.setdefault(indicator, 0)
                performance_per_indicator_dict[indicator] += counter

        sorted_indicators_list = sorted(
            performance_per_indicator_dict.items(), key=lambda x: x[1], reverse=True
        )

        log.info(
            "\n".join(
                [
                    f"{i+1}. {indicator[0]}: {indicator[1]}"
                    for i, indicator in enumerate(sorted_indicators_list)
                ]
            )
        )

    def record_ticker_performance(self, strategy_obj, ticker):
        log.info(f"Recording performance for {ticker}")

        self.total_df = (
            strategy_obj.history_df
            if self.total_df is None
            else pd.merge(
                self.total_df,
                strategy_obj.history_df,
                how="outer",
                left_index=True,
                right_index=True,
            )
        )

        first_value = self.total_df["Close"].values[0]
        if first_value:
            self.total_df["Close"] = self.total_df["Close"] / (first_value / 1000)

        self.total_df.rename(
            columns={
                "Close": f"Close / {ticker}",
                "total": f'total / {ticker} / {strategy_obj.summary["max_output"]["strategy"]}',
            },
            inplace=True,
        )

        self.total_df = self.total_df[
            [
                i
                for i in self.total_df.columns
                if (i.startswith("Close") or i.startswith("total"))
            ]
        ]

    def get_strategy_on_ticker(
        self, ticker_yahoo, ticker_ava, comment, in_portfolio_bool, cache
    ):
        if ticker_yahoo not in self.visited_tickers:
            log.info(f"Getting strategy on {ticker_yahoo}")
            self.visited_tickers.append(ticker_yahoo)
        else:
            return

        try:
            history_df = History(
                ticker_yahoo, "18mo", "1d", cache="reuse" if cache else "skip"
            ).history_df

            strategy_obj = Strategy_TA(history_df, ticker_name=comment)

        except Exception as e:
            log.error(f'There was a problem with the ticker "{ticker_yahoo}": {e} ({traceback.format_exc()})')
            return

        if self.show_only_tickers_to_act_on_bool and (
            (in_portfolio_bool and strategy_obj.summary["signal"] == "buy")
            or (not in_portfolio_bool and strategy_obj.summary["signal"] == "sell")
        ):
            return

        # Print the result for all strategies AND count per strategy performance
        top_signal = strategy_obj.summary["max_output"].pop("signal")
        signal = strategy_obj.summary["signal"]

        if top_signal != signal:
            signal = f"{top_signal} ->> {signal}"
            log.warning(f"Signal override: {signal}")

        max_output_summary = f"signal: {signal} / " + " / ".join(
            [
                f"{k}: {v}"
                for k, v in strategy_obj.summary["max_output"].items()
                if k in ("result", "transactions_counter")
            ]
        )
        log.info(
            f'--- {strategy_obj.summary["ticker_name"]} ({max_output_summary}) (HOLD: {strategy_obj.summary["hold_result"]}) ---'
        )

        for parameter in ("result", "transactions_counter"):
            self.counter_per_strategy_dict["-- MAX --"][
                parameter
            ] += strategy_obj.summary["max_output"][parameter]

        for i, strategy_item_list in enumerate(
            strategy_obj.summary["sorted_strategies_list"]
        ):
            strategy, strategy_data_dict = strategy_item_list[0], strategy_item_list[1]

            self.counter_per_strategy_dict.setdefault(
                strategy, {"total_sum": 0, "transactions_counter": 0}
            )
            self.counter_per_strategy_dict[strategy]["total_sum"] += strategy_data_dict[
                "result"
            ]
            self.counter_per_strategy_dict[strategy]["transactions_counter"] += len(
                strategy_data_dict["transactions"]
            )

            if i < 3:
                log.info(
                    f'Strategy: {strategy} -> {strategy_data_dict["result"]} (number_transactions: {len(strategy_data_dict["transactions"])}) (signal: {strategy_data_dict["signal"]})'
                )
                [
                    log.info(t)
                    for t in strategy_data_dict["transactions"]
                    if self.print_transactions_bool
                ]

                win_counter_dict = self.counter_per_strategy_dict[strategy].get(
                    "win_counter", dict()
                )
                if not isinstance(win_counter_dict, dict):
                    win_counter_dict = dict()
                win_counter_dict[f"{i+1}"] = win_counter_dict.get(f"{i+1}", 0) + 1
                self.counter_per_strategy_dict[strategy]["win_counter"] = win_counter_dict  # type: ignore

        # Plot
        plot_conditions_list = [
            ticker_yahoo in self.plot_extra_tickers_list,
            in_portfolio_bool and self.plot_portfolio_tickers_bool,
            (in_portfolio_bool and signal == "sell")
            and self.plot_tickers_to_act_on_bool,
            (not in_portfolio_bool and signal == "buy")
            and self.plot_tickers_to_act_on_bool,
        ]
        if any(plot_conditions_list):
            self.plot_ticker(strategy_obj)

        # Create a DF with all best strategies vs HOLD
        self.record_ticker_performance(strategy_obj, ticker_yahoo)

    def get_settings_and_context(self):
        log.info("Getting settings and context")

        settings_obj = Settings()
        settings_json = settings_obj.load()

        return Context(
            user=list(settings_json.keys())[0],
            accounts_dict=list(settings_json.values())[0]["1"]["accounts"],
        )

    def run_analysis(self, check_only_watchlist_bool, cache):
        log.info("Running analysis")

        if check_only_watchlist_bool:
            log.info("Checking watch_list")
            for watchlist_name, tickers_list in self.ava.watchlists_dict.items():
                for ticker_dict in tickers_list:
                    self.get_strategy_on_ticker(
                        ticker_dict["ticker_yahoo"],
                        ticker_dict["order_book_id"],
                        f"Watchlist ({watchlist_name}): {ticker_dict['ticker_yahoo']}",
                        in_portfolio_bool=False,
                        cache=cache,
                    )
        else:
            log.info("Checking portfolio")
            if self.ava.portfolio_dict["positions"]["df"] is not None:
                for _, row in self.ava.portfolio_dict["positions"]["df"].iterrows():
                    self.get_strategy_on_ticker(
                        row["ticker_yahoo"],
                        row["orderbookId"],
                        f"Stock: {row['name']} - {row['ticker_yahoo']}",
                        in_portfolio_bool=True,
                        cache=cache,
                    )

            log.info("Checking budget_lists")
            for budget_rule_name, watchlist_dict in self.ava.budget_rules_dict.items():
                for ticker_dict in watchlist_dict["tickers"]:
                    self.get_strategy_on_ticker(
                        ticker_dict["ticker_yahoo"],
                        ticker_dict["order_book_id"],
                        f"Budget ({budget_rule_name}K): {ticker_dict['ticker_yahoo']}",
                        in_portfolio_bool=False,
                        cache=cache,
                    )


if __name__ == "__main__":
    Logger(logger_name="main", file_prefix="manual_long_trading")

    Portfolio_Analysis(
        check_only_watchlist_bool=False,
        show_only_tickers_to_act_on_bool=False,
        print_transactions_bool=False,
        plot_extra_tickers_list=[],
        plot_portfolio_tickers_bool=False,
        plot_total_algo_performance_vs_hold_bool=True,
        plot_tickers_to_act_on_bool=False,
        cache=True,
    )
