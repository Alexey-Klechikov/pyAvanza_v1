import logging
import traceback
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import pandas_ta as ta
from avanza import OrderType as Signal

from src.lt.strategy import Strategy
from src.utils import Cache, Context, History, Settings

log = logging.getLogger("main.dt.testing")


class Backtest:
    def __init__(self):
        self.settings = Settings().load("DT")
        self.strategies = Strategy.load("DT")
        self.ava = Context(self.settings["user"], self.settings["accounts"])

        self.history_dates = []

        self.run_analysis()

    def get_strategy_signal_on_ticker(
        self,
        ticker_yahoo: str,
        ticker_ava: str,
        cache: Cache,
        target_date: Optional[date],
    ) -> Signal:
        data = History(ticker_yahoo, "18mo", "1d", cache=cache).data

        if target_date:
            data = data[data.index <= target_date]
        else:
            self.history_dates = list(reversed(data.index.to_list()[:-1]))

        if str(data.iloc[-1]["Close"]) == "nan":
            self.ava.update_todays_ochl(data, ticker_ava)

        strategy_obj = Strategy(
            data,
            strategies=self.strategies.get(ticker_yahoo, []),
        )

        return strategy_obj.summary.signal

    def get_ma_signals_on_ticker(self, ticker_yahoo: str, target_date: date) -> dict:
        data = History(ticker_yahoo, "18mo", "1d", cache=Cache.REUSE).data
        data = data[data.index <= target_date]

        signals = {}

        for ma in ["SMA", "EMA"]:
            for length in [3, 4, 5, 6, 7]:
                if ma == "SMA":
                    data.ta.sma(length=length, append=True)
                else:
                    data.ta.ema(length=length, append=True)

                signals[f"{ma}_{length}"] = (
                    Signal.BUY
                    if data.iloc[-1][f"{ma}_{length}"] > data.iloc[-1]["Close"]
                    else Signal.SELL
                )

        return signals

    def _run_predictions(self, omx_history: pd.DataFrame) -> pd.DataFrame:
        results = pd.DataFrame()

        for i in range(len(self.history_dates)):
            if i < 2:
                continue

            test_info = {"prediction_date": self.history_dates[i], "omx_signal": 0}

            for ticker_yahoo, ticker in self.settings["omx_weights"].items():
                """
                signal_strategy = self.get_strategy_signal_on_ticker(
                    ticker_yahoo,
                    ticker["orderbook_id"],
                    cache=Cache.REUSE,
                    target_date=test_info["prediction_date"],
                )

                test_info["omx_signal"] += (
                    (1 if signal_strategy == Signal.BUY else -1)
                    * ticker["weight_calc"]
                    / 100
                )
                """

                signal_ma = self.get_ma_signals_on_ticker(
                    ticker_yahoo, test_info["prediction_date"]
                )

                for ma, signal in signal_ma.items():
                    test_info.setdefault(f"{ma}_signal", 0)
                    test_info[f"{ma}_signal"] += (
                        (1 if signal == Signal.BUY else -1)
                        * ticker["weight_calc"]
                        / 100
                    )

            omx_history_day = omx_history.loc[
                self.history_dates[i - 1]
                + timedelta(hours=9, minutes=1) : self.history_dates[i - 1]
                + timedelta(hours=17, minutes=15)
            ]
            omx_history_day_before = omx_history.loc[
                self.history_dates[i]
                + timedelta(hours=17, minutes=15) : self.history_dates[i]
                + timedelta(hours=17, minutes=16)
            ]

            if len(omx_history_day) < 400 or len(omx_history_day_before) == 0:
                continue

            for k, v in test_info.items():
                if k.endswith("_signal"):
                    test_info[k] = round(v, 2)

            test_info.update(
                {
                    "eval_buy_amount": omx_history_day_before.iloc[0]["Close"],
                    "eval_open_amount": omx_history_day.iloc[0]["Open"],
                    "eval_close_amount": omx_history_day.iloc[-1]["Close"],
                    "eval_high_amount": omx_history_day["High"].max(),
                    "eval_low_amount": omx_history_day["Low"].min(),
                    "eval_price_column": (
                        omx_history_day["High"] + omx_history_day["Low"]
                    )
                    / 2,
                    "prediction_date": test_info["prediction_date"].date(),
                }
            )

            results = results.append(test_info, ignore_index=True)  # type: ignore

            log.error(
                " | ".join(
                    [
                        f"{k}: {v}"
                        for k, v in test_info.items()
                        if k
                        in [
                            "eval_buy_amount",
                            "eval_open_amount",
                            "eval_close_amount",
                            "eval_high_amount",
                            "eval_low_amount",
                            "prediction_date",
                        ]
                    ]
                )
            )

            if len(results) > 40:
                break

        return results

    def _run_analytics(self, results: pd.DataFrame) -> None:
        counters = {}

        for signal_column in [c for c in results.columns if c.endswith("_signal")]:
            for target_change_amount in range(5, 15):
                print(
                    "Change_amount: ",
                    target_change_amount,
                    "data:\n",
                    results[
                        [
                            signal_column,
                            "eval_buy_amount",
                            "eval_open_amount",
                            "eval_close_amount",
                            "eval_high_amount",
                            "eval_low_amount",
                        ]
                    ],
                )

                counter: float = 0

                for _, row in results.iterrows():
                    multiplier = 1 if row[signal_column] > 0 else -1
                    amount_diff_close = (
                        row["eval_close_amount"] - row["eval_buy_amount"]
                    )

                    highs = row["eval_price_column"][
                        (
                            (row["eval_price_column"] - row["eval_buy_amount"])
                            * multiplier
                            > 0
                        )
                        & (
                            abs((row["eval_price_column"] - row["eval_buy_amount"]))
                            > target_change_amount
                        )
                    ]
                    lows = row["eval_price_column"][
                        (
                            (row["eval_buy_amount"] - row["eval_price_column"])
                            * multiplier
                            > 0
                        )
                        & (
                            abs((row["eval_price_column"] - row["eval_buy_amount"]))
                            > target_change_amount * 0.8
                        )
                    ]

                    if len(highs) > 0 and len(lows) > 0:
                        if highs.index[0] < lows.index[0]:
                            actual_change_amount = abs(
                                highs[0] - row["eval_buy_amount"]
                            )

                            print(
                                "BULL - " if row[signal_column] > 0 else "BEAR - ",
                                "Case 1: high is before low + both are over limit",
                                counter,
                                " -> ",
                                round(counter + actual_change_amount, 2),
                                "buy_amount: ",
                                row["eval_buy_amount"],
                                "first_high: ",
                                highs.index[0],
                                highs[0],
                                "first_low: ",
                                lows.index[0],
                                lows[0],
                            )
                            counter += actual_change_amount

                        else:
                            actual_change_amount = abs(lows[0] - row["eval_buy_amount"])

                            print(
                                "BULL - " if row[signal_column] > 0 else "BEAR - ",
                                "Case 2: low is before high + both are over limit",
                                counter,
                                " -> ",
                                round(counter - actual_change_amount, 2),
                                "buy_amount: ",
                                row["eval_buy_amount"],
                                "first_high: ",
                                highs.index[0],
                                highs[0],
                                "first_low: ",
                                lows.index[0],
                                lows[0],
                            )
                            counter -= actual_change_amount

                    elif len(highs) > 0:
                        actual_change_amount = abs(highs[0] - row["eval_buy_amount"])

                        print(
                            "BULL - " if row[signal_column] > 0 else "BEAR - ",
                            "Case 3: high is over limit",
                            counter,
                            " -> ",
                            round(counter + actual_change_amount, 2),
                            "buy_amount: ",
                            row["eval_buy_amount"],
                            "first_high: ",
                            highs.index[0],
                            highs[0],
                        )
                        counter += actual_change_amount

                    elif len(lows) > 0:
                        actual_change_amount = abs(lows[0] - row["eval_buy_amount"])

                        print(
                            "BULL - " if row[signal_column] > 0 else "BEAR - ",
                            "Case 4: low is over limit",
                            counter,
                            " -> ",
                            round(counter - actual_change_amount, 2),
                            "buy_amount: ",
                            row["eval_buy_amount"],
                            "first_low: ",
                            lows.index[0],
                            lows[0],
                        )
                        counter -= actual_change_amount

                    else:
                        print(
                            "BULL - " if row[signal_column] > 0 else "BEAR - ",
                            "Case 5: close by the end of the day",
                            counter,
                            " -> ",
                            round(counter + amount_diff_close, 2),
                        )
                        counter += amount_diff_close

                print(
                    f"Change amount: {target_change_amount} | Signal: {signal_column} | Counter: {counter} \n------------------"
                )

                counters[signal_column] = {
                    "counter": counter,
                    "change_amount": target_change_amount,
                }

        print(
            "Best counter: ",
            [
                f"{k}: {v['change_amount']} ({v['counter']})"
                for k, v in counters.items()
                if v["counter"] == max([i["counter"] for i in counters.values()])
            ][0],
        )

    def run_analysis(self) -> None:
        """
        Test 2023.06.27 | Change amount: 10 | Signal: SMA_5_signal | Counter: 121 | Results_len: 40
        Test 2023.06.27 | Change amount: 9 (sell 80%) | Signal: SMA_5_signal | Counter: 118 | Results_len: 40
        """

        log.info("Running analysis")

        for ticker_yahoo, ticker in self.settings["omx_weights"].items():
            signal_strategy = self.get_strategy_signal_on_ticker(
                ticker_yahoo,
                ticker["orderbook_id"],
                cache=Cache.APPEND,
                target_date=None,
            )

        log.info("Running backtest")

        omx_history = History(
            self.settings["instruments"]["MONITORING"]["YAHOO"], "180d", "1m"
        ).data

        results = self._run_predictions(omx_history)
        self._run_analytics(results)


def run() -> None:
    try:
        Backtest()

    except Exception as e:
        log.error(f">>> {e}: {traceback.format_exc()}")
