
import mplfinance as mpf
import matplotlib.pyplot as plt

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

class Plot:
    def __init__(self, data_df, title):
        self.data_df = data_df
        self.title = title

        self.plots_list = list()

    def create_extra_panels(self):
        get_data_columns_dict = lambda x: {i.split('_')[0]:i for i in sorted(self.data_df.columns) if i.startswith(x)}

        # Plotted on top of the main plot
        def _psar(panel_num):
            data_column_dict = get_data_columns_dict('PSAR')
            plot_list = [
                mpf.make_addplot(
                    self.data_df[data],
                    color=color, 
                    panel=panel_num,
                    type='scatter',
                    markersize=5,
                    ) for data, color in ((data_column_dict['PSARl'], 'green'), (data_column_dict['PSARs'], 'red'))]
            self.plots_list += plot_list

        def _alma(panel_num):
            data_column_dict = get_data_columns_dict('ALMA')
            plot_list = [
                mpf.make_addplot(
                    self.data_df[data_column_dict['ALMA']],
                    color='orange', 
                    panel=panel_num)]
            self.plots_list += plot_list

        def _alma_long(panel_num):
            data_column_dict = get_data_columns_dict('ALMA-LONG')
            plot_list = [
                mpf.make_addplot(
                    self.data_df[data_column_dict['ALMA-LONG']],
                    color='blue', 
                    panel=panel_num)]
            self.plots_list += plot_list

        def _ghla(panel_num):
            data_column_dict = get_data_columns_dict('HILO')
            plot_list = [
                mpf.make_addplot(
                    self.data_df[data_column_dict['HILO']],
                    color='blue', 
                    panel=panel_num)]
            self.plots_list += plot_list

        def _supert(panel_num):
            data_column_dict = get_data_columns_dict('SUPERT')
            plot_list = [
                mpf.make_addplot(
                    self.data_df[data_column_dict['SUPERT']],
                    color='blue', 
                    panel=panel_num)]
            self.plots_list += plot_list 

        def _hwc(panel_num):
            plot_list = [mpf.make_addplot(
                self.data_df['HWM'],
                color='brown', 
                panel=panel_num,)]
            self.plots_list += plot_list

        # Plotted each on a separate plot    
        def _rsi(panel_num):
            data_column_dict = get_data_columns_dict('RSI')
            plot_list = [
                mpf.make_addplot(
                    self.data_df[data_column_dict['RSI']],
                    color='orange', 
                    ylim=(0, 100),
                    panel=panel_num,
                    ylabel="RSI")]
            for level, color in ((80, 'red'), (50, 'black'), (20, 'blue')):
                self.data_df[f'hline_{level}'] = level
                plot_list.append(
                    mpf.make_addplot(
                        self.data_df[f'hline_{level}'], 
                        color=color, 
                        ylim=(0, 100),
                        secondary_y=False,
                        panel=panel_num))
            self.plots_list += plot_list
        
        def _macd(panel_num):
            data_column_dict = get_data_columns_dict('MACD')
            plot_lim = (
                0.9 * min([self.data_df[data_column_dict[i]].min() for i in ('MACD', 'MACDh', 'MACDs')]), 
                1.1 * max([self.data_df[data_column_dict[i]].max() for i in ('MACD', 'MACDh', 'MACDs')]))
            plot_list = [
                mpf.make_addplot(
                    self.data_df[data_column_dict['MACD']],
                    ylim=plot_lim,
                    color='orange', 
                    panel=panel_num,
                    ylabel="MACD"),
                mpf.make_addplot(
                    self.data_df[data_column_dict['MACDs']],
                    ylim=plot_lim,
                    color='black', 
                    panel=panel_num,
                    secondary_y=False),
                mpf.make_addplot(
                    self.data_df[data_column_dict['MACDh']], 
                    type='bar',
                    width=0.7,
                    color='dimgray',
                    alpha=1,
                    ylim=plot_lim,
                    secondary_y=False,
                    panel=panel_num)]
            self.plots_list += plot_list

        def _stoch(panel_num):
            data_column_dict = get_data_columns_dict('STOCH')
            plot_lim = (
                0.9 * min([self.data_df[data_column_dict[i]].min() for i in ('STOCHk', 'STOCHd')]), 
                1.1 * max([self.data_df[data_column_dict[i]].max() for i in ('STOCHk', 'STOCHd')]))
            plot_list = [
                mpf.make_addplot(
                    self.data_df[data],
                    ylim=plot_lim,
                    color=color, 
                    panel=panel_num,
                    ylabel="Stoch") for data, color in ((data_column_dict['STOCHk'], 'orange'), (data_column_dict['STOCHd'], 'black'))]     
            for level, color in ((80, 'red'), (20, 'blue')):
                self.data_df[f'hline_{level}'] = level
                plot_list.append(
                    mpf.make_addplot(
                        self.data_df[f'hline_{level}'], 
                        color=color, 
                        ylim=(0, 100),
                        secondary_y=False,
                        panel=panel_num))
            self.plots_list += plot_list

        def _ha(panel_num):
            df = self.data_df[['HA_open', 'HA_high', 'HA_low', 'HA_close']]
            for col in df.columns:
                df[col.replace('HA_', '').capitalize()] = df[col]
            plot_list = [
                mpf.make_addplot(
                    df, 
                    type='candle', 
                    panel=panel_num,
                    ylabel="HA")]
            self.plots_list += plot_list
        
        def _chop(panel_num):
            data_column_dict = get_data_columns_dict('CHOP')
            plot_list = [
                mpf.make_addplot(
                    self.data_df[data_column_dict['CHOP']],
                    color='orange', 
                    ylim=(0, 100),
                    panel=panel_num,
                    ylabel="CHOP")]
            for level, color in ((60, 'red'), (40, 'black')):
                self.data_df[f'hline_{level}'] = level
                plot_list.append(
                    mpf.make_addplot(
                        self.data_df[f'hline_{level}'], 
                        color=color, 
                        ylim=(0, 100),
                        secondary_y=False,
                        panel=panel_num))
            self.plots_list += plot_list

        def _cksp(panel_num):
            data_column_dict = get_data_columns_dict('CKSP')
            plot_lim = (
                0.9 * min([self.data_df[data_column_dict[i]].min() for i in ('CKSPl', 'CKSPs')]), 
                1.1 * max([self.data_df[data_column_dict[i]].max() for i in ('CKSPl', 'CKSPs')]))
            plot_list = [
                mpf.make_addplot(
                    self.data_df[data_column_dict['CKSPl']],
                    color='green', 
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="CKSP"
                    ),
                mpf.make_addplot(
                    self.data_df[data_column_dict['CKSPs']],
                    color='red', 
                    ylim=plot_lim,
                    panel=panel_num,
                    secondary_y=False,
                    )]
            self.plots_list += plot_list

        def _massi(panel_num):
            data_column_dict = get_data_columns_dict('MASSI')
            plot_list = [
                mpf.make_addplot(
                    self.data_df[data_column_dict['MASSI']],
                    color='orange', 
                    panel=panel_num,
                    ylabel="MASSI")]
            for level, color in ((27, 'black'), (26, 'blue'), (24, 'red')):
                self.data_df[f'hline_{level}'] = level
                plot_list.append(
                    mpf.make_addplot(
                        self.data_df[f'hline_{level}'], 
                        color=color, 
                        secondary_y=False,
                        panel=panel_num))
            self.plots_list += plot_list

        def _pvt(panel_num):
            data_column_dict = get_data_columns_dict('SMA')
            plot_lim = (
                0.9 * min([self.data_df[i].min() for i in (data_column_dict['SMA'], 'PVT')]), 
                1.1 * max([self.data_df[i].max() for i in (data_column_dict['SMA'], 'PVT')]))
            plot_list = [
                mpf.make_addplot(
                    self.data_df[data],
                    ylim=plot_lim,
                    color=color, 
                    panel=panel_num,
                    ylabel="PVT",
                    secondary_y=False
                    ) for data, color in (('PVT', 'green'), (data_column_dict['SMA'], 'red'))]
            self.plots_list += plot_list

        graphs_dict = {
            'main_plot': {
                'PSAR': _psar,
                'ALMA': _alma,
                'ALMA_LONG': _alma_long,
                'GHLA': _ghla,
                'SUPERT': _supert,
                'HWC': _hwc},
            "separate_plots": {
                'RSI': _rsi,
                'MACD': _macd,
                'STOCH': _stoch,
                'HA': _ha,
                'CHOP': _chop,
                'CKSP': _cksp,
                'MASSI': _massi,
                'PVT': _pvt}}

        # Expected format "Stock: YadaYada - (Momentum) STOCH + (Trend) CHOP"
        strategy_components = [i.split(')')[1].strip() for i in self.title.split(' - ')[1].split('+')]
        for plot_type, strategy_plots_dict in graphs_dict.items():
            panel_number = 0 if plot_type == "main_plot" else 1
            for strategy_name, plot_func in strategy_plots_dict.items(): 
                if strategy_name not in strategy_components:
                    continue
                plot_func(panel_number)
                panel_number += (0 if plot_type == "main_plot" else 1)

    def show_single_ticker(self):
        def _orders(panel_num):
            orders_plot = [
                mpf.make_addplot(
                    self.data_df['total'],
                    color='black', 
                    ylim=(1000 * 0.9, self.data_df['total'].max() * 1.1),
                    panel=panel_num,
                    secondary_y=True)]
            self.plots_list += orders_plot

        _orders(0)
        
        mpf.plot(
            self.data_df, 
            type='candle', 
            mav=(4), 
            volume=False, 
            show_nontrading=True,
            style=mpf.make_mpf_style(
                marketcolors=mpf.make_marketcolors(
                    up='g',
                    down='r',
                    edge='in',
                    volume='in')),
            figratio=(15,18),
            figscale=2,
            title=self.title,
            xrotation=90,
            scale_padding={
                "left": 0.5,
                "right": 0.5,
                "top": 0.5},
            addplot=self.plots_list)

    def show_entire_portfolio(self):       
        ax = plt.gca()

        self.data_df.plot(
            kind='line', 
            y='Close', 
            color='red', 
            ax=ax)
        self.data_df.plot(
            kind='line', 
            y='total', 
            color='black', 
            ax=ax)
        plt.show()