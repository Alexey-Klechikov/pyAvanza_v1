import logging
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import pytz
from avanza import OrderType

from module.day_trading import Instrument, Strategy
from module.utils import Context, History, Settings, TeleLog

log = logging.getLogger("main.day_trading_calibration")


@dataclass
class CalibrationOrder:
    instrument: Instrument

    on_balance: bool = False
    price_buy: Optional[float] = None
    price_sell: Optional[float] = None
    price_stop_loss: Optional[float] = None
    price_take_profit: Optional[float] = None
    time_buy: Optional[datetime] = None
    time_sell: Optional[datetime] = None
    verdict: Optional[str] = None

    def buy(self, row: pd.Series, index: datetime) -> None:
        self.time_buy = index

        self.on_balance = True

        self.price_buy = ((row["Open"] + row["Close"]) / 2) * (
            1.00015 if self.instrument == Instrument.BULL else 0.99985
        )

    def sell(self, row: pd.Series, index: datetime):
        self.time_sell = index

        self.price_sell = (row["Close"] + row["Open"]) / 2

        if (
            self.price_sell <= self.price_buy and self.instrument == Instrument.BULL
        ) or (self.price_sell >= self.price_buy and self.instrument == Instrument.BEAR):
            self.verdict = "bad"

        else:
            self.verdict = "good"

    def set_limits(self, row: pd.Series, settings_trading: dict) -> None:
        atr_correction = row["ATR"] / 20
        direction = 1 if self.instrument == Instrument.BULL else -1

        reference_price = ((row["Open"] + row["Close"]) / 2) * (
            1.00015 if self.instrument == Instrument.BULL else 0.99985
        )

        self.price_stop_loss = reference_price * (
            1 - (1 - settings_trading["stop_loss"]) * atr_correction * direction
        )
        self.price_take_profit = reference_price * (
            1 + (settings_trading["take_profit"] - 1) * atr_correction * direction
        )

    def check_limits(self, row: pd.Series) -> bool:
        self.price_sell = (row["Close"] + row["Open"]) / 2

        if self.price_stop_loss is None or self.price_take_profit is None:
            return False

        if (
            self.instrument == Instrument.BULL
            and (
                self.price_sell <= self.price_stop_loss
                or self.price_sell >= self.price_take_profit
            )
        ) or (
            self.instrument == Instrument.BEAR
            and (
                self.price_sell <= self.price_take_profit
                or self.price_sell >= self.price_stop_loss
            )
        ):
            return True

        return False

    def pop_result(self) -> dict:
        profit: Optional[float] = None

        if self.price_sell is not None and self.price_buy is not None:
            profit = round(
                20
                * (self.price_sell - self.price_buy)
                * (1 if self.instrument == Instrument.BULL else -1)
                + 1000
            )

        points_bin = 0.0
        if profit is not None:
            points = 1 if (profit - 1000) > 0 else -1
            multiplier = min([1 + abs(profit - 1000) // 100, 4])
            points_bin = points * multiplier

        result = {
            "instrument": self.instrument,
            "price_buy": self.price_buy,
            "price_sell": self.price_sell,
            "time_buy": self.time_buy,
            "time_sell": self.time_sell,
            "verdict": self.verdict,
            "profit": profit,
            "points": points_bin,
        }

        self.on_balance = False
        self.price_buy = None
        self.price_sell = None
        self.time_buy = None
        self.time_sell = None
        self.verdict = None

        return result


class Helper:
    def __init__(self, strategy_name: str, settings: dict) -> None:
        self.strategy_name = strategy_name
        self.settings = settings

        self.orders: Dict[Instrument, CalibrationOrder] = {
            i: CalibrationOrder(i) for i in Instrument
        }

        self.orders_history: List[dict] = []

    def buy_order(
        self,
        signal: Optional[OrderType],
        index: datetime,
        row: pd.Series,
        instrument: Instrument,
    ) -> None:
        if signal is None:
            return

        if not self.orders[instrument].on_balance:
            self.orders[instrument].buy(row, index)

        self.orders[instrument].set_limits(row, self.settings["trading"])

    def sell_order(
        self,
        index: datetime,
        row: pd.Series,
        instrument: Instrument,
    ) -> None:
        if not self.orders[instrument].on_balance:
            return

        self.orders[instrument].sell(row, index)

        self.orders_history.append(self.orders[instrument].pop_result())

    def check_orders_for_limits(self, index: datetime, row: pd.Series) -> None:
        for instrument, calibration_order in self.orders.items():
            if calibration_order.check_limits(row):
                self.sell_order(index, row, instrument)

    def get_signal(self, strategy_logic: dict, row: pd.Series) -> Optional[OrderType]:

        for signal in [OrderType.BUY, OrderType.SELL]:
            if all([i(row) for i in strategy_logic[signal]]):
                return signal

        return None

    def get_orders_history_summary(self) -> dict:
        if len(self.orders_history) == 0:
            return {"strategy": self.strategy_name, "points": 0, "profit": 0}

        df = pd.DataFrame(self.orders_history)
        df.profit = df.profit.astype(float)

        numbers = {
            "trades": len(df),
            "good": len(df[df.verdict == "good"]),
            "bad": len(df[df.verdict == "bad"]),
            "BULL_trades": len(df[df.instrument == Instrument.BULL]),
            "BULL_trades_good": len(
                df[(df.instrument == Instrument.BULL) & (df.verdict == "good")]
            ),
            "BEAR_trades": len(df[df.instrument == Instrument.BEAR]),
            "BEAR_trades_good": len(
                df[(df.instrument == Instrument.BEAR) & (df.verdict == "good")]
            ),
        }

        return {
            "strategy": self.strategy_name,
            "points": int(df.points.sum()),
            "profit": int(df.profit.sum() - len(df) * 1000),
            "efficiency": f"{round(100 * len(df[df.verdict == 'good']) / len(df))}%",
            "numbers": (
                ""
                if numbers["BULL_trades"] == 0
                else f"[BULL: {round(numbers['BULL_trades_good'] / numbers['BULL_trades'] * 100)}% - {numbers['BULL_trades_good']} / {numbers['BULL_trades']}] "
            )
            + (
                ""
                if numbers["BEAR_trades"] == 0
                else f"[BEAR: {round(numbers['BEAR_trades_good'] / numbers['BEAR_trades'] * 100)}% - {numbers['BEAR_trades_good']} / {numbers['BEAR_trades']}]"
            ),
        }

    def print_orders_history(self) -> None:
        if len(self.orders_history) == 0:
            return

        df = pd.DataFrame(self.orders_history)
        df.profit = df.profit.astype(int)
        df.time_buy = df.time_buy.dt.strftime("%m-%d %H:%M")
        df.time_sell = df.time_sell.dt.strftime("%m-%d %H:%M")
        df.price_sell = df.price_sell.round(2)
        df.price_buy = df.price_buy.round(2)
        df.instrument = df.instrument.apply(lambda x: x.value)

        log.info(f"\n{df}")


class Calibration:
    def __init__(self, settings: dict, user: str):
        self.settings = settings

        self.ava = Context(user, settings["accounts"], skip_lists=True)

        self.strategies: List[dict] = []

    def _walk_through_strategies(
        self,
        history: History,
        strategy: Strategy,
        print_orders_history: bool,
    ) -> None:
        self.strategies = []

        daily_volumes = history.data.groupby([history.data.index.date]).sum()["Volume"].values.tolist()  # type: ignore

        log.info(
            f"Dates range: {history.data.index[0].strftime('%Y.%m.%d')} - {history.data.index[-1].strftime('%Y.%m.%d')} "  # type: ignore
            + f"({history.data.shape[0]} rows) "
            + f"({len([i for i in daily_volumes if i > 0])} / {len(daily_volumes)} days with Volume)"
        )

        for i, (strategy_name, strategy_logic) in enumerate(
            strategy.strategies.items()
        ):
            helper = Helper(strategy_name, self.settings)
            signal = None

            for index, row in history.data.iterrows():
                time_index: datetime = index  # type: ignore

                if time_index.hour < 10:
                    continue

                if (time_index.hour == 17 and time_index.minute >= 15) or (
                    history.data.iloc[-1].name == time_index
                ):
                    for instrument in helper.orders:
                        helper.sell_order(time_index, row, instrument)

                    continue

                if signal is not None:
                    helper.sell_order(
                        time_index,
                        row,
                        Instrument.from_signal(signal)[OrderType.SELL],
                    )
                    helper.buy_order(
                        signal,
                        time_index,
                        row,
                        Instrument.from_signal(signal)[OrderType.BUY],
                    )

                helper.check_orders_for_limits(time_index, row)

                signal = helper.get_signal(strategy_logic, row)

            strategy_summary = helper.get_orders_history_summary()

            self.strategies.append(strategy_summary)

            if strategy_summary["profit"] <= 0:
                log.debug(
                    f"[{i+1}/{len(strategy.strategies)}] > "
                    + " | ".join([f"{k}: {v}" for k, v in strategy_summary.items()])
                )

                continue

            log.info(
                f"[{i+1}/{len(strategy.strategies)}] > "
                + " | ".join([f"{k}: {v}" for k, v in strategy_summary.items()])
            )

            if print_orders_history:
                helper.print_orders_history()

    def update(self, print_orders_history: bool) -> None:
        log.info("Updating strategies")

        extra_data = self.ava.get_today_history(
            self.settings["instruments"]["MONITORING"]["AVA"]
        )

        history = History(
            self.settings["instruments"]["MONITORING"]["YAHOO"],
            "60d",
            "1m",
            cache="append",
            extra_data=extra_data,
        )

        history.data = history.data[
            history.data.index
            <= (datetime.now() - timedelta(days=15)).astimezone(
                pytz.timezone("Europe/Stockholm")
            )
        ]

        strategy = Strategy(history.data)

        self._walk_through_strategies(history, strategy, print_orders_history)

        self.strategies = [
            s
            for s in sorted(self.strategies, key=lambda s: s["points"], reverse=True)
            if s["profit"] > 0 and s["points"] > 0
        ]

        Strategy.dump(
            "DT",
            {
                "50-15d": self.strategies,
            },
        )

    def test(self, print_orders_history: bool) -> list:
        log.info("Testing strategies")

        extra_data = self.ava.get_today_history(
            self.settings["instruments"]["MONITORING"]["AVA"]
        )

        history = History(
            self.settings["instruments"]["MONITORING"]["YAHOO"],
            "14d",
            "1m",
            cache="append",
            extra_data=extra_data,
        )

        strategies = Strategy.load("DT")
        strategies_dict = {
            i["strategy"]: i["points"] for i in strategies.get("50-15d", [])
        }

        strategy = Strategy(history.data, strategies=list(strategies_dict.keys()))

        self._walk_through_strategies(history, strategy, print_orders_history)

        strategies["14d"] = [
            s for s in sorted(self.strategies, key=lambda s: s["points"], reverse=True)
        ]

        for s in strategies["14d"]:
            strategies_dict[s["strategy"]] += 2 * s["points"]

        strategies_ordered = sorted(
            [(k, v) for k, v in strategies_dict.items()],
            key=lambda x: x[1],
            reverse=True,
        )
        strategies["use"] = [strategies_ordered[i][0] for i in range(3)]

        Strategy.dump("DT", strategies)

        return strategies["use"]


def run(update: bool = True, print_orders_history: bool = False) -> None:
    settings = Settings().load()

    for user, settings_per_user in settings.items():
        for setting_per_setup in settings_per_user.values():
            if not setting_per_setup.get("run_day_trading", False):
                continue

            try:
                calibration = Calibration(setting_per_setup, user)

                if update:
                    calibration.update(print_orders_history)

                strategy_use = calibration.test(print_orders_history)

                TeleLog(
                    message="DT calibration:\n"
                    + "\n".join(
                        ["\n> " + "\n> ".join(s.split(" + ")) for s in strategy_use]
                    )
                )

            except Exception as e:
                log.error(f">>> {e}: {traceback.format_exc()}")

                TeleLog(crash_report=f"DT_Calibration: script has crashed: {e}")

            return