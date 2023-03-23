import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
from avanza import InstrumentType, OrderType

from src.dt import Strategy
from src.dt.calibration.order import CalibrationOrder
from src.dt.common_types import Instrument
from src.utils import Cache, Context, History, Settings, displace_message

log = logging.getLogger("main.dt.calibration.walker")

DISPLACEMENTS = (9, 60, 3, 4, 4, 15, 15, 0)


class Helper:
    conditions: dict = {}
    show_orders: bool = False

    def __init__(self, strategy_name: str) -> None:
        self.strategy_name = strategy_name

        self.orders: Dict[Instrument, CalibrationOrder] = {
            i: CalibrationOrder(i) for i in Instrument
        }

        self.orders_history: List[dict] = []

    def buy_order(
        self,
        row: pd.Series,
        instrument: Instrument,
    ) -> None:
        if not self.orders[instrument].on_balance:
            self.orders[instrument].buy(row)

        self.orders[instrument].set_limits(row, Walker.settings["trading"])

    def sell_order(
        self,
        row: pd.Series,
        instrument: Instrument,
    ) -> None:
        if not self.orders[instrument].on_balance:
            return

        self.orders[instrument].sell(row)

        self.orders_history.append(self.orders[instrument].pop_result())

    def check_orders_for_limits(self, row: pd.Series) -> None:
        for instrument, calibration_order in self.orders.items():
            if calibration_order.check_limits(row):
                self.sell_order(row, instrument)

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
                or not calibration_order.price_buy
                or not calibration_order.price_sell
                or not calibration_order.time_buy
            ):
                continue

            history_slice = history.loc[calibration_order.time_buy : row.name]  # type: ignore
            price_change = calibration_order.price_sell / calibration_order.price_buy
            percent_exit = Walker.settings["trading"]["exit"] - 1
            percent_pullback = 1 - Walker.settings["trading"]["pullback"]

            if any(
                [
                    all(
                        [
                            instrument == Instrument.BULL,
                            row["RSI"] < 58,
                            (price_change - 1) * 20 > percent_exit,
                            ((1 - row["Low"] / history_slice["High"].max()) * 20)
                            > percent_pullback,
                        ]
                    ),
                    all(
                        [
                            instrument == Instrument.BEAR,
                            row["RSI"] > 42,
                            (1 - price_change) * 20 > percent_exit,
                            ((row["High"] / history_slice["Low"].min() - 1) * 20)
                            > percent_pullback,
                        ]
                    ),
                ]
            ):
                return instrument

        return None

    def get_orders_history_summary(self) -> dict:
        if len(self.orders_history) == 0:
            return {
                "strategy": self.strategy_name,
                "points": 0,
                "profit": 0,
                "efficiency": "0%",
            }

        df = pd.DataFrame(self.orders_history)
        df.profit = df.profit.astype(float)

        numbers = {}
        for instrument in Instrument:
            number_trades = len(df[df.instrument == instrument])
            number_good_trades = len(
                df[(df.instrument == instrument) & (df.verdict == "good")]
            )
            numbers[instrument] = (
                ""
                if number_trades == 0
                else f"{round(number_good_trades / number_trades * 100)}% - {number_good_trades} / {number_trades}"
            )

        return {
            "strategy": self.strategy_name,
            "points": int(df.points.sum()),
            "profit": int(df.profit.sum() - len(df) * 1000),
            "efficiency": f"{round(100 * len(df[df.verdict == 'good']) / len(df))}%",
            "numbers_bull": numbers[Instrument.BULL],
            "numbers_bear": numbers[Instrument.BEAR],
        }

    def print_orders_history(self) -> None:
        if len(self.orders_history) == 0 or not Helper.show_orders:
            return

        df = pd.DataFrame(self.orders_history)
        df.profit = df.profit.astype(int)
        df.time_buy = df.time_buy.dt.strftime("%m-%d %H:%M")
        df.time_sell = df.time_sell.dt.strftime("%m-%d %H:%M")
        df.price_sell = df.price_sell.round(2)
        df.price_buy = df.price_buy.round(2)
        df.instrument = df.instrument.apply(lambda x: x.value)

        log.info(f"\n{df}")

    @staticmethod
    def count_indicators_usage(strategies: List[dict]) -> list:
        used_indicators: str = " + ".join([i["strategy"] for i in strategies])

        conditions_counter = {}
        for category, indicators in Helper.conditions.items():
            conditions_counter.update(
                {
                    f"({category}) {i}": used_indicators.count(f"({category}) {i}")
                    for i in indicators
                }
            )

        return [
            f"{i[0]} - {i[1]}"
            for i in sorted(
                conditions_counter.items(), key=lambda x: x[1], reverse=True
            )
        ]


class Walker:
    settings: dict = {}

    def __init__(self, settings: dict) -> None:
        Walker.settings = settings
        self.ava = Context(settings["user"], settings["accounts"], process_lists=False)

    def traverse_strategies(
        self,
        period: str,
        interval: str,
        cache: Cache,
        filter_strategies: bool,
        loaded_strategies: List[dict],
        target_day_direction: Optional[str] = None,
    ) -> List[dict]:
        strategy = Strategy(
            History(
                Walker.settings["instruments"]["MONITORING"]["YAHOO"],
                period,
                interval,
                cache,
                target_day_direction=target_day_direction,
                extra_data=self.ava.get_today_history(
                    Walker.settings["instruments"]["MONITORING"]["AVA"]
                ),
            ).data,
            strategies=loaded_strategies,
        )

        strategies = []

        Helper.conditions = strategy.components.conditions

        daily_volumes = strategy.data.groupby([strategy.data.index.date])["Volume"].sum().values.tolist()  # type: ignore

        stored_strategies = Strategy.load("DT").get(f"{target_day_direction}_{period}")
        if target_day_direction and stored_strategies and datetime.now().date() - strategy.data.index[-1].date() != timedelta(days=0):  # type: ignore
            log.info(
                "Skipping strategy calibration for today, because there is no fresh data for this target direction"
            )

            return stored_strategies

        log.info(
            " ".join(
                [
                    f"Dates range: {strategy.data.index[0].strftime('%Y.%m.%d')} - {strategy.data.index[-1].strftime('%Y.%m.%d')}",  # type: ignore
                    f"(Rows: {strategy.data.shape[0]})",
                    f"(Days with volume: {len([i for i in daily_volumes if i > 0])} / {len(daily_volumes)})",
                ]
            )
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
                    " | ".join(
                        ["Numbers BULL", "Numbers BEAR", "Signal (at)"][
                            : 2 if filter_strategies else 3
                        ]
                    ),
                ),
            )
        )

        for i, (strategy_name, strategy_logic) in enumerate(
            strategy.strategies.items()
        ):
            helper = Helper(strategy_name)
            last_signal = {"signal": None, "time": ""}

            last_signal = Walker.traverse_day(
                strategy, helper, strategy_logic, last_signal
            )

            strategy_summary = helper.get_orders_history_summary()

            if filter_strategies and any(
                [
                    strategy_summary["points"] < -10,
                    strategy_summary["profit"] <= 100,
                    int(strategy_summary["efficiency"][:-1]) < 50,
                ]
            ):
                continue

            strategies.append(strategy_summary)

            if strategy_summary["profit"] > 0:
                log.info(
                    displace_message(
                        DISPLACEMENTS,
                        list(
                            [f"[{i+1}/{len(strategy.strategies)}]"]
                            + list(strategy_summary.values())
                            + [
                                ""
                                if not last_signal["signal"]
                                else f"{last_signal['signal']} ({last_signal['time']})"
                            ]
                        )[: 7 if filter_strategies else 8],
                    )
                )

                helper.print_orders_history()

        return strategies

    @staticmethod
    def traverse_day(
        strategy: Strategy,
        helper: Helper,
        strategy_logic: dict,
        last_signal: dict,
    ) -> dict:
        exit_instrument = None
        signal = None

        for index, row in strategy.data.iterrows():
            time_index: datetime = index  # type: ignore

            if time_index.hour < 9 and time_index.minute < 30:
                continue

            if (time_index.hour == 17 and time_index.minute >= 15) or (
                strategy.data.iloc[-1].name == time_index
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
                    helper.sell_order(row, instrument)

                continue

            if not signal and exit_instrument:
                helper.sell_order(
                    row,
                    exit_instrument,
                )

            elif signal:
                helper.sell_order(
                    row,
                    Instrument.from_signal(signal)[OrderType.SELL],
                )
                helper.buy_order(
                    row,
                    Instrument.from_signal(signal)[OrderType.BUY],
                )

            helper.check_orders_for_limits(row)

            signal = Helper.get_signal(strategy_logic, row)
            if signal:
                last_signal = {
                    "signal": signal.value,
                    "time": time_index.strftime("%H:%M"),
                }

            exit_instrument = helper.get_exit_instrument(row, strategy.data)

        return last_signal

    def traverse_instruments(
        self, market_direction: Instrument, instruments_pool: dict
    ) -> list:
        instruments = []

        for instrument_id, instrument_type in instruments_pool[market_direction]:
            instrument_info = self.ava.get_instrument_info(
                InstrumentType[instrument_type],
                str(instrument_id),
            )

            log_prefix = (
                f"Instrument {market_direction} ({instrument_type} - {instrument_id})"
            )

            if instrument_info["position"] or instrument_info["order"]:
                log.debug(f"{log_prefix} is in use")

                return [
                    {
                        "identifier": [instrument_type, instrument_id],
                        "numbers": {
                            "score": 0,
                        },
                    }
                ]

            elif instrument_info["is_deprecated"]:
                log.debug(f"{log_prefix} is deprecated")

            elif market_direction != {
                "Lång": Instrument.BULL,
                "Kort": Instrument.BEAR,
            }.get(instrument_info["key_indicators"]["direction"]):
                log.debug(
                    f"{log_prefix} is in wrong category: {instrument_info['key_indicators']['direction']}"
                )

            elif (
                not instrument_info[OrderType.BUY]
                or instrument_info[OrderType.BUY] > 280
            ):
                log.debug(
                    f"{log_prefix} has bad price: {instrument_info[OrderType.BUY]}"
                )

            elif not instrument_info["spread"] or not (
                0.1 < instrument_info["spread"] < 0.9
            ):
                log.debug(f"{log_prefix} has bad spread: {instrument_info['spread']}")

            elif (
                not instrument_info["key_indicators"].get("leverage")
                or instrument_info["key_indicators"]["leverage"] < 18
            ):
                log.debug(
                    f"{log_prefix} has bad leverage: {instrument_info['key_indicators'].get('leverage')}"
                )

            else:
                instruments.append(
                    {
                        "identifier": [instrument_type, instrument_id],
                        "numbers": {
                            "spread": instrument_info["spread"],
                            "leverage": instrument_info["key_indicators"]["leverage"],
                            "score": round(
                                instrument_info["key_indicators"]["leverage"]
                                / instrument_info["spread"]
                            )
                            // 3,
                        },
                    }
                )

        return instruments

    def update_trading_settings(self) -> None:
        settings = Settings().load("DT")

        instruments_pool = self.ava.retrieve_dt_instruments_from_watch_lists()

        instruments_info: dict = {}

        for market_direction in Instrument:
            instruments_info[market_direction] = []

            instruments_info[market_direction] = self.traverse_instruments(
                market_direction, instruments_pool
            )

            top_instruments = sorted(
                filter(
                    lambda x: x["numbers"]["score"]
                    == max(
                        [
                            i["numbers"]["score"]
                            for i in instruments_info[market_direction]
                        ]
                    ),
                    instruments_info[market_direction],
                ),
                key=lambda x: x["identifier"],
            )

            if top_instruments and (
                settings["instruments"]["TRADING"].get(market_direction)
                not in [i["identifier"] for i in top_instruments]
            ):
                log.info(
                    f'Change instrument {market_direction} -> {top_instruments[0]["identifier"]} ({top_instruments[0]["numbers"]})'
                )

                settings["instruments"]["TRADING"][market_direction] = top_instruments[
                    0
                ]["identifier"]

        Settings().dump(settings, "DT")
