"""
This module contains all tooling to communicate to Avanza
"""


from avanza import Avanza, OrderType
import datetime, time, keyring
import pandas as pd


class Context:
    def __init__(self, user, accounts_dict):
        self.ctx = self.get_ctx(user)
        self.accounts_dict = accounts_dict
        self.portfolio_dict = self.get_portfolio()
        self.budget_rules_dict, self.watchlists_dict = self.process_watchlists()

    def get_ctx(self, user):
        i = 1
        while True:
            try:
                ctx = Avanza({
                    'username': keyring.get_password(user, 'un'),
                    'password': keyring.get_password(user, 'pass'),
                    'totpSecret': keyring.get_password(user, 'totp')})
                break
            except Exception as e:
                print(e)
                i += 1
                time.sleep(i*2)   

        return ctx

    def get_portfolio(self):  
        positions_dict = self.ctx.get_positions()  
        portfolio_dict = {
            'buying_power': {k:self.ctx.get_account_overview(v)["buyingPower"] for k,v in self.accounts_dict.items()},
            'total_own_capital': round(sum([self.ctx.get_account_overview(v)["ownCapital"] for v in self.accounts_dict.values()])),
            'positions': {
                'dict': None,
                'df': None}}

        positions_list = [i for i in positions_dict['instrumentPositions'][0]['positions'] if int(i['accountId']) in self.accounts_dict.values()]
        if len(positions_list) != 0:
            portfolio_dict['positions'] = {
                'dict': positions_list,
                'df': pd.DataFrame(positions_list)}
            portfolio_dict['positions']['df']['ticker_yahoo'] = portfolio_dict['positions']['df']['orderbookId'].apply(
                lambda x: f"{self.ctx.get_stock_info(x)['tickerSymbol'].replace(' ', '-')}.ST")

        return portfolio_dict

    def process_watchlists(self):
        watchlists_dict, budget_rules_dict = dict(), dict()
        for watchlist_dict in self.ctx.get_watchlists():
            tickers_list = list()
            for order_book_id in watchlist_dict['orderbooks']:
                stock_info_dict = self.ctx.get_stock_info(order_book_id)
                ticker_dict = {
                    "order_book_id": order_book_id,
                    "name": stock_info_dict['name'],
                    "ticker_yahoo": f"{stock_info_dict['tickerSymbol'].replace(' ', '-')}.ST"}
                tickers_list.append(ticker_dict)
            wl_dict = {
                'watchlist_id': watchlist_dict['id'],
                'tickers': tickers_list}

            try: 
                int(watchlist_dict['name'])
                budget_rules_dict[watchlist_dict['name']] = wl_dict
            except:
                watchlists_dict[watchlist_dict['name']] = wl_dict

        return budget_rules_dict, watchlists_dict

    def create_orders(self, orders_dict, buy_delay_after_sell):
        print('> Creating sell orders') 
        if len(orders_dict['sell']):
            for sell_order_dict in orders_dict['sell']:
                print(f'>> (profit {sell_order_dict["profit"]}%) {sell_order_dict["name"]}')
                self.ctx.place_order(
                    account_id=str(sell_order_dict['account_id']),
                    order_book_id=str(sell_order_dict['order_book_id']),
                    order_type=OrderType.SELL,
                    price=self.get_stock_price(sell_order_dict['order_book_id'])["sell"],
                    valid_until=(datetime.datetime.today() + datetime.timedelta(days=1)).date(),
                    volume=sell_order_dict['volume'])
       
            time.sleep(round(float(buy_delay_after_sell) * 60)) # wait for some sell orders to complete
            self.portfolio_dict = self.get_portfolio()

        print('> Creating buy orders') 
        if len(orders_dict['buy']) > 0:
            orders_dict['buy'].sort(
                key=lambda x: (int(x['budget']), int(x['max_return'])), 
                reverse=True)
            created_orders_list = list()
            reserved_budget = {account: 0 for account in self.accounts_dict}
            for buy_order_dict in orders_dict['buy']:
                # Check accounts one by one if enough funds for the order
                for account_name, account_id in self.accounts_dict.items():
                    if self.portfolio_dict['buying_power'][account_name] - reserved_budget[account_name] > buy_order_dict['budget']:
                        print(f'>> ({buy_order_dict["budget"]}) {buy_order_dict["name"]}')

                        self.ctx.place_order(
                            account_id=str(account_id),
                            order_book_id=str(buy_order_dict['order_book_id']),
                            order_type=OrderType.BUY,
                            price=self.get_stock_price(buy_order_dict['order_book_id'])["buy"],
                            valid_until=(datetime.datetime.today() + datetime.timedelta(days=1)).date(),
                            volume=buy_order_dict['volume'])

                        reserved_budget[account_name] += buy_order_dict['budget']
                        created_orders_list.append(buy_order_dict)
                        break
            
            orders_dict['buy'] = created_orders_list

        return orders_dict

    def get_stock_price(self, stock_id):
        stock_info_dict = self.ctx.get_stock_info(stock_id=stock_id)
        stock_price_dict = {
            'buy': stock_info_dict['lastPrice'],
            'sell': stock_info_dict['lastPrice']}

        order_depth_df = pd.DataFrame(stock_info_dict['orderDepthLevels'])
        if not order_depth_df.empty: 
            stock_price_dict['sell'] = max(order_depth_df['buy'].apply(lambda x: x['price']))
            stock_price_dict['buy'] = min(order_depth_df['sell'].apply(lambda x: x['price']))

        return stock_price_dict

    def remove_active_orders(self):
        print('> Removing active orders')
        active_orders_list = self.ctx.get_deals_and_orders()['orders']
        removed_orders_dict = {
            'buy': list(),
            'sell': list()}

        if len(active_orders_list) > 0:
            for order in active_orders_list:
                if int(order['account']['id']) not in list(self.accounts_dict.values()):
                    continue
                
                print(f">> ({order['sum']}) {order['orderbook']['name']}")
                self.ctx.delete_order(
                    account_id=order['account']['id'],
                    order_id=order['orderId'])

                ticker_yahoo = f"{self.ctx.get_stock_info(order['orderbook']['id'])['tickerSymbol'].replace(' ', '-')}.ST"
                removed_orders_dict[order['type'].lower()].append({
                    'account_id': order['account']['id'],
                    'order_book_id': order['orderbook']['id'],
                    'name': order['orderbook']['name'],
                    'price': order['price'],
                    'volume': order['volume'],
                    'ticker_yahoo': ticker_yahoo})

        return removed_orders_dict