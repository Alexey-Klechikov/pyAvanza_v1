
import mplfinance as mpf
import matplotlib.pyplot as plt

class Plot:
    def __init__(self, data_df, title):
        self.data_df = data_df
        self.title = title

        self.plots_list = list()

    def create_extra_panels(self):
        get_data_columns_dict = lambda x: {i.split('_')[0]:i for i in sorted(self.data_df.columns) if i.startswith(x)}

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

        def _macd(panel_num):
            data_column_dict = get_data_columns_dict('MACD')
            plot_lim = (
                min(self.data_df[data_column_dict['MACD']].min(), self.data_df[data_column_dict['MACDh']].min(), self.data_df[data_column_dict['MACDs']].min()), 
                max(self.data_df[data_column_dict['MACD']].max(), self.data_df[data_column_dict['MACDh']].max(), self.data_df[data_column_dict['MACDs']].max()))
            plot_lim = (plot_lim[0]*0.9, plot_lim[1]*1.1)
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
                min(self.data_df[data_column_dict['STOCHk']].min(), self.data_df[data_column_dict['STOCHd']].min()), 
                max(self.data_df[data_column_dict['STOCHk']].max(), self.data_df[data_column_dict['STOCHd']].max())) 
            plot_lim = (plot_lim[0]*0.9, plot_lim[1]*1.1)
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
        
        def _cksp(panel_num):
            data_column_dict = get_data_columns_dict('CKSP')
            plot_lim = (
                min(self.data_df[data_column_dict['CKSPl']].min(), self.data_df[data_column_dict['CKSPs']].min()), 
                max(self.data_df[data_column_dict['CKSPl']].max(), self.data_df[data_column_dict['CKSPs']].max())) 
            plot_lim = (plot_lim[0]*0.9, plot_lim[1]*1.1)
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

        graphs_dict = {
            'PSAR': _psar,
            'ALMA': _alma,
            'ALMA_LONG': _alma_long,
            'RSI': _rsi,
            'MACD': _macd,
            'STOCH': _stoch,
            'HA': _ha,
            'GHLA': _ghla,
            'SUPERT': _supert,
            'CHOP': _chop,
            'CKSP': _cksp,
            'MASSI': _massi}

        strategy_components = [i.strip() for i in self.title.split(' - ')[1].split('+')]
        for i in ('PSAR', 'ALMA', 'ALMA_LONG', 'GHLA', 'SUPERT'):
            if i in strategy_components:
               graphs_dict[i](0) 

        panel_number = 2
        for i in ('RSI', 'MACD', 'STOCH', 'HA', 'CHOP', 'CKSP', 'MASSI'):
            if i in strategy_components or i == 'MASSI':
               graphs_dict[i](panel_number) 
               panel_number += 1

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
            volume=True, 
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