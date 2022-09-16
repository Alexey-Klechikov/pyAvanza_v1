"""
This module contains all tooling to communicate to Avanza
"""


import time
import keyring
import logging
import pandas as pd

from pytz import timezone
from copy import copy
from datetime import datetime, timedelta
from typing import Tuple, Union

from avanza import Avanza, OrderType, InstrumentType, TimePeriod, Resolution


log = logging.getLogger("main.utils.context")


class Context:
    def __init__(
        self,
        user: str,
        accounts: dict,
        skip_lists: bool = False,
        log_number_errors: int = 0,
    ):
        self.ctx = self.get_ctx(user)
        self.accounts = accounts
        self.log_number_errors = log_number_errors

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

            except Exception as e:
                log.error(e)
                i += 1
                time.sleep(i * 2)

        return ctx

    def get_portfolio(self) -> dict:
        portfolio = {
            "buying_power": dict(),
            "total_own_capital": 0,
            "positions": {"dict": None, "df": None},
        }

        for k, v in self.accounts.items():
            account_overview = self.ctx.get_account_overview(v)
            if account_overview:
                portfolio["buying_power"][k] = account_overview["buyingPower"]
                portfolio["total_own_capital"] += account_overview["ownCapital"]

        positions = list()
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
            portfolio["positions"] = {
                "dict": positions,
                "df": pd.DataFrame(positions),
            }

            tickers_yahoo = list()
            for orderbook_id in portfolio["positions"]["df"]["orderbookId"].tolist():
                stock_info = self.ctx.get_stock_info(orderbook_id)
                if not stock_info:
                    stock_info = dict()

                tickers_yahoo.append(
                    f"{stock_info.get('tickerSymbol', '').replace(' ', '-')}.ST"
                )

            portfolio["positions"]["df"]["ticker_yahoo"] = tickers_yahoo

        return portfolio

    def process_watch_lists(self) -> Tuple[dict, dict]:
        log.debug("Process watch_lists")

        watch_lists, budget_rules = dict(), dict()

        all_watch_lists = self.ctx.get_watchlists()
        if all_watch_lists:
            for watch_list in all_watch_lists:
                tickers = list()

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
                except:
                    watch_lists[watch_list["name"]] = copy(temp_watch_list)

        return budget_rules, watch_lists

    def create_orders(self, orders: list[dict], order_type: str) -> list[dict]:
        log.debug(f"Creating {order_type} order(s)")

        created_orders = list()

        if order_type in ["sell", "take_profit"]:
            for sell_order in orders:
                order_attr = {
                    "account_id": str(sell_order["account_id"]),
                    "order_book_id": str(sell_order["order_book_id"]),
                    "order_type": OrderType.SELL,
                    "price": sell_order.get(
                        "price",
                        self.get_stock_price(sell_order["order_book_id"])["sell"],
                    ),
                    "valid_until": (datetime.today() + timedelta(days=1)).date(),
                    "volume": sell_order["volume"],
                }

                try:
                    self.ctx.place_order(**order_attr)

                except Exception as e:
                    log.error(f"Exception: {e} - {order_attr}")

                # TODO: check why I dont append orders here

        elif order_type == "buy":
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
                            self.portfolio["buying_power"][account_name]
                            - reserved_budget[account_name]
                            > buy_order["budget"]
                        ):
                            order_attr = {
                                "account_id": str(account_id),
                                "order_book_id": str(buy_order["order_book_id"]),
                                "order_type": OrderType.BUY,
                                "price": buy_order.get(
                                    "price",
                                    self.get_stock_price(buy_order["order_book_id"])[
                                        "buy"
                                    ],
                                ),
                                "valid_until": (
                                    datetime.today() + timedelta(days=1)
                                ).date(),
                                "volume": int(buy_order["volume"]),
                            }

                            try:
                                self.ctx.place_order(**order_attr)

                            except Exception as e:
                                log.error(f"Exception: {e} - {order_attr}")

                            reserved_budget[account_name] += buy_order["budget"]
                            created_orders.append(buy_order)

                            break

        return created_orders

    def update_order(self, old_order: dict, price: float) -> None:
        log.debug(f"Updating order")

        order_attr = {
            "account_id": old_order["account"]["id"],
            "order_book_id": old_order["orderbook"]["id"],
            "order_type": OrderType.SELL
            if old_order["type"] == "SELL"
            else OrderType.BUY,
            "price": price,
            "valid_until": (datetime.today() + timedelta(days=1)).date(),
            "volume": old_order["volume"],
            "instrument_type": InstrumentType.CERTIFICATE
            if old_order["orderbook"]["type"] == "CERTIFICATE"
            else InstrumentType.STOCK,
            "order_id": old_order["orderId"],
        }

        try:
            self.ctx.edit_order(**order_attr)

        except Exception as e:
            log.error(f"Exception: {e} - {order_attr}")

    def get_stock_price(self, stock_id: str) -> dict:
        stock_info = self.ctx.get_stock_info(stock_id)

        if stock_info is None:
            raise Exception(f"Stock {stock_id} not found")

        stock_price = {
            "buy": stock_info["lastPrice"],
            "sell": stock_info["lastPrice"],
        }

        order_depth = pd.DataFrame(stock_info["orderDepthLevels"])
        if not order_depth.empty:
            stock_price["sell"] = max(order_depth["buy"].apply(lambda x: x["price"]))
            stock_price["buy"] = min(order_depth["sell"].apply(lambda x: x["price"]))

        return stock_price

    def get_certificate_info(self, certificate_id: str) -> dict:
        certificate = dict()

        for _ in range(5):
            certificate = self.ctx.get_certificate_info(certificate_id)
            certificate = dict() if certificate is None else certificate

            if certificate.get(
                "spread", 1
            ) <= 0.6 or datetime.now() >= datetime.now().replace(hour=17, minute=30):
                return {
                    "buy": certificate.get("sellPrice", None),
                    "sell": certificate.get("buyPrice", None),
                    "positions": certificate.get("positions", list()),
                }

            time.sleep(2)

        log.error(
            f"Certificate {certificate_id} -> spread is too high {certificate.get('spread')}"
        )

        self.log_number_errors += 1

        return {
            "buy": None,
            "sell": None,
            "positions": list(),
        }

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

    def remove_active_orders(
        self,
        orderbook_ids: list[Union[str, int]] = list(),
        account_ids: list[Union[str, int]] = list(),
    ) -> dict:
        active_orders = list()
        removed_orders = {"buy": list(), "sell": list()}

        deals_and_orders = self.ctx.get_deals_and_orders()
        if deals_and_orders:
            active_orders = deals_and_orders["orders"]

        if active_orders:
            log.debug("Removing active orders")

            for order in active_orders:
                if int(order["account"]["id"]) not in list(self.accounts.values()):
                    continue

                if (
                    len(orderbook_ids) > 0
                    and int(order["orderbook"]["id"]) not in orderbook_ids
                ):
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

                stock_info = self.ctx.get_stock_info(order["orderbook"]["id"])
                if not stock_info:
                    continue

                ticker_yahoo = f"{stock_info['tickerSymbol'].replace(' ', '-')}.ST"
                removed_orders[order["type"].lower()].append(
                    {
                        "account_id": order["account"]["id"],
                        "order_book_id": order["orderbook"]["id"],
                        "name": order["orderbook"]["name"],
                        "price": order["price"],
                        "volume": order["volume"],
                        "ticker_yahoo": ticker_yahoo,
                    }
                )

        return removed_orders

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
