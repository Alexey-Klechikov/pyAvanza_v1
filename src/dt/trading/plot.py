from datetime import datetime, timedelta

import mplfinance as mpf
import numpy as np
import pandas as pd
import yfinance as yf


def process_log_file(date_target: str) -> dict:
    with open(f"logs/auto_day_trading_{date_target}.log", "r") as f:
        lines = f.readlines()

    signals: dict = {"BUY": [], "SELL": [], "EXIT": []}
    for line in lines:
        if not ("Signal: BUY" in line or "Signal: SELL" in line or "Exit" in line):
            continue

        signal = line.split("Signal: ")[1].split("|")[0].strip().upper()

        time = (
            datetime.strptime(line.split("[")[2].split("]")[0].strip(), "%H:%M:%S")
            .time()
            .replace(second=0)
        )

        signals[signal].append(time)

    return signals


def get_ticker_history(date_target: str, date_end: str) -> pd.DataFrame:
    ticker = yf.Ticker("^OMX")
    data = ticker.history(interval="1m", start=date_target, end=date_end)[
        ["Open", "High", "Low", "Close"]
    ].reset_index()
    data.index = pd.DatetimeIndex(data["Datetime"])  # type: ignore
    data = data.drop(columns=["Datetime"])

    return data


def append_signals_to_history(data: pd.DataFrame, signals: dict) -> pd.DataFrame:
    for signal, times in signals.items():
        data[signal] = np.nan
        if signal == "EXIT":
            for time in times:
                data.loc[time, signal] = (
                    data.loc[time]["Close"] + data.loc[time]["Open"]
                ) / 2
        else:
            for time in times:
                data.loc[time, signal] = data.loc[time][
                    "Low" if signal == "BUY" else "High"
                ]

    return data


def plot(data: pd.DataFrame):
    fig, _ = mpf.plot(
        data,
        type="candle",
        style="yahoo",
        volume=False,
        ylabel="Price",
        figsize=(19.2, 10.8),
        title="OMX30",
        returnfig=True,
        scale_padding={"left": 0.2, "right": 0.8, "top": 0.5},
        addplot=[
            mpf.make_addplot(
                data["BUY"],
                type="scatter",
                markersize=50,
                marker="^",
                secondary_y=False,
                color="g",
            ),
            mpf.make_addplot(
                data["SELL"],
                type="scatter",
                markersize=50,
                marker="v",
                secondary_y=False,
                color="r",
            ),
            mpf.make_addplot(
                data["EXIT"],
                type="scatter",
                markersize=50,
                marker="x",
                secondary_y=False,
                color="b",
            ),
        ],
    )

    return fig


# MAIN
def main(date_target: str):
    date_end = datetime.strftime(
        datetime.strptime(date_target, "%Y-%m-%d") + timedelta(days=1), "%Y-%m-%d"
    )

    signals = process_log_file(date_target)
    data = get_ticker_history(date_target, date_end)
    data = append_signals_to_history(data, signals)
    fig = plot(data)

    fig.savefig(f"logs/auto_day_trading_{date_target}.png")


if __name__ == "__main__":
    date_target = "2023-03-20"

    main(date_target)
