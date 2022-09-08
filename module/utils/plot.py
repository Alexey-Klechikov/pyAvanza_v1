"""
This module is used to plot tickers, indicators, and comparison graph
"""


import logging
import warnings
import numpy as np
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt


warnings.filterwarnings("ignore", category=FutureWarning)

log = logging.getLogger("main.utils.plot")


class Plot:
    def __init__(self, data: pd.DataFrame, title: str):
        self.data = data
        self.title = title

        self.plots = list()

    def add_horizontal_lines(self, level_color: list[tuple], panel_num: int) -> None:
        horizontal_lines_plots = list()

        for level, color in level_color:
            if level is None:
                continue

            self.data[f"hline_{level}"] = level
            horizontal_lines_plots.append(
                mpf.make_addplot(
                    self.data[f"hline_{level}"],
                    color=color,
                    secondary_y=False,
                    panel=panel_num,
                )
            )

        self.plots += horizontal_lines_plots

    def add_buy_signals(self, panel_num: int, target_data_column: str = "Open") -> None:
        self.data[f"temp_{panel_num}"] = self.data.apply(
            lambda x: np.nan
            if str(x["buy_signal"]) == "nan"
            else round(x[target_data_column], 2),
            axis=1,
        )

        self.plots += [
            mpf.make_addplot(
                self.data[f"temp_{panel_num}"],
                type="scatter",
                marker="o",
                markersize=100,
                color="green",
                panel=panel_num,
                secondary_y=False,
            )
        ]

    def create_extra_panels(self) -> None:
        get_data_columns = lambda x: {
            i.split("_")[0]: i for i in sorted(self.data.columns) if i.startswith(x)
        }

        """ Plotted on top of the main plot """
        ## Trend
        def _psar(panel_num: int) -> None:
            data_columns = get_data_columns("PSAR")

            self.plots += [
                mpf.make_addplot(
                    self.data[data],
                    color=color,
                    panel=panel_num,
                    type="scatter",
                    markersize=10,
                )
                for data, color in (
                    (data_columns["PSARl"], "navy"),
                    (data_columns["PSARs"], "navy"),
                )
            ]

        ## Overlap
        def _alma(panel_num: int) -> None:
            data_columns = get_data_columns("ALMA")

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["ALMA"]],
                    color="orange",
                    panel=panel_num,
                )
            ]

        ## Overlap
        def _ghla(panel_num: int) -> None:
            data_columns = get_data_columns("HILO")

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["HILO"]],
                    color="orange",
                    panel=panel_num,
                )
            ]

        ## Overlap
        def _supert(panel_num: int) -> None:
            data_columns = get_data_columns("SUPERT")

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["SUPERT"]],
                    color="orange",
                    panel=panel_num,
                )
            ]

        ## Volatility
        def _hwc(panel_num: int) -> None:
            self.plots += [
                mpf.make_addplot(
                    self.data["HWM"],
                    color="brown",
                    panel=panel_num,
                )
            ]

        ## Volatility
        def _bbands(panel_num: int) -> None:
            data_columns = get_data_columns("BB")

            self.plots += [
                mpf.make_addplot(
                    self.data[data],
                    color=color,
                    panel=panel_num,
                )
                for data, color in (
                    (data_columns["BBL"], "brown"),
                    (data_columns["BBU"], "brown"),
                )
            ]

        """ Plotted each on a separate plot """
        ## Overlap
        def _linreg(panel_num: int) -> str:
            data_columns = get_data_columns("LR")

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["LRr"]],
                    color="orange",
                    panel=panel_num,
                    ylabel="LINREG",
                ),
                mpf.make_addplot(
                    self.data[data_columns["LRrLag"]],
                    color="red",
                    panel=panel_num,
                    secondary_y=False,
                ),
            ]

            return data_columns["LRr"]

        ## Cycles
        def _ebsw(panel_num: int) -> str:
            data_columns = get_data_columns("EBSW")
            plot_lim = (-1.1, 1.1)

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["EBSW"]],
                    color="orange",
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="EBSW",
                )
            ]

            self.add_horizontal_lines(
                level_color=[(0.5, "red"), (-0.5, "blue")], panel_num=panel_num
            )

            return data_columns["EBSW"]

        ## Momentum
        def _stc(panel_num: int) -> str:
            data_columns = get_data_columns("STC")
            plot_lim = (-10, 110)

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["STC"]],
                    color="orange",
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="STC",
                )
            ]

            self.add_horizontal_lines(
                level_color=[(25, "red"), (75, "blue")],
                panel_num=panel_num,
            )

            return data_columns["STC"]

        ## Momentum
        def _cci(panel_num: int) -> str:
            data_columns = get_data_columns("CCI")

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["CCI"]],
                    color="orange",
                    panel=panel_num,
                    ylabel="CCI",
                ),
                mpf.make_addplot(
                    self.data[data_columns["CCILag"]],
                    color="red",
                    panel=panel_num,
                    secondary_y=False,
                ),
            ]

            return data_columns["CCI"]

        ## Momentum
        def _rsi(panel_num: int) -> str:
            data_columns = get_data_columns("RSI")
            plot_lim = (0, 100)

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["RSI"]],
                    color="orange",
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="RSI",
                )
            ]

            self.add_horizontal_lines(
                level_color=[(80, "red"), (50, "black"), (20, "blue")],
                panel_num=panel_num,
            )
            return data_columns["RSI"]

        ## Momentum
        def _rvgi(panel_num: int) -> str:
            data_columns = get_data_columns("RVGI")
            plot_lim = (
                0.9
                * min([self.data[data_columns[i]].min() for i in ("RVGI", "RVGIs")]),
                1.1
                * max([self.data[data_columns[i]].max() for i in ("RVGI", "RVGIs")]),
            )

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["RVGI"]],
                    ylim=plot_lim,
                    color="orange",
                    panel=panel_num,
                    ylabel="RVGI",
                ),
                mpf.make_addplot(
                    self.data[data_columns["RVGIs"]],
                    ylim=plot_lim,
                    color="black",
                    panel=panel_num,
                    secondary_y=False,
                ),
            ]

            return data_columns["RVGI"]

        ## Momentum
        def _macd(panel_num: int) -> str:
            data_columns = get_data_columns("MACD")
            plot_lim = (
                0.9
                * min(
                    [
                        self.data[data_columns[i]].min()
                        for i in ("MACD", "MACDh", "MACDs")
                    ]
                ),
                1.1
                * max(
                    [
                        self.data[data_columns[i]].max()
                        for i in ("MACD", "MACDh", "MACDs")
                    ]
                ),
            )

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["MACD"]],
                    ylim=plot_lim,
                    color="orange",
                    panel=panel_num,
                    ylabel="MACD",
                ),
                mpf.make_addplot(
                    self.data[data_columns["MACDs"]],
                    ylim=plot_lim,
                    color="black",
                    panel=panel_num,
                    secondary_y=False,
                ),
                mpf.make_addplot(
                    self.data[data_columns["MACDh"]],
                    type="bar",
                    width=0.7,
                    color="dimgray",
                    alpha=1,
                    ylim=plot_lim,
                    secondary_y=False,
                    panel=panel_num,
                ),
            ]

            return data_columns["MACD"]

        ## Momentum
        def _stoch(panel_num: int) -> str:
            data_columns = get_data_columns("STOCH")
            plot_lim = (
                0.9
                * min([self.data[data_columns[i]].min() for i in ("STOCHk", "STOCHd")]),
                1.1
                * max([self.data[data_columns[i]].max() for i in ("STOCHk", "STOCHd")]),
            )

            self.plots += [
                mpf.make_addplot(
                    self.data[data],
                    ylim=plot_lim,
                    color=color,
                    panel=panel_num,
                    ylabel="Stoch",
                )
                for data, color in (
                    (data_columns["STOCHk"], "orange"),
                    (data_columns["STOCHd"], "black"),
                )
            ]

            self.add_horizontal_lines(
                level_color=[(80, "red"), (20, "blue")], panel_num=panel_num
            )

            return data_columns["STOCHk"]

        ## Momentum
        def _uo(panel_num: int) -> str:
            data_columns = get_data_columns("UO")
            plot_lim = (0, 100)

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["UO"]],
                    color="orange",
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="UO",
                )
            ]

            self.add_horizontal_lines(
                level_color=[(70, "red"), (30, "blue")], panel_num=panel_num
            )

            return data_columns["UO"]

        ## Candle
        def _ha(panel_num: int) -> str:
            df = self.data[["HA_open", "HA_high", "HA_low", "HA_close"]]

            for col in df.columns:
                df[col.replace("HA_", "").capitalize()] = df[col]

            self.plots += [
                mpf.make_addplot(df, type="candle", panel=panel_num, ylabel="HA")
            ]

            return "HA_open"

        ## Trend
        def _chop(panel_num: int) -> str:
            data_columns = get_data_columns("CHOP")

            plot_lim = (0, 100)

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["CHOP"]],
                    color="orange",
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="CHOP",
                )
            ]

            self.add_horizontal_lines(
                level_color=[(60, "red"), (40, "blue")], panel_num=panel_num
            )

            return data_columns["CHOP"]

        ## Trend
        def _cksp(panel_num: int) -> str:
            data_columns = get_data_columns("CKSP")

            plot_lim = (
                0.9
                * min([self.data[data_columns[i]].min() for i in ("CKSPl", "CKSPs")]),
                1.1
                * max([self.data[data_columns[i]].max() for i in ("CKSPl", "CKSPs")]),
            )

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["CKSPl"]],
                    color="orange",
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="CKSP",
                ),
                mpf.make_addplot(
                    self.data[data_columns["CKSPs"]],
                    color="black",
                    ylim=plot_lim,
                    panel=panel_num,
                    secondary_y=False,
                ),
            ]

            return data_columns["CKSPl"]

        ## Trend
        def _adx(panel_num: int) -> str:
            data_columns = get_data_columns("DM")

            plot_lim = (
                0.9 * min([self.data[data_columns[i]].min() for i in ("DMP", "DMN")]),
                1.1 * max([self.data[data_columns[i]].max() for i in ("DMP", "DMN")]),
            )

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["DMP"]],
                    color="orange",
                    ylim=plot_lim,
                    panel=panel_num,
                    ylabel="ADX",
                ),
                mpf.make_addplot(
                    self.data[data_columns["DMN"]],
                    color="black",
                    ylim=plot_lim,
                    panel=panel_num,
                    secondary_y=False,
                ),
            ]

            return data_columns["DMP"]

        ## Volatility
        def _massi(panel_num: int) -> str:
            data_columns = get_data_columns("MASSI")

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["MASSI"]],
                    color="orange",
                    panel=panel_num,
                    ylabel="MASSI",
                )
            ]

            self.add_horizontal_lines(
                level_color=[(27, "red"), (26, "black"), (24, "blue")],
                panel_num=panel_num,
            )

            return data_columns["MASSI"]

        ## Volume
        def _cmf(panel_num: int) -> str:
            data_columns = get_data_columns("CMF")

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["CMF"]],
                    color="orange",
                    panel=panel_num,
                    ylabel="CMF",
                )
            ]

            self.add_horizontal_lines(
                level_color=[(0, "black"), (None, None)], panel_num=panel_num
            )

            return data_columns["CMF"]

        ## Volume
        def _pvt(panel_num: int) -> str:
            data_columns = get_data_columns("SMA")
            plot_lim = (
                0.9 * min([self.data[i].min() for i in (data_columns["SMA"], "PVT")]),
                1.1 * max([self.data[i].max() for i in (data_columns["SMA"], "PVT")]),
            )

            self.plots += [
                mpf.make_addplot(
                    self.data[data],
                    ylim=plot_lim,
                    color=color,
                    panel=panel_num,
                    ylabel="PVT",
                    secondary_y=False,
                )
                for data, color in (("PVT", "green"), (data_columns["SMA"], "red"))
            ]

            return "PVT"

        ## Volume
        def _kvo(panel_num: int) -> str:
            data_columns = get_data_columns("KVO")

            plot_lim = (
                0.9 * min([self.data[data_columns[i]].min() for i in ("KVO", "KVOs")]),
                1.1 * max([self.data[data_columns[i]].max() for i in ("KVO", "KVOs")]),
            )

            self.plots += [
                mpf.make_addplot(
                    self.data[data_columns["KVO"]],
                    ylim=plot_lim,
                    color="orange",
                    panel=panel_num,
                    ylabel="KVO",
                ),
                mpf.make_addplot(
                    self.data[data_columns["KVOs"]],
                    ylim=plot_lim,
                    color="black",
                    panel=panel_num,
                    secondary_y=False,
                ),
            ]

            return data_columns["KVO"]

        graphs = {
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
                "STC": _stc,
                "CCI": _cci,
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
        ]

        add_panel_num = lambda plot_type: 0 if plot_type == "main_plot" else 1

        for plot_type, strategy_plots in graphs.items():
            panel_num = add_panel_num(plot_type)

            for strategy_name, plotting_functions in strategy_plots.items():
                if strategy_name not in strategy_components:
                    continue

                target_data_column = plotting_functions(panel_num)

                if target_data_column is not None:
                    self.add_buy_signals(panel_num, target_data_column)

                panel_num += add_panel_num(plot_type)

    def add_orders_to_main_plot(self) -> None:
        if "total" in self.data.columns:
            self.plots.append(
                mpf.make_addplot(
                    self.data["total"],
                    color="black",
                    ylim=(1000 * 0.9, self.data["total"].max() * 1.1),
                    panel=0,
                    secondary_y=True,
                )
            )

        if "sell_signal" in self.data.columns:
            self.plots.append(
                mpf.make_addplot(
                    self.data["sell_signal"],
                    scatter=True,
                    markersize=100,
                    marker="o",
                    color="red",
                    secondary_y=False,
                )
            )

        if "buy_signal" in self.data.columns:
            self.plots.append(
                mpf.make_addplot(
                    self.data["buy_signal"],
                    scatter=True,
                    markersize=100,
                    marker="o",
                    color="green",
                    secondary_y=False,
                )
            )

    def show_single_ticker(self) -> None:
        mpf.plot(
            self.data,
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
            addplot=self.plots,
        )

    def show_entire_portfolio(self) -> None:
        ax = plt.gca()

        self.data.plot(kind="line", y="Close", color="red", ax=ax)
        self.data.plot(kind="line", y="total", color="black", ax=ax)

        plt.show()
