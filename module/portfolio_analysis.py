"""
This module is the "frontend" meant for everyday run. It will perform analysis on stocks and trigger trades.
It will import other modules to run the analysis on the stocks -> place orders -> dump log in Telegram.py
It will be run from Telegram or automatically as cron-job.
"""


from .utils.context import Context
from .utils.strategy import Strategy
from .utils.settings import Settings
from .utils.log import Log


class Portfolio_Analysis:
    def __init__(self, **kwargs):
        self.strategies_dict = Strategy.load()
        self.signals_dict = kwargs.get('signals_dict', dict())

        self.run_analysis(kwargs['user'], kwargs['accounts_dict'], kwargs['log_to_telegram'])

    def get_signal_on_ticker(self, ticker):
        if ticker not in self.signals_dict:
            try:
                strategy_obj = Strategy(ticker, strategies_list=self.strategies_dict.get(ticker, list()))
            except Exception as e:
                print(f'(!) There was a problem with the ticker "{ticker}": {e}')
                return None

            self.signals_dict[ticker] = {
                'signal': strategy_obj.summary["signal"],
                'return': strategy_obj.summary['max_output']['result']}
        return self.signals_dict[ticker]

    def create_sell_orders(self, ava):
        print(f'> Walk through portfolio')
        orders_list, portfolio_tickers_list = list(), list()
        if ava.portfolio_dict['positions']['df'] is not None:
            for i, row in ava.portfolio_dict['positions']['df'].iterrows():
                print(f'>> Portfolio ({int(i) + 1}/{ava.portfolio_dict["positions"]["df"].shape[0]}): {row["ticker_yahoo"]}')

                portfolio_tickers_list.append(row["ticker_yahoo"])

                signal_dict = self.get_signal_on_ticker(row["ticker_yahoo"])
                if signal_dict is None or signal_dict['signal'] == 'buy':
                    continue

                orders_list.append({
                    'account_id': row['accountId'], 
                    'order_book_id': row['orderbookId'], 
                    'volume': row['volume'], 
                    'price': row['lastPrice'],
                    'profit': row['profitPercent'],
                    'name': row['name'],
                    'ticker_yahoo': row["ticker_yahoo"],
                    'max_return': signal_dict['return']})

        ava.create_orders(orders_list, 'sell')

        return orders_list, portfolio_tickers_list

    def create_buy_orders(self, ava, portfolio_tickers_list):
        print(f'> Walk through budget lists')
        orders_list = list()
        for budget_rule_name, watchlist_dict in ava.budget_rules_dict.items():
            for ticker_dict in watchlist_dict['tickers']:
                if ticker_dict['ticker_yahoo'] in portfolio_tickers_list: 
                    continue

                print(f'>> Budget list "{budget_rule_name}": {ticker_dict["ticker_yahoo"]}')
                
                signal_dict = self.get_signal_on_ticker(ticker_dict['ticker_yahoo'])
                if signal_dict is None or signal_dict['signal'] == 'sell':
                    continue

                stock_price_dict = ava.get_stock_price(ticker_dict['order_book_id'])
                try:
                    volume = int(int(budget_rule_name) * 1000 // stock_price_dict['buy'])
                except:
                    print(f"There was a problem with fetching buy price for {ticker_dict['ticker_yahoo']}")
                    continue

                orders_list.append({
                    'ticker_yahoo': ticker_dict['ticker_yahoo'],
                    'order_book_id': ticker_dict['order_book_id'], 
                    'budget': int(budget_rule_name) * 1000,
                    'price': stock_price_dict['buy'],
                    'volume': volume,
                    'name': ticker_dict['name'],
                    'max_return': signal_dict['return']})

        created_orders_list = ava.create_orders(orders_list, 'buy')
        
        return created_orders_list

    def run_analysis(self, user, accounts_dict, log_to_telegram):
        print(f'Running analysis for account(s): {" & ".join(accounts_dict)}')
        ava = Context(user, accounts_dict)
        ava.remove_active_orders()

        created_orders_dict = dict()
        created_orders_dict['sell'], portfolio_tickers_list = self.create_sell_orders(ava)
        created_orders_dict['buy'] = self.create_buy_orders(ava, portfolio_tickers_list)

        # Dump log to Telegram
        if log_to_telegram:
            log_obj = Log(
                portfolio_dict=ava.get_portfolio(), 
                orders_dict=created_orders_dict)
            log_obj.dump_to_telegram()


def run(): 
    settings_obj = Settings()
    settings_json = settings_obj.load()  

    signals_dict = dict()
    for user, settings_per_account_dict in settings_json.items():
        for settings_dict in settings_per_account_dict.values():
            if not settings_dict['run_script_daily']:
                continue

            walkthrough_obj = Portfolio_Analysis(
                user=user,
                accounts_dict=settings_dict["accounts"],
                signals_dict=signals_dict,
                log_to_telegram=settings_dict.get("log_to_telegram", True),
                buy_delay_after_sell=settings_dict.get("buy_delay_after_sell", 2))
            signals_dict = walkthrough_obj.signals_dict