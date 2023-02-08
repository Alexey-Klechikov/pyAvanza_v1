import logging
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
from avanza import InstrumentType, OrderType

from module.dt import DayTime, Strategy, TradingTime
from module.dt.calibration.order import CalibrationOrder
from module.dt.common_types import Instrument
from module.utils import Cache, Context, History, Settings, TeleLog, displace_message

log = logging.getLogger("main.dt.calibration.main")

DISPLACEMENTS = (9, 60, 3, 4, 4, 15, 15, 0)


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

    @staticmethod
    def get_signal(strategy_logic: dict, row: pd.Series) -> Optional[OrderType]:
        for signal in [OrderType.BUY, OrderType.SELL]:
            if all([i(row) for i in strategy_logic[signal]]):
                return signal

        return None

    def get_exit_instrument(
        self, row: pd.Series, history: pd.DataFrame
    ) -> Optional[Instrument]:
        for instrument, calibration_order in self.orders.items():
            if (
                not calibration_order.on_balance
                or calibration_order.price_buy is None
                or calibration_order.price_sell is None
                or calibration_order.time_buy is None
            ):
                continue

            history_slice = history.loc[calibration_order.time_buy : row.name]["Close"]  # type: ignore

            if instrument == Instrument.BULL:
                if row["RSI"] >= 60:
                    continue

                if (
                    calibration_order.price_sell / calibration_order.price_buy - 1
                ) * 20 <= (self.settings["trading"]["exit"] - 1):
                    continue

                if (1 - row["Close"] / history_slice.max()) * 20 <= (
                    1 - self.settings["trading"]["pullback"]
                ):
                    continue

                return instrument

            if instrument == Instrument.BEAR:
                if row["RSI"] <= 40:
                    continue

                if (
                    1 - calibration_order.price_sell / calibration_order.price_buy
                ) * 20 <= (self.settings["trading"]["exit"] - 1):
                    continue

                if (row["Close"] / history_slice.min() - 1) * 20 <= (
                    1 - self.settings["trading"]["pullback"]
                ):
                    continue

                return instrument

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
            "numbers_bull": (
                ""
                if numbers["BULL_trades"] == 0
                else f"{round(numbers['BULL_trades_good'] / numbers['BULL_trades'] * 100)}% - {numbers['BULL_trades_good']} / {numbers['BULL_trades']}"
            ),
            "numbers_bear": (
                ""
                if numbers["BEAR_trades"] == 0
                else f"{round(numbers['BEAR_trades_good'] / numbers['BEAR_trades'] * 100)}% - {numbers['BEAR_trades_good']} / {numbers['BEAR_trades']}"
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
    def __init__(self, settings: dict, print_orders_history: bool):
        self.settings = settings
        self.print_orders_history = print_orders_history

        self.ava = Context(settings["user"], settings["accounts"], skip_lists=True)

        self.strategies: List[dict] = []

    def _walk_through_strategies(
        self,
        history: History,
        strategy: Strategy,
        consider_efficiency: bool,
    ) -> None:
        self.strategies = []

        daily_volumes = history.data.groupby([history.data.index.date])["Volume"].sum().values.tolist()  # type: ignore

        log.info(
            f"Dates range: {history.data.index[0].strftime('%Y.%m.%d')} - {history.data.index[-1].strftime('%Y.%m.%d')} "  # type: ignore
            + f"({history.data.shape[0]} rows) "
            + f"({len([i for i in daily_volumes if i > 0])} / {len(daily_volumes)} days with Volume)"
        )

        log.info(
            displace_message(
                DISPLACEMENTS,
                (
                    "Counter",
                    "Strategy",
                    "Pts",
                    "Prft",
                    "Effi",
                    "Numbers BULL | Numbers BEAR | Signal (at)",
                ),
            )
        )

        for i, (strategy_name, strategy_logic) in enumerate(
            strategy.strategies.items()
        ):
            helper = Helper(strategy_name, self.settings)
            exit_instrument = None
            last_signal = {"signal": None, "time": ""}
            signal = None

            for index, row in history.data.iterrows():
                time_index: datetime = index  # type: ignore

                if time_index.hour < 10:
                    continue

                if (time_index.hour == 17 and time_index.minute >= 15) or (
                    history.data.iloc[-1].name == time_index
                ):
                    if any(
                        [
                            (
                                last_signal["signal"] == OrderType.BUY
                                and exit_instrument == Instrument.BULL
                            ),
                            (
                                last_signal["signal"] == OrderType.SELL
                                and exit_instrument == Instrument.BEAR
                            ),
                            not any([o.on_balance for o in helper.orders.values()]),
                        ]
                    ):
                        last_signal["signal"] = None

                    for instrument in helper.orders:
                        helper.sell_order(time_index, row, instrument)

                    continue

                if signal is None and exit_instrument is not None:
                    helper.sell_order(
                        time_index,
                        row,
                        exit_instrument,
                    )

                elif signal is not None:
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

                signal = Helper.get_signal(strategy_logic, row)
                if signal:
                    last_signal = {
                        "signal": signal.value,
                        "time": time_index.strftime("%H:%M"),
                    }

                exit_instrument = helper.get_exit_instrument(row, history.data)

            strategy_summary = helper.get_orders_history_summary()

            if consider_efficiency and (
                strategy_summary["profit"] <= 0 or strategy_summary["points"] < -20
            ):
                continue

            self.strategies.append(strategy_summary)

            log.info(
                displace_message(
                    DISPLACEMENTS,
                    tuple(
                        [f"[{i+1}/{len(strategy.strategies)}]"]
                        + list(strategy_summary.values())
                        + [
                            ""
                            if not last_signal["signal"]
                            else f"{last_signal['signal']} ({last_signal['time']})"
                        ]
                    ),
                )
            )

            if self.print_orders_history:
                helper.print_orders_history()

    def _update_trading_settings(self) -> None:
        settings = Settings().load("DT")

        instruments_info: dict = {}
        spreads = []

        for instrument_type in Instrument:
            instruments_info[instrument_type] = []

            for instrument_id in settings["instruments"]["TRADING_POOL"][
                instrument_type
            ]:
                instrument_info = self.ava.get_instrument_info(
                    InstrumentType.WARRANT, str(instrument_id)
                )

                if (
                    instrument_type == Instrument.BULL
                    and instrument_info["key_indicators"]["direction"] != "Lång"
                ) or (
                    instrument_type == Instrument.BEAR
                    and instrument_info["key_indicators"]["direction"] != "Kort"
                ):
                    log.warning(f"Instrument {instrument_id} is not {instrument_type}")

                    continue

                if instrument_info[OrderType.BUY] > 280:
                    log.warning(f"Instrument {instrument_id} is too expensive")

                    continue

                if not isinstance(instrument_info["spread"], float) or not isinstance(
                    instrument_info["key_indicators"].get("leverage"), float
                ):
                    log.warning(
                        f"Instrument {instrument_id} is not valid: {instrument_info['spread']} / {instrument_info['key_indicators'].get('leverage')}"
                    )

                    continue

                instruments_info[instrument_type].append(
                    (
                        instrument_id,
                        {
                            "spread": instrument_info["spread"],
                            "leverage": instrument_info["key_indicators"]["leverage"],
                            "score": round(
                                instrument_info["key_indicators"]["leverage"]
                                / instrument_info["spread"],
                                2,
                            ),
                        },
                    )
                )

                if instrument_info["position"] or instrument_info["orders"]:
                    log.debug(
                        f"Instrument {instrument_type} -> {instrument_id} is in use"
                    )

                    instruments_info[instrument_type] = [
                        instruments_info[instrument_type].pop()
                    ]

                    break

            top_instrument = sorted(
                instruments_info[instrument_type], key=lambda x: x[1]["score"]
            ).pop()

            if (
                settings["instruments"]["TRADING"].get(instrument_type)
                != top_instrument[0]
            ):
                log.info(
                    f"Change instrument {instrument_type} -> {top_instrument[0]} ({top_instrument[1]})"
                )

                settings["instruments"]["TRADING"][instrument_type] = top_instrument[0]

            spreads.append(top_instrument[1]["spread"])

        settings["trading"]["spread_limit"] = min(round(max(spreads) * 3, 2), 0.8)

        log.debug(f"Spread limit: {settings['trading']['spread_limit']}")

        Settings().dump(settings, "DT")

    def update(self) -> None:
        log.info("Updating strategies")

        extra_data = self.ava.get_today_history(
            self.settings["instruments"]["MONITORING"]["AVA"]
        )

        history = History(
            self.settings["instruments"]["MONITORING"]["YAHOO"],
            "30d",
            "1m",
            cache=Cache.APPEND,
            extra_data=extra_data,
        )

        strategy = Strategy(history.data)

        self._walk_through_strategies(history, strategy, True)

        self.strategies = [
            s for s in sorted(self.strategies, key=lambda s: s["points"], reverse=True)
        ]

        Strategy.dump(
            "DT",
            {
                "30d": self.strategies,
            },
        )

    def test(self) -> list:
        log.info("Testing strategies")

        extra_data = self.ava.get_today_history(
            self.settings["instruments"]["MONITORING"]["AVA"]
        )

        history = History(
            self.settings["instruments"]["MONITORING"]["YAHOO"],
            "15d",
            "1m",
            cache=Cache.APPEND,
            extra_data=extra_data,
        )

        strategies = Strategy.load("DT")
        strategies_dict = {
            i["strategy"]: i["points"] for i in strategies.get("30d", [])
        }

        strategy = Strategy(history.data, strategies=list(strategies_dict.keys()))

        self._walk_through_strategies(history, strategy, True)

        strategies["15d"] = [
            s for s in sorted(self.strategies, key=lambda s: s["points"], reverse=True)
        ]

        most_profitable_strategies = [
            (i["strategy"], i["profit"])
            for i in strategies["15d"]
            if i["points"]
            in sorted(
                list(set([s["points"] for s in strategies["15d"]])), reverse=True
            )[: min(3, len(strategies["15d"]))]
        ]

        strategies["use"] = [
            i[0]
            for i in sorted(
                most_profitable_strategies, key=lambda s: s[1], reverse=True
            )
        ]

        Strategy.dump("DT", strategies)

        return strategies["use"]

    def adjust(self) -> None:
        log.info("Adjusting strategies")

        extra_data = self.ava.get_today_history(
            self.settings["instruments"]["MONITORING"]["AVA"]
        )

        history = History(
            self.settings["instruments"]["MONITORING"]["YAHOO"],
            "1d",
            "1m",
            cache=Cache.SKIP,
            extra_data=extra_data,
        )

        history.data = history.data[datetime.now() - timedelta(hours=3) :]  # type: ignore

        self._update_trading_settings()

        strategies = Strategy.load("DT")

        strategy = Strategy(history.data, strategies=strategies["use"])

        self._walk_through_strategies(history, strategy, False)

        strategies["use"] = [
            s["strategy"]
            for s in sorted(self.strategies, key=lambda s: s["profit"], reverse=True)
        ]

        Strategy.dump("DT", strategies)


def run(
    update: bool = True, adjust: bool = True, print_orders_history: bool = False
) -> None:
    trading_time = TradingTime()
    settings = Settings().load("DT")
    calibration = Calibration(settings, print_orders_history)

    # day run
    while True:
        if not adjust:
            break

        try:
            trading_time.update_day_time()

            if trading_time.day_time == DayTime.MORNING:
                pass

            elif trading_time.day_time == DayTime.DAY:
                calibration.adjust()

            elif trading_time.day_time == DayTime.EVENING:
                break

            time.sleep(60 * 5)

        except Exception as e:
            log.error(f">>> {e}: {traceback.format_exc()}")

    # full calibration
    try:
        if update:
            calibration.update()

        strategy_use = calibration.test()

        TeleLog(
            message="DT calibration:\n"
            + "\n".join(["\n> " + "\n> ".join(s.split(" + ")) for s in strategy_use])
        )

    except Exception as e:
        log.error(f">>> {e}: {traceback.format_exc()}")

        TeleLog(crash_report=f"DT_Calibration: script has crashed: {e}")

    return
