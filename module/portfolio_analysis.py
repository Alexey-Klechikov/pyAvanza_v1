"""
This module is the "frontend" meant for everyday run. It will perform analysis on stocks and trigger trades.
It will import other modules to run the analysis on the stocks -> place orders -> dump log in Telegram.py
"""

import logging

from .utils import Settings
from .utils import Strategy
from .utils import Context
from .utils import TeleLog


log = logging.getLogger("main.portfolio_analysis")


class Portfolio_Analysis:
    def __init__(self, **kwargs):
        self.strategies_dict = Strategy.load("TA")
        self.signals_dict = kwargs.get("signals_dict", dict())

        self.ava = Context(kwargs["user"], kwargs["accounts_dict"])
        self.run_analysis(kwargs["accounts_dict"], kwargs["log_to_telegram"])

    def get_signal_on_ticker(self, ticker_yahoo, ticker_ava):
        log.info(f'Getting signal for ticker "{ticker_yahoo}"')

        if ticker_yahoo not in self.signals_dict:
            try:
                strategy_obj = Strategy(
                    ticker_yahoo,
                    ticker_ava,
                    self.ava,
                    strategies_list=self.strategies_dict.get(ticker_yahoo, list()),
                )
            except Exception as e:
                log.error(f'There was a problem with the ticker "{ticker_yahoo}": {e}')
                return None

            self.signals_dict[ticker_yahoo] = {
                "signal": strategy_obj.summary["signal"],
                "return": strategy_obj.summary["max_output"]["result"],
            }

        return self.signals_dict[ticker_yahoo]

    def create_sell_orders(self):
        log.info(f"Walk through portfolio (sell)")

        orders_list, portfolio_tickers_dict = list(), dict()
        if self.ava.portfolio_dict["positions"]["df"] is not None:
            for i, row in self.ava.portfolio_dict["positions"]["df"].iterrows():
                log.info(
                    f'Portfolio ({int(i) + 1}/{self.ava.portfolio_dict["positions"]["df"].shape[0]}): {row["ticker_yahoo"]}'
                )

                portfolio_tickers_dict[row["ticker_yahoo"]] = {"row": row}

                signal_dict = self.get_signal_on_ticker(
                    row["ticker_yahoo"], row["orderbookId"]
                )
                if signal_dict is None or signal_dict["signal"] == "buy":
                    continue

                log.info("> SELL")
                orders_list.append(
                    {
                        "account_id": row["accountId"],
                        "order_book_id": row["orderbookId"],
                        "volume": row["volume"],
                        "price": row["lastPrice"],
                        "profit": row["profitPercent"],
                        "name": row["name"],
                        "ticker_yahoo": row["ticker_yahoo"],
                        "max_return": signal_dict["return"],
                    }
                )

        self.ava.create_orders(orders_list, "sell")

        return orders_list, portfolio_tickers_dict

    def create_buy_orders(self, portfolio_tickers_dict):
        log.info(f"Walk through budget lists (buy)")

        orders_list = list()
        for budget_rule_name, watchlist_dict in self.ava.budget_rules_dict.items():
            for ticker_dict in watchlist_dict["tickers"]:
                if ticker_dict["ticker_yahoo"] in portfolio_tickers_dict:
                    portfolio_tickers_dict[ticker_dict["ticker_yahoo"]]["budget"] = (
                        int(budget_rule_name) * 1000
                    )

                    continue

                log.info(
                    f'> Budget list "{budget_rule_name}": {ticker_dict["ticker_yahoo"]}'
                )

                signal_dict = self.get_signal_on_ticker(
                    ticker_dict["ticker_yahoo"], ticker_dict["order_book_id"]
                )
                if signal_dict is None or signal_dict["signal"] == "sell":
                    continue

                stock_price_dict = self.ava.get_stock_price(
                    ticker_dict["order_book_id"]
                )
                try:
                    volume = int(
                        int(budget_rule_name) * 1000 // stock_price_dict["buy"]
                    )
                except:
                    log.error(
                        f"There was a problem with fetching buy price for {ticker_dict['ticker_yahoo']}"
                    )
                    continue

                log.info("> BUY")
                orders_list.append(
                    {
                        "ticker_yahoo": ticker_dict["ticker_yahoo"],
                        "order_book_id": ticker_dict["order_book_id"],
                        "budget": int(budget_rule_name) * 1000,
                        "price": stock_price_dict["buy"],
                        "volume": volume,
                        "name": ticker_dict["name"],
                        "max_return": signal_dict["return"],
                    }
                )

        created_orders_list = self.ava.create_orders(orders_list, "buy")

        return created_orders_list, portfolio_tickers_dict

    def create_take_profit_orders(
        self, portfolio_tickers_dict, created_sell_orders_list
    ):
        log.info(f"Walk through portfolio (take profit)")

        for sell_order_dict in created_sell_orders_list:
            if sell_order_dict["ticker_yahoo"] in portfolio_tickers_dict:
                portfolio_tickers_dict.pop(sell_order_dict["ticker_yahoo"])

        orders_list = list()
        for ticker_dict in portfolio_tickers_dict.values():
            ticker_row, ticker_budget = ticker_dict["row"], ticker_dict.get(
                "budget", None
            )

            if ticker_budget is None:
                log.error(f'Ticker "{ticker_row["ticker_yahoo"]}" has no budget')
                continue

            log.info(f'> Checking ticker: {ticker_row["ticker_yahoo"]}')

            volume_sell = (
                ticker_row["value"] - max(ticker_row["acquiredValue"], ticker_budget)
            ) // ticker_row["lastPrice"]

            skip_conditions_list = [ticker_row["profitPercent"] < 10, volume_sell <= 0]

            if any(skip_conditions_list):
                continue

            log.info("> TAKE PROFIT")
            orders_list.append(
                {
                    "account_id": ticker_row["accountId"],
                    "order_book_id": ticker_row["orderbookId"],
                    "volume": volume_sell,
                    "price": ticker_row["lastPrice"],
                    "profit": round(
                        (
                            (volume_sell * ticker_row["lastPrice"])
                            / max(ticker_row["acquiredValue"], ticker_budget)
                        )
                        * 100,
                        1,
                    ),
                    "name": ticker_row["name"],
                    "ticker_yahoo": ticker_row["ticker_yahoo"],
                }
            )

        self.ava.create_orders(orders_list, "take_profit")

        return orders_list

    def run_analysis(self, accounts_dict, log_to_telegram):
        log.info(f'Running analysis for account(s): {" & ".join(accounts_dict)}')
        self.ava.remove_active_orders(account_ids_list=list(accounts_dict.values()))

        created_orders_dict = dict()
        created_orders_dict["sell"], portfolio_tickers_dict = self.create_sell_orders()
        created_orders_dict["buy"], portfolio_tickers_dict = self.create_buy_orders(
            portfolio_tickers_dict
        )
        created_orders_dict["take_profit"] = self.create_take_profit_orders(
            portfolio_tickers_dict, created_orders_dict["sell"]
        )

        # Dump log to Telegram
        if log_to_telegram:
            log_obj = TeleLog(
                portfolio_dict=self.ava.get_portfolio(), orders_dict=created_orders_dict
            )
            log_obj.dump_to_telegram()


def run():
    settings_json = Settings().load()

    signals_dict = dict()
    for user, settings_per_account_dict in settings_json.items():
        for settings_dict in settings_per_account_dict.values():
            if not settings_dict["run_script_daily"]:
                continue

            walkthrough_obj = Portfolio_Analysis(
                user=user,
                accounts_dict=settings_dict["accounts"],
                signals_dict=signals_dict,
                log_to_telegram=settings_dict.get("log_to_telegram", True),
                buy_delay_after_sell=settings_dict.get("buy_delay_after_sell", 2),
            )
            signals_dict = walkthrough_obj.signals_dict
