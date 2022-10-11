"""
This module contains all tooling to communicate to Avanza
"""


import logging
import time
from copy import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Tuple, Union

import keyring
import pandas as pd
from avanza import Avanza, InstrumentType, OrderType, Resolution, TimePeriod
from pytz import timezone
from requests.exceptions import HTTPError

log = logging.getLogger("main.utils.context")


@dataclass
class Positions:
    lst: Optional[list] = None
    df: pd.DataFrame = pd.DataFrame(columns=["orderbookId"])

    def __post_init__(self):
        self.df = pd.DataFrame(self.lst)


@dataclass
class Portfolio:
    buying_power: dict = field(default_factory=dict)
    total_own_capital: float = 0
    positions: Positions = Positions()


class Context:
    def __init__(self, user: str, accounts: dict, skip_lists: bool = False):
        self.ctx = self.get_ctx(user)
        self.accounts = accounts

        if not skip_lists:
            self.portfolio = self.get_portfolio()
            self.budget_rules, self.watch_lists = self.process_watch_lists()

    def get_ctx(self, user: str) -> Avanza:
        log.debug("Getting context")

        i = 1
        while True:
            try:
                ctx = Avanza(
                    {
                        "username": keyring.get_password(user, "un"),
                        "password": keyring.get_password(user, "pass"),
                        "totpSecret": keyring.get_password(user, "totp"),
                    }
                )
                break

            except HTTPError as exc:
                log.error(exc)
                i += 1

                time.sleep(i * 2)

        return ctx

    def get_portfolio(self) -> Portfolio:
        portfolio = Portfolio()

        for account_name, account_id in self.accounts.items():
            account_overview = self.ctx.get_account_overview(account_id)

            if account_overview:
                portfolio.buying_power[account_name] = account_overview["buyingPower"]
                portfolio.total_own_capital += account_overview["ownCapital"]

        positions = []
        all_positions = self.ctx.get_positions()
        if all_positions:
            for position in all_positions["instrumentPositions"][0]["positions"]:
                if not int(position["accountId"]) in self.accounts.values():
                    continue

                if position.get("orderbookId", None) is None:
                    log.warning(f"{position['name']} has no orderbookId")
                    continue

                positions.append(position)

        if positions:
            portfolio.positions = Positions(positions)

            tickers_yahoo = []
            for orderbook_id in portfolio.positions.df["orderbookId"].tolist():
                stock_info = self.ctx.get_stock_info(orderbook_id)
                if not stock_info:
                    stock_info = {}

                tickers_yahoo.append(
                    f"{stock_info.get('tickerSymbol', '').replace(' ', '-')}.ST"
                )

            portfolio.positions.df["ticker_yahoo"] = tickers_yahoo

        return portfolio

    def process_watch_lists(self) -> Tuple[dict, dict]:
        log.debug("Process watch_lists")

        watch_lists, budget_rules = {}, {}

        all_watch_lists = self.ctx.get_watchlists()
        if all_watch_lists:
            for watch_list in all_watch_lists:
                tickers = []

                for order_book_id in watch_list["orderbooks"]:
                    stock_info = self.ctx.get_stock_info(order_book_id)
                    if stock_info is None:
                        log.warning(f"{order_book_id} not found")
                        continue

                    ticker_dict = {
                        "order_book_id": order_book_id,
                        "name": stock_info.get("name"),
                        "ticker_yahoo": f"{stock_info.get('tickerSymbol', '').replace(' ', '-')}.ST",
                    }
                    tickers.append(ticker_dict)

                temp_watch_list = {
                    "watch_list_id": watch_list["id"],
                    "tickers": tickers,
                }

                try:
                    int(watch_list["name"])
                    budget_rules[watch_list["name"]] = copy(temp_watch_list)
                except ValueError:
                    watch_lists[watch_list["name"]] = copy(temp_watch_list)

        return budget_rules, watch_lists

    def create_orders(self, orders: list[dict], order_type: OrderType) -> list[dict]:
        log.debug(f"Creating {order_type} order(s)")

        created_orders = []

        if order_type == OrderType.SELL:
            for sell_order in orders:
                if sell_order["volume"] == 0:
                    continue

                order_attr = {
                    "account_id": str(sell_order["account_id"]),
                    "order_book_id": str(sell_order["order_book_id"]),
                    "order_type": order_type,
                    "price": sell_order.get(
                        "price",
                        self.get_stock_price(sell_order["order_book_id"])[
                            OrderType.SELL
                        ],
                    ),
                    "valid_until": (datetime.today() + timedelta(days=1)).date(),
                    "volume": sell_order["volume"],
                }

                try:
                    self.ctx.place_order(**order_attr)

                except HTTPError as exc:
                    log.error(f"Exception: {exc} - {order_attr}")

                # HERE: check why I dont append orders here

        elif order_type == OrderType.BUY:
            self.portfolio = self.get_portfolio()

            if len(orders) > 0:
                orders.sort(
                    key=lambda x: (int(x["budget"]), int(x["max_return"])), reverse=True
                )
                reserved_budget = {account: 0 for account in self.accounts}

                for buy_order in orders:
                    # Check accounts one by one if enough funds for the order
                    for account_name, account_id in self.accounts.items():
                        if (
                            self.portfolio.buying_power[account_name]
                            - reserved_budget[account_name]
                            > buy_order["budget"]
                            and buy_order["volume"] > 0
                        ):
                            order_attr = {
                                "account_id": str(account_id),
                                "order_book_id": str(buy_order["order_book_id"]),
                                "order_type": order_type,
                                "price": buy_order.get(
                                    "price",
                                    self.get_stock_price(buy_order["order_book_id"])[
                                        order_type
                                    ],
                                ),
                                "valid_until": (
                                    datetime.today() + timedelta(days=1)
                                ).date(),
                                "volume": int(buy_order["volume"]),
                            }

                            try:
                                self.ctx.place_order(**order_attr)

                            except HTTPError as exc:
                                log.error(f"Exception: {exc} - {order_attr}")

                            reserved_budget[account_name] += buy_order["budget"]
                            created_orders.append(buy_order)

                            break

        return created_orders

    def update_order(self, old_order: dict, price: float) -> None:
        log.debug("Updating order")

        order_attr = {
            "account_id": old_order["account"]["id"],
            "order_book_id": old_order["orderbook"]["id"],
            "order_type": OrderType["SELL" if old_order["type"] == "SELL" else "BUY"],
            "price": price,
            "valid_until": (datetime.today() + timedelta(days=1)).date(),
            "volume": old_order["volume"],
            "instrument_type": InstrumentType[
                "CERTIFICATE"
                if old_order["orderbook"]["type"] == "CERTIFICATE"
                else "STOCK"
            ],
            "order_id": old_order["orderId"],
        }

        try:
            self.ctx.edit_order(**order_attr)

        except Exception as exc:
            log.error(f"Exception: {exc} - {order_attr}")

    def get_stock_price(self, stock_id: str) -> dict:
        stock_info = self.ctx.get_stock_info(stock_id)

        if stock_info is None:
            raise Exception(f"Stock {stock_id} not found")

        stock_price = {
            OrderType.BUY: stock_info["lastPrice"],
            OrderType.SELL: stock_info["lastPrice"],
        }

        order_depth = pd.DataFrame(stock_info["orderDepthLevels"])
        if not order_depth.empty:
            stock_price[OrderType.SELL] = max(
                order_depth["buy"].apply(lambda x: x["price"])
            )
            stock_price[OrderType.BUY] = min(
                order_depth["sell"].apply(lambda x: x["price"])
            )

        return stock_price

    def get_certificate_info(self, certificate_id: str) -> dict:
        certificate = {}

        for _ in range(5):
            try:
                certificate = self.ctx.get_certificate_info(certificate_id)

            except HTTPError:
                time.sleep(1)

                continue

            certificate = {} if certificate is None else certificate

            if certificate.get(
                "spread", 1
            ) <= 0.65 or datetime.now() >= datetime.now().replace(hour=17, minute=30):
                return {
                    OrderType.BUY: certificate.get("sellPrice", None),
                    OrderType.SELL: certificate.get("buyPrice", None),
                    "positions": certificate.get("positions", []),
                    "spread": certificate.get("spread"),
                }

            time.sleep(2)

        return {
            OrderType.BUY: None,
            OrderType.SELL: None,
            "positions": [],
            "spread": certificate.get("spread"),
        }

    def get_active_order(self, certificate_id: Optional[str] = None) -> dict:
        active_order: dict = {}

        for _ in range(5):
            try:
                orders = self.ctx.get_deals_and_orders()

            except HTTPError:
                time.sleep(1)

                continue

            active_orders = [] if not orders else orders["orders"]
            active_orders = [
                order
                for order in active_orders
                if (order["orderbook"]["id"] == certificate_id)
                and (order["rawStatus"] == "ACTIVE")
            ]

            return active_order if not active_orders else active_orders[0]

        return active_order

    def remove_active_orders(self, account_ids: list[Union[str, int]]) -> None:
        active_orders = []

        deals_and_orders = self.ctx.get_deals_and_orders()
        if deals_and_orders:
            active_orders = deals_and_orders["orders"]

        if active_orders:
            log.debug("Removing active orders")

            for order in active_orders:
                if int(order["account"]["id"]) not in list(self.accounts.values()):
                    continue

                if (
                    len(account_ids) > 0
                    and int(order["account"]["id"]) not in account_ids
                ):
                    continue

                log.debug(f"({order['sum']}) {order['orderbook']['name']}")
                self.ctx.delete_order(
                    account_id=order["account"]["id"], order_id=order["orderId"]
                )

    def update_todays_ochl(self, data: pd.DataFrame, stock_id: str) -> pd.DataFrame:
        stock_info = self.ctx.get_stock_info(stock_id)

        if stock_info is None:
            raise Exception(f"Stock {stock_id} not found")

        last_row_index = data.tail(1).index
        data.loc[last_row_index, "Open"] = max(
            min(
                stock_info["lastPrice"] + stock_info["change"],
                stock_info["highestPrice"],
            ),
            stock_info["lowestPrice"],
        )
        data.loc[last_row_index, "Close"] = stock_info["lastPrice"]
        data.loc[last_row_index, "High"] = stock_info["highestPrice"]
        data.loc[last_row_index, "Low"] = stock_info["lowestPrice"]
        data.loc[last_row_index, "Volume"] = stock_info["totalVolumeTraded"]

        return data

    def get_today_history(self, stock_id: str) -> pd.DataFrame:
        period = TimePeriod.TODAY
        resolution = Resolution.MINUTE

        chart_data = self.ctx.get_chart_data(stock_id, period, resolution)

        if chart_data is None or len(chart_data["ohlc"]) == 0:
            return pd.DataFrame(
                columns=["Datetime", "Open", "High", "Low", "Close", "Volume"]
            ).set_index("Datetime")

        data = pd.DataFrame(chart_data["ohlc"])
        data["Datetime"] = [
            datetime.fromtimestamp(x / 1000).astimezone(timezone("Europe/Stockholm"))
            for x in data.timestamp
        ]
        data = (
            data.rename(
                columns={
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "totalVolumeTraded": "Volume",
                }
            )
            .set_index("Datetime")
            .drop(["timestamp"], axis=1)
        )

        return data
