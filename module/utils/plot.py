"""
This module is used to plot tickers, indicators, and comparison graph
"""


import logging
import warnings
import numpy as np
import mplfinance as mpf
import matplotlib.pyplot as plt


warnings.filterwarnings("ignore", category=FutureWarning)

log = logging.getLogger("main.plot")


class Plot:
    def __init__(self, data_df, title):
        self.data_df = data_df
        self.title = title

        self.plots_list = list()

    def add_horisontal_lines(self, level_color_list, panel_num):
        horisontal_lines_plots_list = list()
        for level, color in level_color_list:
            if level is None:
                continue
            self.data_df[f"hline_{level}"] = level
            horisontal_lines_plots_list.append(
                mpf.make_addplot(
                    self.data_df[f"hline_{level}"],
                    color=color,
                    secondary_y=False,
                    panel=panel_num,
                )
            )

        self.plots_list += horisontal_lines_plots_list

    def add_buy_signals(self, panel_num, target_data_column="Open"):
        self.data_df[f"temp_{panel_num}"] = self.data_df.apply(
            lambda x: np.nan
            if str(x["buy_signal"]) == "nan"
            else round(x[target_data_column], 2),
            axis=1,
        )

        self.plots_list += [
            mpf.make_addplot(
                self.data_df[f"temp_{panel_num}"],
                type="scatter",
                marker="o",
                markersize=100,
                color="green",
                panel=panel_num,
                secondary_y=False,
            )
        ]

    def create_extra_panels(self):
        get_data_columns_dict = lambda x: {
            i.split("_")[0]: i for i in sorted(self.data_df.columns) if i.startswith(x)
        }

        """ Plotted on top of the main plot """
        ## Trend
        def _psar(panel_num):
            data_column_dict = get_data_columns_dict("PSAR")
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data],
                    color=color,
                    panel=panel_num,
                    type="scatter",
                    markersize=10,
                )
                for data, color in (
                    (data_column_dict["PSARl"], "navy"),
                    (data_column_dict["PSARs"], "navy"),
                )
            ]

        ## Overlap
        def _alma(panel_num):
            data_column_dict = get_data_columns_dict("ALMA")
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["ALMA"]],
                    color="orange",
                    panel=panel_num,
                )
            ]

        ## Overlap
        def _ghla(panel_num):
            data_column_dict = get_data_columns_dict("HILO")
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["HILO"]],
                    color="orange",
                    panel=panel_num,
                )
            ]

        ## Overlap
        def _supert(panel_num):
            data_column_dict = get_data_columns_dict("SUPERT")
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["SUPERT"]],
                    color="orange",
                    panel=panel_num,
                )
            ]

        ## Volatility
        def _hwc(panel_num):
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df["HWM"],
                    color="brown",
                    panel=panel_num,
                )
            ]

        ## Volatility
        def _bbands(panel_num):
            data_column_dict = get_data_columns_dict("BB")
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data],
                    color=color,
                    panel=panel_num,
                )
                for data, color in (
                    (data_column_dict["BBL"], "brown"),
                    (data_column_dict["BBU"], "brown"),
                )
            ]

        """ Plotted each on a separate plot """
        ## Overlap
        def _linreg(panel_num):
            data_column_dict = get_data_columns_dict("LR")
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["LRr"]],
                    color="orange",
                    panel=panel_num,
                    ylabel="LINREG",
                ),
                mpf.make_addplot(
                    self.data_df[data_column_dict["LRrLag"]],
                    color="red",
                    panel=panel_num,
                    secondary_y=False,
                ),
            ]
            return data_column_dict["LRr"]

        ## Cycles
        def _ebsw(panel_num):
            data_column_dict = get_data_columns_dict("EBSW")
            plot_lim = (-1.1, 1.1)
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["EBSW"]],
                    color="orange",
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="EBSW",
                )
            ]
            self.add_horisontal_lines(
                level_color_list=((0.5, "red"), (-0.5, "blue")), panel_num=panel_num
            )
            return data_column_dict["EBSW"]

        ## Momentum
        def _rsi(panel_num):
            data_column_dict = get_data_columns_dict("RSI")
            plot_lim = (0, 100)
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["RSI"]],
                    color="orange",
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="RSI",
                )
            ]
            self.add_horisontal_lines(
                level_color_list=((80, "red"), (50, "black"), (20, "blue")),
                panel_num=panel_num,
            )
            return data_column_dict["RSI"]

        ## Momentum
        def _rvgi(panel_num):
            data_column_dict = get_data_columns_dict("RVGI")
            plot_lim = (
                0.9
                * min(
                    [self.data_df[data_column_dict[i]].min() for i in ("RVGI", "RVGIs")]
                ),
                1.1
                * max(
                    [self.data_df[data_column_dict[i]].max() for i in ("RVGI", "RVGIs")]
                ),
            )
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["RVGI"]],
                    ylim=plot_lim,
                    color="orange",
                    panel=panel_num,
                    ylabel="RVGI",
                ),
                mpf.make_addplot(
                    self.data_df[data_column_dict["RVGIs"]],
                    ylim=plot_lim,
                    color="black",
                    panel=panel_num,
                    secondary_y=False,
                ),
            ]
            return data_column_dict["RVGI"]

        ## Momentum
        def _macd(panel_num):
            data_column_dict = get_data_columns_dict("MACD")
            plot_lim = (
                0.9
                * min(
                    [
                        self.data_df[data_column_dict[i]].min()
                        for i in ("MACD", "MACDh", "MACDs")
                    ]
                ),
                1.1
                * max(
                    [
                        self.data_df[data_column_dict[i]].max()
                        for i in ("MACD", "MACDh", "MACDs")
                    ]
                ),
            )
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["MACD"]],
                    ylim=plot_lim,
                    color="orange",
                    panel=panel_num,
                    ylabel="MACD",
                ),
                mpf.make_addplot(
                    self.data_df[data_column_dict["MACDs"]],
                    ylim=plot_lim,
                    color="black",
                    panel=panel_num,
                    secondary_y=False,
                ),
                mpf.make_addplot(
                    self.data_df[data_column_dict["MACDh"]],
                    type="bar",
                    width=0.7,
                    color="dimgray",
                    alpha=1,
                    ylim=plot_lim,
                    secondary_y=False,
                    panel=panel_num,
                ),
            ]
            return data_column_dict["MACD"]

        ## Momentum
        def _stoch(panel_num):
            data_column_dict = get_data_columns_dict("STOCH")
            plot_lim = (
                0.9
                * min(
                    [
                        self.data_df[data_column_dict[i]].min()
                        for i in ("STOCHk", "STOCHd")
                    ]
                ),
                1.1
                * max(
                    [
                        self.data_df[data_column_dict[i]].max()
                        for i in ("STOCHk", "STOCHd")
                    ]
                ),
            )
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data],
                    ylim=plot_lim,
                    color=color,
                    panel=panel_num,
                    ylabel="Stoch",
                )
                for data, color in (
                    (data_column_dict["STOCHk"], "orange"),
                    (data_column_dict["STOCHd"], "black"),
                )
            ]
            self.add_horisontal_lines(
                level_color_list=((80, "red"), (20, "blue")), panel_num=panel_num
            )
            return data_column_dict["STOCHk"]

        ## Momentum
        def _uo(panel_num):
            data_column_dict = get_data_columns_dict("UO")
            plot_lim = (0, 100)
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["UO"]],
                    color="orange",
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="UO",
                )
            ]
            self.add_horisontal_lines(
                level_color_list=((70, "red"), (30, "blue")), panel_num=panel_num
            )
            return data_column_dict["UO"]

        ## Candle
        def _ha(panel_num):
            df = self.data_df[["HA_open", "HA_high", "HA_low", "HA_close"]]
            for col in df.columns:
                df[col.replace("HA_", "").capitalize()] = df[col]
            self.plots_list += [
                mpf.make_addplot(df, type="candle", panel=panel_num, ylabel="HA")
            ]
            return "HA_open"

        ## Trend
        def _chop(panel_num):
            data_column_dict = get_data_columns_dict("CHOP")
            plot_lim = (0, 100)
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["CHOP"]],
                    color="orange",
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="CHOP",
                )
            ]
            self.add_horisontal_lines(
                level_color_list=((60, "red"), (40, "blue")), panel_num=panel_num
            )
            return data_column_dict["CHOP"]

        ## Trend
        def _cksp(panel_num):
            data_column_dict = get_data_columns_dict("CKSP")
            plot_lim = (
                0.9
                * min(
                    [
                        self.data_df[data_column_dict[i]].min()
                        for i in ("CKSPl", "CKSPs")
                    ]
                ),
                1.1
                * max(
                    [
                        self.data_df[data_column_dict[i]].max()
                        for i in ("CKSPl", "CKSPs")
                    ]
                ),
            )
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["CKSPl"]],
                    color="orange",
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="CKSP",
                ),
                mpf.make_addplot(
                    self.data_df[data_column_dict["CKSPs"]],
                    color="black",
                    ylim=plot_lim,
                    panel=panel_num,
                    secondary_y=False,
                ),
            ]
            return data_column_dict["CKSPl"]

        ## Trend
        def _adx(panel_num):
            data_column_dict = get_data_columns_dict("DM")
            plot_lim = (
                0.9
                * min(
                    [self.data_df[data_column_dict[i]].min() for i in ("DMP", "DMN")]
                ),
                1.1
                * max(
                    [self.data_df[data_column_dict[i]].max() for i in ("DMP", "DMN")]
                ),
            )
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["DMP"]],
                    color="orange",
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="ADX",
                ),
                mpf.make_addplot(
                    self.data_df[data_column_dict["DMN"]],
                    color="black",
                    ylim=plot_lim,
                    panel=panel_num,
                    secondary_y=False,
                ),
            ]
            return data_column_dict["DMP"]

        ## Volatility
        def _massi(panel_num):
            data_column_dict = get_data_columns_dict("MASSI")
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["MASSI"]],
                    color="orange",
                    panel=panel_num,
                    ylabel="MASSI",
                )
            ]
            self.add_horisontal_lines(
                level_color_list=((27, "red"), (26, "black"), (24, "blue")),
                panel_num=panel_num,
            )
            return data_column_dict["MASSI"]

        ## Volume
        def _cmf(panel_num):
            data_column_dict = get_data_columns_dict("CMF")
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["CMF"]],
                    color="orange",
                    panel=panel_num,
                    ylabel="CMF",
                )
            ]
            self.add_horisontal_lines(
                level_color_list=((0, "black"), (None, None)), panel_num=panel_num
            )
            return data_column_dict["CMF"]

        ## Volume
        def _pvt(panel_num):
            data_column_dict = get_data_columns_dict("SMA")
            plot_lim = (
                0.9
                * min(
                    [self.data_df[i].min() for i in (data_column_dict["SMA"], "PVT")]
                ),
                1.1
                * max(
                    [self.data_df[i].max() for i in (data_column_dict["SMA"], "PVT")]
                ),
            )
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data],
                    ylim=plot_lim,
                    color=color,
                    panel=panel_num,
                    ylabel="PVT",
                    secondary_y=False,
                )
                for data, color in (("PVT", "green"), (data_column_dict["SMA"], "red"))
            ]
            return "PVT"

        ## Volume
        def _kvo(panel_num):
            data_column_dict = get_data_columns_dict("KVO")
            plot_lim = (
                0.9
                * min(
                    [self.data_df[data_column_dict[i]].min() for i in ("KVO", "KVOs")]
                ),
                1.1
                * max(
                    [self.data_df[data_column_dict[i]].max() for i in ("KVO", "KVOs")]
                ),
            )
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df[data_column_dict["KVO"]],
                    ylim=plot_lim,
                    color="orange",
                    panel=panel_num,
                    ylabel="KVO",
                ),
                mpf.make_addplot(
                    self.data_df[data_column_dict["KVOs"]],
                    ylim=plot_lim,
                    color="black",
                    panel=panel_num,
                    secondary_y=False,
                ),
            ]
            return data_column_dict["KVO"]

        graphs_dict = {
            "main_plot": {
                "PSAR": _psar,
                "ALMA": _alma,
                "GHLA": _ghla,
                "SUPERT": _supert,
                "HWC": _hwc,
                "BBANDS": _bbands,
            },
            "separate_plots": {
                "LINREG": _linreg,
                "EBSW": _ebsw,
                "RSI": _rsi,
                "RVGI": _rvgi,
                "MACD": _macd,
                "STOCH": _stoch,
                "HA": _ha,
                "CHOP": _chop,
                "CKSP": _cksp,
                "MASSI": _massi,
                "PVT": _pvt,
                "CMF": _cmf,
                "ADX": _adx,
                "KVO": _kvo,
                "UO": _uo,
            },
        }

        # Expected format "Stock: YadaYada - (Momentum) STOCH + (Trend) CHOP"
        strategy_components = [
            i.split(")")[1].strip() for i in self.title.split(" - ")[1].split("+")
        ] + ["UO"]
        add_panel_num = lambda plot_type: 0 if plot_type == "main_plot" else 1
        for plot_type, strategy_plots_dict in graphs_dict.items():
            panel_num = add_panel_num(plot_type)
            for strategy_name, plotting_functions in strategy_plots_dict.items():
                if strategy_name not in strategy_components:
                    continue
                target_data_column = plotting_functions(panel_num)
                if target_data_column is not None:
                    self.add_buy_signals(panel_num, target_data_column)
                panel_num += add_panel_num(plot_type)

    def show_single_ticker(self):
        def _orders(panel_num):
            self.plots_list += [
                mpf.make_addplot(
                    self.data_df["total"],
                    color="black",
                    ylim=(1000 * 0.9, self.data_df["total"].max() * 1.1),
                    panel=panel_num,
                    secondary_y=True,
                ),
                mpf.make_addplot(
                    self.data_df["buy_signal"],
                    scatter=True,
                    markersize=100,
                    marker="o",
                    color="green",
                    secondary_y=True,
                ),
                mpf.make_addplot(
                    self.data_df["sell_signal"],
                    scatter=True,
                    markersize=20,
                    marker="o",
                    color="red",
                    secondary_y=True,
                ),
            ]

        _orders(0)

        mpf.plot(
            self.data_df,
            type="candle",
            mav=(4),
            volume=False,
            show_nontrading=True,
            style=mpf.make_mpf_style(
                marketcolors=mpf.make_marketcolors(
                    up="g", down="r", edge="in", volume="in"
                )
            ),
            figratio=(15, 18),
            figscale=2,
            title=self.title,
            xrotation=90,
            scale_padding={"left": 0.5, "right": 0.5, "top": 0.5},
            addplot=self.plots_list,
        )

    def show_entire_portfolio(self):
        ax = plt.gca()

        self.data_df.plot(kind="line", y="Close", color="red", ax=ax)
        self.data_df.plot(kind="line", y="total", color="black", ax=ax)
        plt.show()
