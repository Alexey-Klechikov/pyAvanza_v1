import telegram_send

class Log:
    def __init__(self, orders_dict, portfolio_dict):
        self.message = self.parse(orders_dict, portfolio_dict)

    def parse(self, orders_dict, portfolio_dict):
        free_funds = "\n".join([f"> {account}: {funds}" for account, funds in portfolio_dict["buying_power"].items()])
        message = f'Total value: {portfolio_dict["total_own_capital"]}\nTotal free funds:\n{free_funds}\n\n'

        for order_type, orders_list in orders_dict.items():
            if len(orders_list) == 0:
                continue
            
            # TODO - ticker - hyperlink

            message += f'Type: {order_type}\n'
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

                message += '\n'.join(message_list + ["\n"])
            message += '\n'
        return message

    def dump_to_telegram(self):
        telegram_send.send(messages=[self.message])