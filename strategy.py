from pprint import pprint
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import os, pickle

pd.options.mode.chained_assignment = None
pd.set_option('display.max_columns', 500)
pd.options.mode.chained_assignment = None
pd.set_option('display.expand_frame_repr', False)
pd.set_option('max_colwidth', None)
pd.options.display.max_rows = 99999
pd.options.display.max_columns = 99999
pd.options.display.encoding = 'UTF-8'
pd.options.display.float_format = '{:.2f}'.format


class Strategy:
    def __init__(self, ticker_id, ticker_name='', cache=False):
        self.ticker_obj, history_df = self.read_ticker(ticker_id, cache)
        self.history_df, conditions_dict = self.prepare_conditions(history_df)
        strategies_dict = self.generate_strategies(conditions_dict)
        self.summary = self.get_signal(ticker_name, strategies_dict)

    def read_ticker(self, ticker_symbol, cache):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        pickle_path = f'{current_dir}/cache/{ticker_symbol}.pickle'

        directory_exists = os.path.exists('/'.join(pickle_path.split('/')[:-1]))
        if not directory_exists:
            os.makedirs('/'.join(pickle_path.split('/')[:-1]))

        if not cache:
            if os.path.exists(pickle_path):
                os.remove(pickle_path)

        # Check if cache exists (and is completed)
        while True:
            try:
                if not os.path.exists(pickle_path):
                    with open(pickle_path, 'wb') as pcl:
                        ticker_obj = yf.Ticker(
                            ticker_symbol)
                        history_df = ticker_obj.history(
                            period="18mo")

                        cache = (ticker_obj, history_df)
                        pickle.dump(cache, pcl)
                with open(pickle_path, 'rb') as token:
                    cache = pickle.load(token)
                    break
            except EOFError:
                # If cache was not created properly earlier - delete it and try again
                os.remove(pickle_path)

        return cache

    def prepare_conditions(self, history_df):
        conditions_dict = {"HOLD": {
            "buy": lambda x: True,
            "sell": lambda x: False}}

        ''' Candle '''
        # Heikin-Ashi
        history_df.ta.ha(append=True)
        conditions_dict["HA"] = {
            'buy': lambda x: (x['HA_open'] < x["HA_close"]) and (x['HA_low'] == x["HA_open"]),
            'sell': lambda x: (x['HA_open'] > x["HA_close"]) and (x['HA_high'] == x["HA_open"])}

        ''' Trend ''' 
        # PSAR (Parabolic Stop and Reverse)
        history_df.ta.psar(append=True)
        conditions_dict["PSAR"] = {
            'buy': lambda x: x['Close'] > x["PSARl_0.02_0.2"],
            'sell': lambda x: x['Close'] < x["PSARs_0.02_0.2"]}

        # CHOP (Choppiness Index)
        history_df.ta.chop(append=True)
        conditions_dict["CHOP"] = {
            'buy': lambda x: x["CHOP_14_1_100"] < 60,
            'sell': lambda x: x["CHOP_14_1_100"] > 60}

        # CKSP (Chande Kroll Stop)
        history_df.ta.cksp(append=True)
        conditions_dict["CKSP"] = {
            'buy': lambda x: x["CKSPl_10_3_20"] > x['CKSPs_10_3_20'],
            'sell': lambda x: x["CKSPl_10_3_20"] < x['CKSPs_10_3_20']}

        ''' Overlap '''
        ## ALMA (Arnaud Legoux Moving Average)
        history_df.ta.alma(length=15, append=True)
        conditions_dict["ALMA"] = {
            'buy': lambda x: x['Close'] > x['ALMA_15_6.0_0.85'],
            'sell': lambda x: x['Close'] < x['ALMA_15_6.0_0.85']}
        history_df.ta.alma(length=50, append=True)
        history_df.rename(columns={'ALMA_50_6.0_0.85': 'ALMA-LONG_50_6.0_0.85'}, inplace=True)
        conditions_dict["ALMA_LONG"] = {
            'buy': lambda x: x['Close'] > x['ALMA-LONG_50_6.0_0.85'],
            'sell': lambda x: x['Close'] < x['ALMA-LONG_50_6.0_0.85']}

        ## GHLA (Gann High-Low Activator)
        history_df.ta.hilo(append=True)
        conditions_dict["GHLA"] = {
            'buy': lambda x: x['Close'] > x['HILO_13_21'],
            'sell': lambda x: x['Close'] < x['HILO_13_21']}

        ## SUPERTREND
        history_df.ta.supertrend(append=True)
        conditions_dict["SUPERT"] = {
            'buy': lambda x: x['Close'] > x['SUPERT_7_3.0'],
            'sell': lambda x: x['Close'] < x['SUPERT_7_3.0']}

        ''' Momentum '''
        # RSI (Relative Strength Index)
        history_df.ta.rsi(length=14, append=True)
        conditions_dict["RSI"] = {
            'buy': lambda x: x['RSI_14'] > 50,
            'sell': lambda x: x['RSI_14'] < 50}

        ## MACD (Moving Average Convergence Divergence)
        history_df.ta.macd(fast=8, slow=21, signal=5, append=True)
        conditions_dict["MACD"] = {
            'buy': lambda x: x['MACD_8_21_5'] > x['MACDs_8_21_5'],
            'sell': lambda x: x['MACD_8_21_5'] < x['MACDs_8_21_5']}

        ## STOCH (Stochastic Oscillator)
        history_df.ta.stoch(k=14, d=3, append=True)
        conditions_dict["STOCH"] = {
            'buy': lambda x: x["STOCHd_14_3_3"] < 80 and x["STOCHk_14_3_3"] < 80,
            'sell': lambda x: x["STOCHd_14_3_3"] > 20 and x["STOCHk_14_3_3"] > 20}

        # Reference horizontal lines
        for level in (20, 25, 30, 40, 50, 60, 70, 75, 80):
            history_df[f'hline_{level}'] = level

        return history_df.iloc[100:], conditions_dict

    def generate_strategies(self, conditions_dict):
        strategies_list = [
            ['HOLD']]        
        # Overlap 
        strategies_list += [
            ['MACD', 'RSI'],
            ['MACD', 'RSI', 'STOCH'],
            ['MACD', 'STOCH'],
            ['ALMA', 'ALMA_LONG'],
            ['GHLA', 'ALMA']]
        # Overlap - Trend
        strategies_list += [
            ['ALMA', 'PSAR'],
            ['ALMA', 'CKSP'],
            ['ALMA', 'CHOP'],
            ['GHLA', 'PSAR'],
            ['GHLA', 'CHOP'],
            ['SUPERT', 'PSAR'],
            ['SUPERT', 'CHOP'],
            ['SUPERT', 'CKSP']]
        # Overlap - Momentum
        strategies_list += [
            ['ALMA', 'MACD'],
            ['GHLA', 'RSI'],
            ['SUPERT', 'RSI'],
            ['SUPERT', 'STOCH'],
            ['SUPERT', 'RSI', 'STOCH']]
        # Momentum - Trend
        strategies_list += [
            ['MACD', 'PSAR'],
            ['MACD', 'CKSP'],
            ['MACD', 'CHOP'],
            ['RSI', 'CHOP'],
            ['STOCH', 'PSAR'],
            ['STOCH', 'CKSP'],
            ['STOCH', 'CHOP']]
        # Candle - Momentum
        strategies_list += [
            ['MACD', 'RSI', 'HA']]
        # Overlap - Candle
        strategies_list += [
            ['GHLA', 'HA']]

        strategies_dict = dict()
        for strategy_list in strategies_list:
            strategy_dict = dict()
            for order_type in ('buy', 'sell'):
                strategy_dict[order_type] = [conditions_dict[strategy_component][order_type] for strategy_component in strategy_list]
            strategies_dict[' + '.join(strategy_list)] = strategy_dict
        return strategies_dict

    def get_signal(self, ticker_name, strategies_dict):   
        summary = {
            "ticker_name": ticker_name,
            "strategies": dict(),
            "max_output": dict()}
        
        for strategy in strategies_dict:
            summary["strategies"][strategy] = {
                'transactions': list(),
                'result': 0}

            transaction_comission = 0.0025

            balance_list = list()
            balance_dict = {
                'deposit': 1000,
                'market': None,
                'total': 1000,
                'order_price': 0}
            for i, row in self.history_df.iterrows():
                date = str(i)[:10]

                # Sell event
                if  all(map(lambda x: x(row), strategies_dict[strategy]["sell"])) and balance_dict['market'] is not None:
                    summary["strategies"][strategy]['transactions'].append(f'({date}) Sell at {row["Close"]}')
                    price_change = (row["Close"] - balance_dict['order_price']) / balance_dict['order_price']
                    balance_dict['deposit'] = balance_dict['market'] * (1 + price_change) * (1 - transaction_comission)
                    balance_dict['market'] = None
                    balance_dict['total'] = balance_dict['deposit']

                # Buy event
                elif all(map(lambda x: x(row), strategies_dict[strategy]["buy"])) and balance_dict['deposit'] is not None:
                    summary["strategies"][strategy]['transactions'].append(f'({date}) Buy at {row["Close"]}')
                    balance_dict['order_price'] = row["Close"]
                    balance_dict['market'] = balance_dict['deposit'] * (1 - transaction_comission)
                    balance_dict['deposit'] = None
                    balance_dict['total'] = balance_dict['market']

                # Hold on market
                else:
                    if balance_dict['deposit'] == None:
                        price_change = (row['Close'] - balance_dict['order_price']) / balance_dict['order_price']
                        balance_dict['total'] = balance_dict['market'] * (1 + price_change)
                        
                balance_list.append(balance_dict['total'])

            summary["strategies"][strategy]['result'] = round(balance_dict['total'])
            summary["strategies"][strategy]['signal'] = 'sell' if balance_dict['market'] is None else 'buy'
            summary["strategies"][strategy]['transactions_counter'] = len(summary["strategies"][strategy]['transactions'])
            if balance_dict['total'] > summary['max_output'].get('result', 0) and strategy != "HOLD":
                self.history_df.loc[:, 'total'] = balance_list

                summary['max_output'] = {
                    'strategy': strategy,
                    'result': summary["strategies"][strategy]['result'],
                    'signal': summary["strategies"][strategy]['signal'],
                    'transactions_counter': summary["strategies"][strategy]['transactions_counter']}

        summary["hold_result"] = summary["strategies"].pop('HOLD')["result"]
        summary["sorted_strategies_list"] = sorted(summary['strategies'].items(), key=lambda x: int(x[1]["result"]), reverse=True)
        sorted_signals_list = [i[1]["signal"] for i in summary["sorted_strategies_list"]]
        summary["top_3_signal"] = sorted_signals_list[2] if len(set(sorted_signals_list[:2])) != 1 else sorted_signals_list[0]
            
        return summary
