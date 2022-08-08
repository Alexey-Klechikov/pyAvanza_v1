"""
This module is used to process and dump execution logs to Telegram
"""

import logging
import telegram_send


log = logging.getLogger("main.telelog")


class TeleLog:
    def __init__(self, **kwargs):
        self.message = ""

        if "portfolio_dict" in kwargs:
            self.parse_portfolio_dict(kwargs["portfolio_dict"])

        if "orders_dict" in kwargs:
            self.parse_orders_dict(kwargs["orders_dict"])

        if "watchlists_analysis_log_list" in kwargs:
            self.parse_watchlists_analysis_log(kwargs["watchlists_analysis_log_list"])

        if "completed_orders_list" in kwargs:
            self.parse_completed_orders_list(kwargs["completed_orders_list"])

        if "day_trading_stats_dict" in kwargs:
            self.parse_day_trading_stats_dict(kwargs["day_trading_stats_dict"])

    def parse_day_trading_stats_dict(self, day_trading_stats_dict):
        log.info("Parse day_trading_stats_dict")

        day_trading_stats_dict["profit"] = round(
            (
                day_trading_stats_dict["balance_after"]
                - day_trading_stats_dict["balance_before"]
            )
            / day_trading_stats_dict["budget"],
            2,
        )

        self.message += f'DT profit: {day_trading_stats_dict["profit"]}%'

    def parse_portfolio_dict(self, portfolio_dict):
        log.info("Parse portfolio_dict")

        free_funds = "\n".join(
            [
                f"> {account}: {funds}"
                for account, funds in portfolio_dict["buying_power"].items()
            ]
        )
        self.message += f'Total value: {round(portfolio_dict["total_own_capital"])}\n\nTotal free funds:\n{free_funds}\n\n'

    def parse_watchlists_analysis_log(self, watchlists_analysis_log_list):
        log.info("Parse watchlists_analysis_log_list")

        self.message = "\n".join(watchlists_analysis_log_list)

    def parse_orders_dict(self, orders_dict):
        log.info("Parse orders_dict")

        for order_type, orders_list in orders_dict.items():
            if len(orders_list) == 0:
                continue

            self.message += f"{order_type.upper()} orders:\n\n"
            for order_dict in orders_list:
                message_list = list()

                if order_type == "buy":
                    message_list = [
                        f"> Ticker: {order_dict['name']} ({order_dict['ticker_yahoo']})",
                        f">> Budget: {order_dict['budget']} SEK",
                    ]

                elif order_type == "sell":
                    message_list = [
                        f"> Ticker: {order_dict['name']} ({order_dict['ticker_yahoo']})",
                        f">> Value: {round(float(order_dict['price']) * int(order_dict['volume']))} SEK",
                        f">> Profit: {order_dict['profit']} %",
                    ]

                elif order_type == "take_profit":
                    message_list = [
                        f"> Ticker: {order_dict['name']} ({order_dict['ticker_yahoo']})",
                        f">> Value: {round(float(order_dict['price']) * int(order_dict['volume']))} SEK",
                        f">> Profit: {order_dict['profit']} %",
                    ]

                self.message += "\n".join(message_list + ["\n"])

        return self.message

    def parse_completed_orders_list(self, completed_orders_list):
        log.info("Parse completed_orders_list")

        orders_list = [
            " / ".join([f"{k}: {v}" for k, v in order_dict.items()])
            for order_dict in completed_orders_list
        ]

        self.message = "\n".join(orders_list)

        return self.message

    def dump_to_telegram(self):
        log.info("Dump to Telegram")

        telegram_send.send(messages=[self.message])
