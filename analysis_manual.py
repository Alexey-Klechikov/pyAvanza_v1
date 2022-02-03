from pprint import pprint
from module import Context, Strategy, Plot
import pandas as pd


class Analysis:
    def __init__(self, **kwargs):
        self.total_df = None
        self.visited_tickers = list()
        self.counter_per_strategy = {'-- MAX --': {'result': 0, 'transactions_counter': 0}}

        self.plot_tickers_list = kwargs['plot_tickers_list']
        self.plot_portfolio_tickers = kwargs['plot_portfolio_tickers']
        self.print_transactions_bool = kwargs['print_transactions_bool']
        self.show_only_tickers_to_act_on_bool = kwargs['show_only_tickers_to_act_on']

        self.run(kwargs['check_only_watchlist_bool'], kwargs['cache'])
        self.print_performance_per_strategy()
        self.plot_performance_compared_to_hold(kwargs['plot_total_algo_performance_vs_hold'])

    def plot_ticker(self, strategy_obj):
        plot_obj = Plot(
            data_df=strategy_obj.history_df, 
            title=f'{strategy_obj.ticker_obj.info["symbol"]} ({strategy_obj.ticker_obj.info["shortName"]}) - {strategy_obj.summary["max_output"]["strategy"]}')
        plot_obj.create_extra_panels()
        plot_obj.show_single_ticker()

    def plot_performance_compared_to_hold(self, plot_total_algo_performance_vs_hold):
        if not plot_total_algo_performance_vs_hold:
            return
        
        columns_dict = {
            'Close': list(),
            'total': list()}
        for col in self.total_df.columns:
            for column_to_merge in columns_dict:
                if col.startswith(column_to_merge):
                    columns_dict[column_to_merge].append(col)
        
        for result_column, columns_to_merge_list in columns_dict.items():
            self.total_df[result_column] = self.total_df[columns_to_merge_list].sum(axis=1)
        
        plot_obj = Plot(
            data_df=self.total_df, 
            title=f'Total HOLD (red) vs Total algo (black)')
        plot_obj.show_entire_portfolio()
    
    def print_performance_per_strategy(self):
        result_dict = self.counter_per_strategy.pop('-- MAX --')
        result_message = [f'-- MAX -- : {str(result_dict)}']
        sorted_strategies = sorted(self.counter_per_strategy.items(), key=lambda x: int(x[1]["total_sum"]), reverse=True)
        print('\n' + '\n'.join(result_message + [f'{strategy[0]}: {strategy[1]}' for strategy in sorted_strategies]))

    def record_ticker_performance(self, strategy_obj, ticker):
        self.total_df = strategy_obj.history_df if self.total_df is None else pd.merge(
            self.total_df, strategy_obj.history_df,
            how='outer',
            left_index=True, 
            right_index=True)
        self.total_df['Close'] = self.total_df['Close'] / (self.total_df['Close'].values[0] / 1000)
        self.total_df.rename(
            columns={
                'Close': f'Close / {ticker}',
                'total': f'total / {ticker} / {strategy_obj.summary["max_output"]["strategy"]}'}, 
            inplace=True)
        self.total_df = self.total_df[[i for i in self.total_df.columns if (i.startswith('Close') or i.startswith('total'))]]

    def get_strategy_on_ticker(self, ticker, comment, in_portfolio_bool, cache):
        if ticker in self.visited_tickers:
            return 
        self.visited_tickers.append(ticker)

        try:
            strategy_obj = Strategy(ticker, comment, cache)
        except Exception as e: 
            print(f'\n--- (!) There was a problem with the ticker "{ticker}": {e} ---')
            return

        if self.show_only_tickers_to_act_on_bool and (
            (in_portfolio_bool and strategy_obj.summary['top_3_signal'] == 'buy') or 
            (not in_portfolio_bool and strategy_obj.summary['top_3_signal'] == 'sell')):
            return

        # Print the result for all strategies AND count per strategy performance
        top_signal = strategy_obj.summary["max_output"].pop("signal")
        top_3_signal = strategy_obj.summary["top_3_signal"]
        signal = top_signal if top_signal == top_3_signal else f"{top_signal} ->> {top_3_signal}"
        max_output_summary = f'signal: {signal} / ' + ' / '.join([f'{k}: {v}' for k, v in strategy_obj.summary["max_output"].items() if k in ("result", "transactions_counter")])
        print(f'\n--- {strategy_obj.summary["ticker_name"]} ({max_output_summary}) (HOLD: {strategy_obj.summary["hold_result"]}) ---\n')

        for parameter in ('result', 'transactions_counter'):
            self.counter_per_strategy['-- MAX --'][parameter] += strategy_obj.summary["max_output"][parameter]

        for i, strategy_item_list in enumerate(strategy_obj.summary["sorted_strategies_list"]):
            strategy, strategy_data_dict = strategy_item_list[0], strategy_item_list[1]
            
            self.counter_per_strategy.setdefault(strategy, {'total_sum': 0, 'win_counter': dict(), 'transactions_counter': 0})
            self.counter_per_strategy[strategy]['total_sum'] += strategy_data_dict["result"]
            self.counter_per_strategy[strategy]['transactions_counter'] += len(strategy_data_dict["transactions"])
            
            if i < 3: 
                print(f'Strategy: {strategy} -> {strategy_data_dict["result"]} (number_transactions: {len(strategy_data_dict["transactions"])}) (signal: {strategy_data_dict["signal"]})')
                [print(f'> {t}') for t in strategy_data_dict["transactions"] if self.print_transactions_bool]
                
                self.counter_per_strategy[strategy]['win_counter'].setdefault(f'{i+1}', 0)
                self.counter_per_strategy[strategy]['win_counter'][f'{i+1}'] += 1

        # Plot
        if (ticker in self.plot_tickers_list) or (self.plot_portfolio_tickers and in_portfolio_bool):
            self.plot_ticker(strategy_obj)

        # Create a DF with all best strategies vs HOLD
        self.record_ticker_performance(strategy_obj, ticker)

    def run(self, check_only_watchlist_bool, cache):
        ava_ctx = Context(
            user='ava_elbe',
            accounts_dict={
                'Bostad - Elena': 6574382, 
                'Bostad - Alex': 9568450})
        
        in_portfolio_bool = False
        if check_only_watchlist_bool:
            # Watch lists
            for watch_list_name, tickers_list in ava_ctx.watch_lists_dict.items():
                for ticker_dict in tickers_list:
                    self.get_strategy_on_ticker(
                        ticker_dict['ticker_yahoo'], 
                        f"{watch_list_name}: {ticker_dict['ticker_yahoo']}",
                        in_portfolio_bool,
                        cache)
        else:
            # Portfolio
            in_portfolio_bool = True
            if ava_ctx.portfolio_dict['positions']['df'] is not None:
                for _, row in ava_ctx.portfolio_dict['positions']['df'].iterrows():
                    self.get_strategy_on_ticker(
                        row["ticker_yahoo"], 
                        f"Stock: {row['name']} - {row['ticker_yahoo']}",
                        in_portfolio_bool,
                        cache)

            # Budget lists
            for budget_rule_name, tickers_list in ava_ctx.budget_rules_dict.items():
                for ticker_dict in tickers_list:
                    self.get_strategy_on_ticker(
                        ticker_dict['ticker_yahoo'], 
                        f"Budget {budget_rule_name}K: {ticker_dict['ticker_yahoo']}",
                        in_portfolio_bool,
                        cache)


if __name__ == '__main__':
    Analysis(
        check_only_watchlist_bool=False,
        show_only_tickers_to_act_on=False,
        
        print_transactions_bool=False, 
        
        plot_tickers_list=['BUFAB.ST', 'PFE.ST', 'SEB-C.ST'], 
        plot_portfolio_tickers=False,
        plot_total_algo_performance_vs_hold=True,
                
        cache=True)
