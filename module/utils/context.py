"""
This module contains all tooling to communicate to Avanza
"""


import time
import keyring
import logging
import datetime
import pandas as pd

from avanza import Avanza, OrderType
from pprint import pprint


log = logging.getLogger("main.context")


class Context:
    def __init__(self, user, accounts_dict, skip_lists=False):
        self.ctx = self.get_ctx(user)
        self.accounts_dict = accounts_dict

        if not skip_lists:
            self.portfolio_dict = self.get_portfolio()
            self.budget_rules_dict, self.watchlists_dict = self.process_watchlists()

    def get_ctx(self, user):
        log.info("Getting context")

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

    def get_portfolio(self):
        log.info("Getting portfolio")

        portfolio_dict = {
            "buying_power": {},
            "total_own_capital": 0,
            "positions": {"dict": None, "df": None},
        }

        for k, v in self.accounts_dict.items():
            account_overview_dict = self.ctx.get_account_overview(v)
            if account_overview_dict:
                portfolio_dict["buying_power"][k] = account_overview_dict["buyingPower"]
                portfolio_dict["total_own_capital"] += account_overview_dict[
                    "ownCapital"
                ]

        positions_list = list()
        positions_dict = self.ctx.get_positions()
        if positions_dict:
            for p in positions_dict["instrumentPositions"][0]["positions"]:
                if not int(p["accountId"]) in self.accounts_dict.values():
                    continue

                if p.get("orderbookId", None) is None:
                    log.warning(f"{p['name']} has no orderbookId")
                    continue

                positions_list.append(p)

        if positions_list:
            portfolio_dict["positions"] = {
                "dict": positions_list,
                "df": pd.DataFrame(positions_list),
            }

            tickers_yahoo_list = list()
            for orderbook_id in portfolio_dict["positions"]["df"][
                "orderbookId"
            ].tolist():
                stock_info_dict = self.ctx.get_stock_info(orderbook_id)
                if not stock_info_dict:
                    stock_info_dict = dict()

                tickers_yahoo_list.append(
                    f"{stock_info_dict.get('tickerSymbol', '').replace(' ', '-')}.ST"
                )

            portfolio_dict["positions"]["df"]["ticker_yahoo"] = tickers_yahoo_list

        return portfolio_dict

    def process_watchlists(self):
        log.info("Process watchlists")

        watchlists_dict, budget_rules_dict = dict(), dict()

        watchlists_list = self.ctx.get_watchlists()
        if watchlists_list:
            for watchlist_dict in watchlists_list:
                tickers_list = list()

                for order_book_id in watchlist_dict["orderbooks"]:
                    stock_info_dict = self.ctx.get_stock_info(order_book_id)
                    if stock_info_dict is None:
                        log.warning(f"{order_book_id} not found")
                        continue

                    ticker_dict = {
                        "order_book_id": order_book_id,
                        "name": stock_info_dict.get("name"),
                        "ticker_yahoo": f"{stock_info_dict.get('tickerSymbol', '').replace(' ', '-')}.ST",
                    }
                    tickers_list.append(ticker_dict)

                wl_dict = {
                    "watchlist_id": watchlist_dict["id"],
                    "tickers": tickers_list,
                }

                try:
                    int(watchlist_dict["name"])
                    budget_rules_dict[watchlist_dict["name"]] = wl_dict
                except:
                    watchlists_dict[watchlist_dict["name"]] = wl_dict

        return budget_rules_dict, watchlists_dict

    def create_orders(self, orders_list, type):
        log.info(f"Creating {type} orders")

        if type in ["sell", "take_profit"]:
            for sell_order_dict in orders_list:
                log.info(
                    f'> (profit {sell_order_dict["profit"]}%) {sell_order_dict["name"]}'
                )
                order_attr = {
                    "account_id": str(sell_order_dict["account_id"]),
                    "order_book_id": str(sell_order_dict["order_book_id"]),
                    "order_type": OrderType.SELL,
                    "price": self.get_stock_price(sell_order_dict["order_book_id"])[
                        "sell"
                    ],
                    "valid_until": (
                        datetime.datetime.today() + datetime.timedelta(days=1)
                    ).date(),
                    "volume": sell_order_dict["volume"],
                }

                try:
                    self.ctx.place_order(**order_attr)
                except Exception as e:
                    log.error(f"Exception: {e} - {order_attr}")

        elif type == "buy":
            self.portfolio_dict = self.get_portfolio()
            created_orders_list = list()

            if len(orders_list) > 0:
                orders_list.sort(
                    key=lambda x: (int(x["budget"]), int(x["max_return"])), reverse=True
                )
                reserved_budget = {account: 0 for account in self.accounts_dict}

                for buy_order_dict in orders_list:
                    # Check accounts one by one if enough funds for the order
                    for account_name, account_id in self.accounts_dict.items():
                        if (
                            self.portfolio_dict["buying_power"][account_name]
                            - reserved_budget[account_name]
                            > buy_order_dict["budget"]
                        ):
                            log.info(
                                f'({buy_order_dict["budget"]}) {buy_order_dict["name"]}'
                            )
                            order_attr = {
                                "account_id": str(account_id),
                                "order_book_id": str(buy_order_dict["order_book_id"]),
                                "order_type": OrderType.BUY,
                                "price": self.get_stock_price(
                                    buy_order_dict["order_book_id"]
                                )["buy"],
                                "valid_until": (
                                    datetime.datetime.today()
                                    + datetime.timedelta(days=1)
                                ).date(),
                                "volume": int(buy_order_dict["volume"]),
                            }

                            try:
                                self.ctx.place_order(**order_attr)
                            except Exception as e:
                                log.error(f"Exception: {e} - {order_attr}")

                            reserved_budget[account_name] += buy_order_dict["budget"]
                            created_orders_list.append(buy_order_dict)
                            break

            return created_orders_list

    def get_stock_price(self, stock_id):
        log.info(f"Getting stock price {stock_id}")

        stock_info_dict = self.ctx.get_stock_info(stock_id)

        if stock_info_dict is None:
            raise Exception(f"Stock {stock_id} not found")

        stock_price_dict = {
            "buy": stock_info_dict["lastPrice"],
            "sell": stock_info_dict["lastPrice"],
        }

        order_depth_df = pd.DataFrame(stock_info_dict["orderDepthLevels"])
        if not order_depth_df.empty:
            stock_price_dict["sell"] = max(
                order_depth_df["buy"].apply(lambda x: x["price"])
            )
            stock_price_dict["buy"] = min(
                order_depth_df["sell"].apply(lambda x: x["price"])
            )

        return stock_price_dict

    def get_certificate_info(self, certificate_id):
        certificate_dict = self.ctx.get_certificate_info(certificate_id)

        try:
            if (
                certificate_dict is None
                or "sellPrice" not in certificate_dict
                or "buyPrice" not in certificate_dict
            ):
                raise Exception(
                    f"Certificate {certificate_id} not found or missing info"
                )

            return {
                "buy": certificate_dict["sellPrice"],
                "sell": certificate_dict["buyPrice"],
                "positions": certificate_dict["positions"],
            }

        except Exception as e:
            log.error(f"{e}: {certificate_dict}")
            return {"buy": None, "sell": None, "positions": []}

    def get_todays_ochl(self, history_df, stock_id):
        log.warning(f"Getting todays OCHL")

        stock_info_dict = self.ctx.get_stock_info(stock_id)

        if stock_info_dict is None:
            raise Exception(f"Stock {stock_id} not found")

        last_row_index = history_df.tail(1).index
        history_df.loc[last_row_index, "Open"] = max(
            min(
                stock_info_dict["lastPrice"] + stock_info_dict["change"],
                stock_info_dict["highestPrice"],
            ),
            stock_info_dict["lowestPrice"],
        )
        history_df.loc[last_row_index, "Close"] = stock_info_dict["lastPrice"]
        history_df.loc[last_row_index, "High"] = stock_info_dict["highestPrice"]
        history_df.loc[last_row_index, "Low"] = stock_info_dict["lowestPrice"]
        history_df.loc[last_row_index, "Volume"] = stock_info_dict["totalVolumeTraded"]

    def remove_active_orders(self, orderbook_ids_list=list(), account_ids_list=list()):
        active_orders_list = list()
        removed_orders_dict = {"buy": list(), "sell": list()}

        deals_and_orders_dict = self.ctx.get_deals_and_orders()
        if deals_and_orders_dict:
            active_orders_list = deals_and_orders_dict["orders"]

        if active_orders_list:
            log.info("Removing active orders")

            for order in active_orders_list:
                if int(order["account"]["id"]) not in list(self.accounts_dict.values()):
                    continue

                if (
                    len(orderbook_ids_list) > 0
                    and int(order["orderbook"]["id"]) not in orderbook_ids_list
                ):
                    continue

                if (
                    len(account_ids_list) > 0
                    and int(order["account"]["id"]) not in account_ids_list
                ):
                    continue

                log.info(f"({order['sum']}) {order['orderbook']['name']}")
                self.ctx.delete_order(
                    account_id=order["account"]["id"], order_id=order["orderId"]
                )

                stock_info_dict = self.ctx.get_stock_info(order["orderbook"]["id"])
                if not stock_info_dict:
                    continue

                ticker_yahoo = f"{stock_info_dict['tickerSymbol'].replace(' ', '-')}.ST"
                removed_orders_dict[order["type"].lower()].append(
                    {
                        "account_id": order["account"]["id"],
                        "order_book_id": order["orderbook"]["id"],
                        "name": order["orderbook"]["name"],
                        "price": order["price"],
                        "volume": order["volume"],
                        "ticker_yahoo": ticker_yahoo,
                    }
                )

        return removed_orders_dict
