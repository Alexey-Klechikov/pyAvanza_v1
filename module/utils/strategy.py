"""
This module contains all technical indicators and strategies generation routines
"""


import yfinance as yf
import pandas_ta as ta
import os, pickle
from copy import copy
import numpy as np

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
pd.options.mode.chained_assignment = None
pd.set_option('display.expand_frame_repr', False)


class Strategy:
    def __init__(self, ticker_id, ticker_name='', cache=False):
        self.ticker_obj, history_df = self.read_ticker(ticker_id, cache)
        self.history_df, conditions_dict = self.prepare_conditions(history_df)
        strategies_dict = self.generate_strategies(conditions_dict)
        self.summary = self.get_signal(ticker_name, strategies_dict)

    def read_ticker(self, ticker_symbol, cache):
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pickle_path = f'{current_dir}/cache/{ticker_symbol}.pickle'

        directory_exists = os.path.exists('/'.join(pickle_path.split('/')[:-1]))
        if not directory_exists:
            os.makedirs('/'.join(pickle_path.split('/')[:-1]))

        if not cache:
            if os.path.exists(pickle_path):
                os.remove(pickle_path)

        # Check if cache exists (and is completed)
        for _ in range(2):
            try:
                if not os.path.exists(pickle_path):
                    with open(pickle_path, 'wb') as pcl:
                        ticker_obj = yf.Ticker(ticker_symbol)
                        history_df = ticker_obj.history(period="18mo")
                        
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
        condition_types_list = ("Blank", "Volatility", "Trend", "Candle", "Overlap", "Momentum", "Volume", "Cycles")
        conditions_dict = {ct:dict() for ct in condition_types_list}

        ''' Blank '''
        conditions_dict['Blank']["HOLD"]= {
            "buy": lambda x: True,
            "sell": lambda x: False}
        
        ''' Cycles '''
        # EBSW (Even Better Sinewave)
        history_df.ta.ebsw(append=True)
        conditions_dict['Cycles']["EBSW"] = {
            'buy': lambda x: x['EBSW_40_10'] > 0.5,
            'sell': lambda x: x['EBSW_40_10'] < -0.5}

        ''' Volume '''
        # PVT (Price Volume Trend)
        history_df.ta.pvt(append=True)
        history_df.ta.sma(close='PVT', length=9, append=True)
        conditions_dict['Volume']["PVT"] = {
            'buy': lambda x: x['SMA_9'] < x['PVT'],
            'sell': lambda x: x['SMA_9'] > x['PVT']}

        # CMF (Chaikin Money Flow)
        history_df.ta.cmf(append=True)
        conditions_dict['Volume']["CMF"] = {
            'buy': lambda x: x["CMF_20"] > 0,
            'sell': lambda x: x["CMF_20"] < 0}

        ''' Volatility '''
        # MASSI (Mass Index)
        history_df.ta.massi(append=True)
        conditions_dict['Volatility']["MASSI"] = {
            'buy': lambda x: 26 < x['MASSI_9_25'] < 27,
            'sell': lambda x: 26 < x['MASSI_9_25'] < 27}

        # HWC (Holt-Winter Channel)
        history_df.ta.hwc(append=True)
        conditions_dict['Volatility']["HWC"] = {
            'buy': lambda x: x['Close'] > x["HWM"],
            'sell': lambda x: x['Close'] < x["HWM"]}
        
        # BBANDS (Bollinger Bands)
        history_df.ta.bbands(length=20, std=2, append=True)
        conditions_dict['Volatility']["BBANDS"] = {
            'buy': lambda x: x['Close'] > x["BBL_20_2.0"],
            'sell': lambda x: x['Close'] < x["BBU_20_2.0"]}

        ''' Candle '''
        # HA (Heikin-Ashi)
        history_df.ta.ha(append=True)
        conditions_dict['Candle']["HA"] = {
            'buy': lambda x: (x['HA_open'] < x["HA_close"]) and (x['HA_low'] == x["HA_open"]),
            'sell': lambda x: (x['HA_open'] > x["HA_close"]) and (x['HA_high'] == x["HA_open"])}

        ''' Trend ''' 
        # PSAR (Parabolic Stop and Reverse)
        history_df.ta.psar(append=True)
        conditions_dict['Trend']["PSAR"] = {
            'buy': lambda x: x['Close'] > x["PSARl_0.02_0.2"],
            'sell': lambda x: x['Close'] < x["PSARs_0.02_0.2"]}

        # CHOP (Choppiness Index)
        history_df.ta.chop(append=True)
        conditions_dict["Trend"]["CHOP"] = {
            'buy': lambda x: x["CHOP_14_1_100"] < 61.8,
            'sell': lambda x: x["CHOP_14_1_100"] > 61.8}

        # CKSP (Chande Kroll Stop)
        history_df.ta.cksp(append=True)
        conditions_dict["Trend"]["CKSP"] = {
            'buy': lambda x: x["CKSPl_10_3_20"] > x['CKSPs_10_3_20'],
            'sell': lambda x: x["CKSPl_10_3_20"] < x['CKSPs_10_3_20']}

        ''' Overlap '''
        # ALMA (Arnaud Legoux Moving Average)
        history_df.ta.alma(length=15, append=True)
        conditions_dict["Overlap"]["ALMA"] = {
            'buy': lambda x: x['Close'] > x['ALMA_15_6.0_0.85'],
            'sell': lambda x: x['Close'] < x['ALMA_15_6.0_0.85']}
        history_df.ta.alma(length=50, append=True)
        history_df.rename(columns={'ALMA_50_6.0_0.85': 'ALMA-LONG_50_6.0_0.85'}, inplace=True)
        conditions_dict["Overlap"]["ALMA_LONG"] = {
            'buy': lambda x: x['Close'] > x['ALMA-LONG_50_6.0_0.85'],
            'sell': lambda x: x['Close'] < x['ALMA-LONG_50_6.0_0.85']}

        # GHLA (Gann High-Low Activator)
        history_df.ta.hilo(append=True)
        conditions_dict["Overlap"]["GHLA"] = {
            'buy': lambda x: x['Close'] > x['HILO_13_21'],
            'sell': lambda x: x['Close'] < x['HILO_13_21']}

        # SUPERT (Supertrend)
        history_df.ta.supertrend(append=True)
        conditions_dict["Overlap"]["SUPERT"] = {
            'buy': lambda x: x['Close'] > x['SUPERT_7_3.0'],
            'sell': lambda x: x['Close'] < x['SUPERT_7_3.0']}

        ''' Momentum '''
        # RSI (Relative Strength Index)
        history_df.ta.rsi(length=14, append=True)
        conditions_dict['Momentum']["RSI"] = {
            'buy': lambda x: x['RSI_14'] > 50,
            'sell': lambda x: x['RSI_14'] < 50}

        # RVGI (Relative Vigor Index)
        history_df.ta.rvgi(append=True)
        conditions_dict['Momentum']["RVGI"] = {
            'buy': lambda x: x['RVGI_14_4'] > x['RVGIs_14_4'],
            'sell': lambda x: x['RVGI_14_4'] < x['RVGIs_14_4']}

        # MACD (Moving Average Convergence Divergence)
        history_df.ta.macd(fast=8, slow=21, signal=5, append=True)
        conditions_dict['Momentum']["MACD"] = {
            'buy': lambda x: x['MACD_8_21_5'] > x['MACDs_8_21_5'],
            'sell': lambda x: x['MACD_8_21_5'] < x['MACDs_8_21_5']}

        # STOCH (Stochastic Oscillator)
        history_df.ta.stoch(k=14, d=3, append=True)
        conditions_dict['Momentum']["STOCH"] = {
            'buy': lambda x: x["STOCHd_14_3_3"] < 80 and x["STOCHk_14_3_3"] < 80,
            'sell': lambda x: x["STOCHd_14_3_3"] > 20 and x["STOCHk_14_3_3"] > 20}

        return history_df.iloc[100:], conditions_dict

    def generate_strategies(self, conditions_dict):
        strategies_list = [
            [('Blank', 'HOLD')],
            [('Momentum', 'MACD'), ('Momentum', 'RSI'), ('Momentum', 'STOCH')],
            [('Momentum', 'MACD'), ('Momentum', 'STOCH')],
            [("Overlap", 'ALMA'), ("Overlap", 'ALMA_LONG')]]

        # + Triple indicator strategies (try every combination of different types)
        indicators_list = list()
        special_case_indicators_list = ('HOLD', 'ALMA_LONG') # should not participate in autogenerating strategies
        for indicator_type, indicators_dict in conditions_dict.items():
            indicators_list += [(indicator_type, indicator) for indicator in indicators_dict.keys() if indicator not in special_case_indicators_list]
        
        for i_1, indicator_1 in enumerate(indicators_list):
            temp_indicators_list = indicators_list[i_1:]
            for i_2, indicator_2 in enumerate(temp_indicators_list):
                if indicator_1[0] == indicator_2[0]:
                    continue
                for indicator_3 in temp_indicators_list[i_2:]:
                    if indicator_2[0] == indicator_3[0]:
                        continue
                    strategies_list.append([indicator_1, indicator_2, indicator_3])              

        strategies_dict = dict()
        for strategy_list in strategies_list:
            strategy_dict = dict()
            for order_type in ('buy', 'sell'):
                strategy_dict[order_type] = [conditions_dict[strategy_component[0]][strategy_component[1]][order_type] for strategy_component in strategy_list]
            strategies_dict[' + '.join([f"({i[0]}) {i[1]}" for i in strategy_list])] = strategy_dict
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
                'order_price': 0,
                'buy_signal': np.nan,
                'sell_signal': np.nan}
            for i, row in self.history_df.iterrows():
                date = str(i)[:10]

                # Sell event
                if  all(map(lambda x: x(row), strategies_dict[strategy]["sell"])) and balance_dict['market'] is not None:
                    summary["strategies"][strategy]['transactions'].append(f'({date}) Sell at {row["Close"]}')
                    price_change = (row["Close"] - balance_dict['order_price']) / balance_dict['order_price']
                    balance_dict['deposit'] = balance_dict['market'] * (1 + price_change) * (1 - transaction_comission)
                    balance_dict['market'] = None
                    balance_dict['total'] = balance_dict['deposit']
                    balance_dict['sell_signal'] = balance_dict['total']

                # Buy event
                elif all(map(lambda x: x(row), strategies_dict[strategy]["buy"])) and balance_dict['deposit'] is not None:
                    summary["strategies"][strategy]['transactions'].append(f'({date}) Buy at {row["Close"]}')
                    balance_dict['buy_signal'] = balance_dict['total']
                    balance_dict['order_price'] = row["Close"]
                    balance_dict['market'] = balance_dict['deposit'] * (1 - transaction_comission)
                    balance_dict['deposit'] = None
                    balance_dict['total'] = balance_dict['market']

                # Hold on market
                else:
                    if balance_dict['deposit'] is None:
                        price_change = (row['Close'] - balance_dict['order_price']) / balance_dict['order_price']
                        balance_dict['total'] = balance_dict['market'] * (1 + price_change)
                        balance_dict['buy_signal'] = np.nan
                        balance_dict['sell_signal'] = np.nan

                balance_list.append(copy(balance_dict))

            summary["strategies"][strategy]['result'] = round(balance_dict['total'])
            summary["strategies"][strategy]['signal'] = 'sell' if balance_dict['market'] is None else 'buy'
            summary["strategies"][strategy]['transactions_counter'] = len(summary["strategies"][strategy]['transactions'])
            if balance_dict['total'] > summary['max_output'].get('result', 0) and strategy != "(Blank) HOLD":
                for col in ['total', 'buy_signal', 'sell_signal']:
                    self.history_df.loc[:, col] = [i[col] for i in balance_list]

                summary['max_output'] = {
                    'strategy': strategy,
                    'result': summary["strategies"][strategy]['result'],
                    'signal': summary["strategies"][strategy]['signal'],
                    'transactions_counter': summary["strategies"][strategy]['transactions_counter']}

        summary["hold_result"] = summary["strategies"].pop('(Blank) HOLD')["result"]
        summary["sorted_strategies_list"] = sorted(summary['strategies'].items(), key=lambda x: int(x[1]["result"]), reverse=True)
        summary["top_3_signal"] = summary['max_output']["signal"]
        
        sorted_signals_list = [i[1]["signal"] for i in summary["sorted_strategies_list"]]
        if summary['max_output']['transactions_counter'] == 1:
            summary["top_3_signal"] = 'buy' if sorted_signals_list[:3].count('buy') >= 2 else 'sell'

        return summary 