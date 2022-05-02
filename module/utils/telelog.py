"""
This module is used to process and dump execution logs to Telegram
"""


import telegram_send, logging

log = logging.getLogger('main.telelog')


class TeleLog:
    def __init__(self, **kwargs):
        self.message = ''

        if 'portfolio_dict' in kwargs:
            self.parse_portfolio_dict(kwargs['portfolio_dict'])

        if 'orders_dict' in kwargs:
            self.parse_orders_dict(kwargs['orders_dict'])
        
        if 'watchlists_analysis_log_list' in kwargs:
            self.parse_watchlists_analysis_log(kwargs['watchlists_analysis_log_list'])

    def parse_portfolio_dict(self, portfolio_dict):
        log.info('Parse portfolio_dict')

        free_funds = "\n".join([f"> {account}: {funds}" for account, funds in portfolio_dict["buying_power"].items()])
        self.message += f'Total value: {portfolio_dict["total_own_capital"]}\nTotal free funds:\n{free_funds}\n\n'

    def parse_watchlists_analysis_log(self, watchlists_analysis_log_list):
        log.info('Parse watchlists_analysis_log_list')

        self.message = '\n'.join(watchlists_analysis_log_list)

    def parse_orders_dict(self, orders_dict):
        log.info('Parse orders_dict')

        for order_type, orders_list in orders_dict.items():
            if len(orders_list) == 0:
                continue
            
            # TODO - ticker - hyperlink

            self.message += f'Type: {order_type}\n'
            for order in orders_list:
                message_list = list()
                if order_type == 'buy':
                    message_list = [
                        f"Ticker: {order['name']} ({order['ticker_yahoo']})",
                        f"Budget: {order['budget']} SEK"]
                elif order_type == 'sell':
                    message_list = [
                        f"Ticker: {order['name']} ({order['ticker_yahoo']})",
                        f"Value: {round(float(order['price']) * int(order['volume']))} SEK",
                        f"Profit: {order['profit']} %"]

                self.message += '\n'.join(message_list + ["\n"])
        return self.message

    def dump_to_telegram(self):
        log.info('Dump to Telegram')

        telegram_send.send(messages=[self.message])