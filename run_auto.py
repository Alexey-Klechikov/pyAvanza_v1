from pprint import pprint
from module import Context, Strategy, Log


class Analysis:
    def __init__(self, **kwargs):
        self.signals_dict = kwargs.get('signals_dict', dict())
        self.run(kwargs['user'], kwargs['accounts_dict'], kwargs['log_to_telegram'])

    def get_signal_on_ticker(self, ticker):
        if ticker not in self.signals_dict:
            try:
                strategy_obj = Strategy(ticker)
            except Exception as e:
                print(f'(!) There was a problem with the ticker "{ticker}": {e}')
                return None 

            self.signals_dict[ticker] = {
                'signal': strategy_obj.summary["top_3_signal"],
                'return': strategy_obj.summary['max_output']['result']}
        return self.signals_dict[ticker]

    def run(self, user, accounts_dict, log_to_telegram):
        print(f'Running analysis for account(s): {" & ".join(accounts_dict)}')
        ava_ctx = Context(user, accounts_dict)
        removed_orders_dict = ava_ctx.remove_active_orders()

        orders_dict = {
            'buy': list(),
            'sell': list()}
        
        # Deleted orders
        for order_type, orders_list in removed_orders_dict.items():
            for order in orders_list:
                signal_dict = self.get_signal_on_ticker(order["ticker_yahoo"])
                if signal_dict is None or signal_dict['signal'] != order_type:
                    continue

                stock_price_dict = ava_ctx.get_stock_price(order['order_book_id'])
                orders_dict[order_type].append({
                    'account_id': order['account_id'],
                    'order_book_id': order['order_book_id'],
                    'profit': '-',
                    'name': order['name'],
                    'price': stock_price_dict[order_type],
                    'volume': order['volume'],
                    'budget': stock_price_dict[order_type] * order['volume'],
                    'ticker_yahoo': order["ticker_yahoo"],
                    'max_return': signal_dict['return']})

        # Portfolio
        portfolio_tickers_list = list()
        if ava_ctx.portfolio_dict['positions']['df'] is not None:
            for _, row in ava_ctx.portfolio_dict['positions']['df'].iterrows():
                portfolio_tickers_list.append(row["ticker_yahoo"])

                signal_dict = self.get_signal_on_ticker(row["ticker_yahoo"])
                if signal_dict is None or signal_dict['signal'] == 'buy':
                    continue

                orders_dict['sell'].append({
                    'account_id': row['accountId'], 
                    'order_book_id': row['orderbookId'], 
                    'volume': row['volume'], 
                    'price': row['lastPrice'],
                    'profit': row['profitPercent'],
                    'name': row['name'],
                    'ticker_yahoo': row["ticker_yahoo"],
                    'max_return': signal_dict['return']})

        # Budget lists
        for budget_rule_name, tickers_list in ava_ctx.budget_rules_dict.items():
            for ticker_dict in tickers_list:
                if ticker_dict['ticker_yahoo'] in portfolio_tickers_list: 
                    continue
                
                signal_dict = self.get_signal_on_ticker(ticker_dict['ticker_yahoo'])
                if signal_dict is None or signal_dict['signal'] == 'sell':
                    continue

                stock_price_dict = ava_ctx.get_stock_price(ticker_dict['order_book_id'])
                orders_dict['buy'].append({
                    'ticker_yahoo': ticker_dict['ticker_yahoo'],
                    'order_book_id': ticker_dict['order_book_id'], 
                    'budget': int(budget_rule_name) * 1000,
                    'price': stock_price_dict['buy'],
                    'volume': round(int(budget_rule_name) * 1000 / stock_price_dict['buy']),
                    'name': ticker_dict['name'],
                    'max_return': signal_dict['return']})
        
        # Create orders
        created_orders_dict = ava_ctx.create_orders(orders_dict)

        # Dump log to Telegram
        if log_to_telegram:
            log_obj = Log(created_orders_dict, ava_ctx.portfolio_dict)
            log_obj.dump_to_telegram()

def run():    
    walkthrough_obj = Analysis(
        user='ava_elbe',
        accounts_dict={
            'Bostad - Elena': 6574382, 
            'Bostad - Alex': 9568450},
        log_to_telegram=True)

    Analysis(
        user='ava_elbe',
        accounts_dict={
            'Semester': 1732606},
        signals_dict=walkthrough_obj.signals_dict,
        log_to_telegram=False)

if __name__ == '__main__':
    run()