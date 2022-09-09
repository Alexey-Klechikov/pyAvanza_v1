"""
This module is used to process and dump execution logs to Telegram
"""

import logging
import telegram_send


log = logging.getLogger("main.utils.telelog")


class TeleLog:
    def __init__(self, **kwargs):
        self.message = ""

        if "portfolio" in kwargs:
            self.parse_portfolio(kwargs["portfolio"])

        if "orders" in kwargs:
            self.parse_orders(kwargs["orders"])

        if "watch_lists_analysis_log" in kwargs:
            self.parse_watch_lists_analysis_log(kwargs["watch_lists_analysis_log"])

        if "completed_orders" in kwargs:
            self.parse_completed_orders(kwargs["completed_orders"])

        if "day_trading_stats" in kwargs:
            self.parse_day_trading_stats(kwargs["day_trading_stats"])

        if "crash_report" in kwargs:
            self.message = kwargs["crash_report"]

        if "message" in kwargs:
            self.message = kwargs["message"]

        self.dump_to_telegram()

    def parse_day_trading_stats(self, day_trading_stats: dict) -> None:
        log.debug("Parse day_trading_stats")

        profit = round(
            day_trading_stats["balance_after"] - day_trading_stats["balance_before"]
        )

        profit_percentage = round(100 * profit / day_trading_stats["budget"], 2)

        messages = [
            f'DT: Total value: {round(day_trading_stats["balance_after"])}',
            f'> Budget: {day_trading_stats["budget"]}',
            f"> Profit: {profit_percentage}% ({profit} SEK)",
            f'> Trades: {day_trading_stats["number_trades"]}',
        ]

        if day_trading_stats["number_errors"] > 0:
            messages.append(f'> Errors: {day_trading_stats["number_errors"]}')

        self.message += "\n".join(messages)

    def parse_portfolio(self, portfolio: dict) -> None:
        log.debug("Parse portfolio")

        free_funds = "\n".join(
            [
                f"> {account}: {funds}"
                for account, funds in portfolio["buying_power"].items()
            ]
        )
        self.message += f'LT: Total value: {round(portfolio["total_own_capital"])}\n\nTotal free funds:\n{free_funds}\n\n'

    def parse_watch_lists_analysis_log(
        self, watch_lists_analysis_log: list[str]
    ) -> None:
        log.debug("Parse watch_lists_analysis_log")

        self.message = "\n".join(watch_lists_analysis_log)

    def parse_orders(self, orders: dict) -> str:
        log.debug("Parse orders")

        for order_type, orders_by_type in orders.items():
            if len(orders_by_type) == 0:
                continue

            self.message += f"{order_type.upper()} orders:\n\n"

            for order in orders_by_type:
                order_messages = list()

                if order_type == "buy":
                    order_messages = [
                        f"> Ticker: {order['name']} ({order['ticker_yahoo']})",
                        f">> Budget: {order['budget']} SEK",
                    ]

                elif order_type == "sell":
                    order_messages = [
                        f"> Ticker: {order['name']} ({order['ticker_yahoo']})",
                        f">> Value: {round(float(order['price']) * int(order['volume']))} SEK",
                        f">> Profit: {order['profit']} %",
                    ]

                elif order_type == "take_profit":
                    order_messages = [
                        f"> Ticker: {order['name']} ({order['ticker_yahoo']})",
                        f">> Value: {round(float(order['price']) * int(order['volume']))} SEK",
                        f">> Profit: {order['profit']} %",
                    ]

                self.message += "\n".join(order_messages + ["\n"])

        return self.message

    def parse_completed_orders(self, completed_orders: list[dict]) -> str:
        log.debug("Parse completed_orders")

        orders = [
            " / ".join([f"{k}: {v}" for k, v in order.items()])
            for order in completed_orders
        ]

        self.message = "\n".join(orders)

        return self.message

    def dump_to_telegram(self) -> None:
        log.info("Dump log to Telegram")

        telegram_send.send(messages=[self.message])
