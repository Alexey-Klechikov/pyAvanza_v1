"""
This module is the "frontend" meant for everyday run. It will perform analysis on stocks and trigger trades.
It will import other modules to run the analysis on the stocks -> place orders -> dump log in Telegram.py
"""

import logging
import traceback
from typing import Tuple

from .utils import Settings
from .utils import History
from .utils import Strategy_TA
from .utils import Context
from .utils import TeleLog


log = logging.getLogger("main.long_trading")


class Portfolio_Analysis:
    def __init__(self, **kwargs):
        self.strategies = Strategy_TA.load("TA")
        self.signals = kwargs.get("signals", dict())

        self.ava = Context(kwargs["user"], kwargs["accounts"])
        self.run_analysis(kwargs["accounts"], kwargs["log_to_telegram"])

    def get_signal_on_ticker(self, ticker_yahoo: str, ticker_ava: str) -> dict:
        log.info(f"Getting signal")

        if ticker_yahoo not in self.signals:
            try:
                data = History(ticker_yahoo, "18mo", "1d", cache="skip").data

                if str(data.iloc[-1]["Close"]) == "nan":
                    self.ava.update_todays_ochl(data, ticker_ava)

                strategy_obj = Strategy_TA(
                    data,
                    strategies=self.strategies.get(ticker_yahoo, list()),
                )

            except Exception as e:
                log.error(f"Error (get_signal_on_ticker): {e}")

                return {}

            self.signals[ticker_yahoo] = {
                "signal": strategy_obj.summary["signal"],
                "return": strategy_obj.summary["max_output"]["result"],
            }

        return self.signals[ticker_yahoo]

    def create_sell_orders(self) -> Tuple[list, dict]:
        log.info(f"Walk through portfolio (sell)")

        orders, portfolio_tickers = list(), dict()
        if self.ava.portfolio["positions"]["df"] is not None:
            for i, row in self.ava.portfolio["positions"]["df"].iterrows():
                log.info(
                    f'Portfolio ({int(i) + 1}/{self.ava.portfolio["positions"]["df"].shape[0]}): {row["ticker_yahoo"]}'
                )

                portfolio_tickers[row["ticker_yahoo"]] = {"row": row}

                signal = self.get_signal_on_ticker(
                    row["ticker_yahoo"], row["orderbookId"]
                )

                if signal.get("signal") != "sell":
                    continue

                log.info("> SELL")

                orders.append(
                    {
                        "account_id": row["accountId"],
                        "order_book_id": row["orderbookId"],
                        "volume": row["volume"],
                        "price": row["lastPrice"],
                        "profit": row["profitPercent"],
                        "name": row["name"],
                        "ticker_yahoo": row["ticker_yahoo"],
                        "max_return": signal["return"],
                    }
                )

        self.ava.create_orders(orders, "sell")

        return orders, portfolio_tickers

    def create_buy_orders(self, portfolio_tickers: dict) -> Tuple[list, dict]:
        log.info(f"Walk through budget lists (buy)")

        orders = list()
        for budget_rule_name, watch_list in self.ava.budget_rules.items():
            for ticker in watch_list["tickers"]:
                if ticker["ticker_yahoo"] in portfolio_tickers:
                    portfolio_tickers[ticker["ticker_yahoo"]]["budget"] = (
                        int(budget_rule_name) * 1000
                    )

                    continue

                log.info(
                    f'> Budget list "{budget_rule_name}": {ticker["ticker_yahoo"]}'
                )

                signal = self.get_signal_on_ticker(
                    ticker["ticker_yahoo"], ticker["order_book_id"]
                )

                if signal.get("signal") != "buy":
                    continue

                stock_price = self.ava.get_stock_price(ticker["order_book_id"])

                try:
                    volume = int(int(budget_rule_name) * 1000 // stock_price["buy"])

                except Exception as e:
                    log.error(f"Error (create_buy_orders): {e}")
                    continue

                log.info("> BUY")

                orders.append(
                    {
                        "ticker_yahoo": ticker["ticker_yahoo"],
                        "order_book_id": ticker["order_book_id"],
                        "budget": int(budget_rule_name) * 1000,
                        "price": stock_price["buy"],
                        "volume": volume,
                        "name": ticker["name"],
                        "max_return": signal["return"],
                    }
                )

        created_orders = self.ava.create_orders(orders, "buy")

        return created_orders, portfolio_tickers

    def create_take_profit_orders(
        self, portfolio_tickers: dict, created_sell_orders: list
    ) -> list:
        log.info(f"Walk through portfolio (take profit)")

        for sell_order in created_sell_orders:
            if sell_order["ticker_yahoo"] in portfolio_tickers:
                portfolio_tickers.pop(sell_order["ticker_yahoo"])

        orders = list()

        for ticker in portfolio_tickers.values():
            ticker_budget = ticker.get("budget")

            if ticker_budget is None:
                log.error(f'> Ticker "{ticker["row"]["ticker_yahoo"]}" has no budget')

                continue

            log.info(f'> Ticker: {ticker["row"]["ticker_yahoo"]}')

            volume_sell = (
                ticker["row"]["value"]
                - max(ticker["row"]["acquiredValue"], ticker_budget)
            ) // ticker["row"]["lastPrice"]

            conditions_skip = [ticker["row"]["profitPercent"] < 10, volume_sell <= 0]

            if any(conditions_skip):
                continue

            log.info("> TAKE PROFIT")
            orders.append(
                {
                    "account_id": ticker["row"]["accountId"],
                    "order_book_id": ticker["row"]["orderbookId"],
                    "volume": volume_sell,
                    "price": ticker["row"]["lastPrice"],
                    "profit": round(
                        (
                            (volume_sell * ticker["row"]["lastPrice"])
                            / max(ticker["row"]["acquiredValue"], ticker_budget)
                        )
                        * 100,
                        1,
                    ),
                    "name": ticker["row"]["name"],
                    "ticker_yahoo": ticker["row"]["ticker_yahoo"],
                }
            )

        self.ava.create_orders(orders, "take_profit")

        return orders

    def run_analysis(self, accounts: dict, log_to_telegram: bool) -> None:
        log.info(f'Running analysis for account(s): {" & ".join(accounts)}')

        self.ava.remove_active_orders(account_ids=list(accounts.values()))

        created_orders = dict()
        created_orders["sell"], portfolio_tickers = self.create_sell_orders()
        created_orders["buy"], portfolio_tickers = self.create_buy_orders(
            portfolio_tickers
        )
        created_orders["take_profit"] = self.create_take_profit_orders(
            portfolio_tickers, created_orders["sell"]
        )

        if log_to_telegram:
            TeleLog(portfolio=self.ava.get_portfolio(), orders=created_orders)


def run() -> None:
    settings: dict = Settings().load()
    signals = dict()

    for user, settings_per_user in settings.items():
        for setting_per_setup in settings_per_user.values():
            if not setting_per_setup.get("run_long_trading", False):
                continue

            try:
                walkthrough = Portfolio_Analysis(
                    user=user,
                    accounts=setting_per_setup["accounts"],
                    signals=signals,
                    log_to_telegram=setting_per_setup.get("log_to_telegram", True),
                    buy_delay_after_sell=setting_per_setup.get(
                        "buy_delay_after_sell", 2
                    ),
                )
                signals = walkthrough.signals

            except Exception as e:
                log.error(f">>> {e}: {traceback.format_exc()}")

                TeleLog(crash_report=f"LT: script has crashed: {e}")
