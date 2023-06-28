import logging
import time
import traceback
from typing import List, Optional

from avanza import OrderType as Signal

from src.lt.strategy import Strategy
from src.utils import Cache, Context, History, Settings, TeleLog

log = logging.getLogger("main.lt.trading")


class PortfolioAnalysis:
    def __init__(self):
        self.settings = Settings().load("LT")

        self.strategies = Strategy.load("LT")
        self.signals: dict = {}

        self.portfolio_tickers: dict = {"sold": {}, "in_stock": {}}

        self.ava = Context(self.settings["user"], self.settings["accounts"])
        self.run_analysis()

    def _get_signal_on_ticker(self, ticker_yahoo: str, ticker_ava: str) -> dict:
        if ticker_yahoo in self.signals:
            return self.signals[ticker_yahoo]

        try:
            data = History(ticker_yahoo, "18mo", "1d", cache=Cache.SKIP).data

            if str(data.iloc[-1]["Close"]) == "nan":
                self.ava.update_todays_ochl(data, ticker_ava)

            if self.strategies.get(ticker_yahoo):
                strategy_obj = Strategy(
                    data,
                    strategies=self.strategies.get(ticker_yahoo, {}).get(
                        "strategies", []
                    ),
                )

                self.signals[ticker_yahoo] = {
                    "signal": strategy_obj.summary.signal,
                    "return": strategy_obj.summary.max_output.result,
                }

            else:
                log.info("!!!! No strategy found")  # TODO: HERE: remove
                self.signals[ticker_yahoo] = {
                    "signal": Signal.SELL,
                    "return": 0,
                }

            return self.signals[ticker_yahoo]

        except Exception as e:
            log.error(f"Error (_get_signal_on_ticker): {e}")

            return {}

    def _sort_buy_orders(self, orders: List[dict]) -> List[dict]:
        sorted_orders: list = []

        tickers_sorted_by_priority: list = [
            i[0]
            for i in sorted(
                self.strategies.items(), key=lambda x: x[1]["max_output"], reverse=True
            )
        ]

        for ticker in tickers_sorted_by_priority:
            for order in orders:
                if order["ticker_yahoo"] == ticker:
                    sorted_orders.append(order)

        return sorted_orders

    def get_account_development(self) -> Optional[float]:
        current_ballance = self.ava.get_portfolio().total_own_capital
        account_development = (
            None
            if self.settings.get("last_accounts_balance", 0) == 0
            else round(
                (current_ballance - self.settings["last_accounts_balance"])
                / self.settings.get("last_accounts_balance", 0)
                * 100,
                2,
            )
        )

        self.settings[
            "last_accounts_balance"
        ] = self.ava.get_portfolio().total_own_capital

        Settings().dump(self.settings, "LT")

        return account_development

    def create_sell_orders(self) -> List[dict]:
        log.info("Walk through portfolio (SELL)")

        orders: list = []

        if self.ava.portfolio.positions.df.shape[0] == 0:
            return orders

        for i, row in self.ava.portfolio.positions.df.iterrows():
            log.info(
                f'Portfolio ({int(i) + 1}/{self.ava.portfolio.positions.df.shape[0]}): {row["ticker_yahoo"]}'  # type: ignore
            )

            signal = self._get_signal_on_ticker(row["ticker_yahoo"], row["orderbookId"])

            self.portfolio_tickers[
                "in_stock" if signal.get("signal") == Signal.BUY else "sold"
            ][row["ticker_yahoo"]] = row

            if signal.get("signal") == Signal.BUY:
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

        if len(orders) > 0:
            time.sleep(self.settings["buy_delay_after_sell"] * 60)

        return orders

    def create_buy_orders(self) -> List[dict]:
        log.info("Walk through watch lists (BUY)")

        orders: list = []

        for watch_list_name, watch_list in self.ava.watch_lists.items():
            for ticker in watch_list["tickers"]:
                if ticker["ticker_yahoo"] in list(
                    self.portfolio_tickers["in_stock"]
                ) + list(self.portfolio_tickers["sold"]):
                    continue

                log.info(f'> Watch list "{watch_list_name}": {ticker["ticker_yahoo"]}')

                signal = self._get_signal_on_ticker(
                    ticker["ticker_yahoo"], ticker["order_book_id"]
                )

                if signal.get("signal") == Signal.SELL:
                    continue

                stock_price = self.ava.get_stock_price(ticker["order_book_id"])
                volume = self.settings["budget_per_ticker"] // (
                    stock_price[Signal.BUY]
                    if stock_price[Signal.BUY]
                    else self.settings["budget_per_ticker"] + 1
                )

                log.info(">> ACTION")

                orders.append(
                    {
                        "ticker_yahoo": ticker["ticker_yahoo"],
                        "order_book_id": ticker["order_book_id"],
                        "budget": self.settings["budget_per_ticker"],
                        "price": stock_price[Signal.BUY],
                        "volume": volume,
                        "name": ticker["name"],
                        "max_return": signal["return"],
                    }
                )

        orders = self._sort_buy_orders(orders)
        orders = self.ava.create_orders(orders, Signal.BUY)

        return orders

    def create_take_profit_orders(self) -> List[dict]:
        log.info("Walk through portfolio (TAKE PROFIT)")

        orders = []

        for ticker in self.portfolio_tickers["in_stock"].values():
            log.info(f'> Ticker: {ticker["ticker_yahoo"]}')

            volume_sell = (
                ticker["value"] - self.settings["budget_per_ticker"]
            ) // ticker["lastPrice"]

            profit_percent = round(
                volume_sell
                * ticker["lastPrice"]
                / self.settings["budget_per_ticker"]
                * 100,
                1,
            )

            if profit_percent < 10 or volume_sell <= 0:
                continue

            log.info("> TAKE PROFIT")
            orders.append(
                {
                    "account_id": ticker["accountId"],
                    "order_book_id": ticker["orderbookId"],
                    "volume": volume_sell,
                    "price": ticker["lastPrice"],
                    "profit": profit_percent,
                    "name": ticker["name"],
                    "ticker_yahoo": ticker["ticker_yahoo"],
                }
            )

        self.ava.create_orders(orders, Signal.SELL)

        return orders

    def run_analysis(self) -> None:
        log.info(
            f'Running analysis for account(s): {" & ".join(self.settings["accounts"])}'
        )

        account_development = self.get_account_development()

        self.ava.delete_active_orders(
            account_ids=list(self.settings["accounts"].values())
        )

        created_orders = {}
        created_orders[Signal.SELL] = self.create_sell_orders()
        created_orders[Signal.BUY] = self.create_buy_orders()
        created_orders[Signal.SELL] += self.create_take_profit_orders()

        if self.settings["log_to_telegram"]:
            TeleLog(
                portfolio=self.ava.get_portfolio(),
                orders=created_orders,
                account_development=account_development,
            )


def run() -> None:
    try:
        PortfolioAnalysis()

    except Exception as e:
        log.error(f">>> {e}: {traceback.format_exc()}")

        TeleLog(crash_report=f"LT: script has crashed: {e}")
