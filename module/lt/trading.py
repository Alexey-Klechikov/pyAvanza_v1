import logging
import traceback
from typing import List, Tuple

from avanza import OrderType as Signal

from module.lt.strategy import Strategy
from module.utils import Cache, Context, History, Settings, TeleLog

log = logging.getLogger("main.lt.trading")


class PortfolioAnalysis:
    def __init__(self, signals: dict):
        settings = Settings().load("LT")

        self.strategies = Strategy.load("LT")
        self.signals = signals

        self.ava = Context(settings["user"], settings["accounts"])
        self.run_analysis(settings["accounts"], settings["log_to_telegram"])

    def get_signal_on_ticker(self, ticker_yahoo: str, ticker_ava: str) -> dict:
        log.info("Getting signal")

        if ticker_yahoo not in self.signals:
            try:
                data = History(ticker_yahoo, "18mo", "1d", cache=Cache.SKIP).data

                if str(data.iloc[-1]["Close"]) == "nan":
                    self.ava.update_todays_ochl(data, ticker_ava)

                strategy_obj = Strategy(
                    data,
                    strategies=self.strategies.get(ticker_yahoo, []),
                )

            except Exception as e:
                log.error(f"Error (get_signal_on_ticker): {e}")

                return {}

            self.signals[ticker_yahoo] = {
                "signal": strategy_obj.summary.signal,
                "return": strategy_obj.summary.max_output.result,
            }

        return self.signals[ticker_yahoo]

    def create_sell_orders(self) -> Tuple[List[dict], dict]:
        log.info("Walk through portfolio (sell)")

        orders, portfolio_tickers = [], {}
        if self.ava.portfolio.positions.df.shape[0] != 0:
            for i, row in self.ava.portfolio.positions.df.iterrows():
                log.info(
                    f'Portfolio ({int(i) + 1}/{self.ava.portfolio.positions.df.shape[0]}): {row["ticker_yahoo"]}'  # type: ignore
                )

                portfolio_tickers[row["ticker_yahoo"]] = {"row": row}

                signal = self.get_signal_on_ticker(
                    row["ticker_yahoo"], row["orderbookId"]
                )

                if signal.get("signal") != Signal.SELL:
                    continue

                log.info(">> ACTION")

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

        self.ava.create_orders(orders, Signal.SELL)

        return orders, portfolio_tickers

    def create_buy_orders(self, portfolio_tickers: dict) -> Tuple[List[dict], dict]:
        log.info("Walk through budget lists (buy)")

        orders = []
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

                if signal.get("signal") != Signal.BUY:
                    continue

                stock_price = self.ava.get_stock_price(ticker["order_book_id"])

                try:
                    volume = int(
                        int(budget_rule_name) * 1000 // stock_price[Signal.BUY]
                    )

                except Exception as e:
                    log.error(f"Error (create_buy_orders): {e}")
                    continue

                log.info(">> ACTION")

                orders.append(
                    {
                        "ticker_yahoo": ticker["ticker_yahoo"],
                        "order_book_id": ticker["order_book_id"],
                        "budget": int(budget_rule_name) * 1000,
                        "price": stock_price[Signal.BUY],
                        "volume": volume,
                        "name": ticker["name"],
                        "max_return": signal["return"],
                    }
                )

        created_orders = self.ava.create_orders(orders, Signal.BUY)

        return created_orders, portfolio_tickers

    def create_take_profit_orders(
        self, portfolio_tickers: dict, created_sell_orders: List[dict]
    ) -> List[dict]:
        log.info("Walk through portfolio (take profit)")

        for sell_order in created_sell_orders:
            if sell_order["ticker_yahoo"] in portfolio_tickers:
                portfolio_tickers.pop(sell_order["ticker_yahoo"])

        orders = []

        for ticker in portfolio_tickers.values():
            ticker_budget = ticker.get("budget")

            if ticker_budget is None:
                log.warning(
                    f'> Ticker "{ticker["row"]["ticker_yahoo"]}" has no budget -> skip'
                )

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

        self.ava.create_orders(orders, Signal.SELL)

        return orders

    def run_analysis(self, accounts: dict, log_to_telegram: bool) -> None:
        log.info(f'Running analysis for account(s): {" & ".join(accounts)}')

        self.ava.delete_active_orders(account_ids=list(accounts.values()))

        created_orders = {}
        created_orders[Signal.SELL], portfolio_tickers = self.create_sell_orders()
        created_orders[Signal.BUY], portfolio_tickers = self.create_buy_orders(
            portfolio_tickers
        )
        created_orders[Signal.SELL] += self.create_take_profit_orders(
            portfolio_tickers, created_orders[Signal.SELL]
        )

        if log_to_telegram:
            TeleLog(portfolio=self.ava.get_portfolio(), orders=created_orders)


def run() -> None:
    signals: dict = {}

    try:
        walkthrough = PortfolioAnalysis(signals)
        signals = walkthrough.signals

    except Exception as e:
        log.error(f">>> {e}: {traceback.format_exc()}")

        TeleLog(crash_report=f"LT: script has crashed: {e}")
