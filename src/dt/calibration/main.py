import logging
import time
import traceback
from datetime import datetime

from src.dt import DayTime, Strategy, TradingTime
from src.dt.calibration.walker import Helper, Walker
from src.dt.common_types import Instrument
from src.utils import Cache, Settings, TeleLog

log = logging.getLogger("main.dt.calibration.main")

PERIOD_UPDATE = "20d"
PERIOD_TEST = "10d"


class Calibration:
    def __init__(self):
        self.walker = Walker(Settings().load("DT"))

    def update(self, direction) -> None:
        log.info(f"Updating strategies ({direction})")

        profitable_strategies = sorted(
            self.walker.traverse_strategies(
                period=PERIOD_UPDATE,
                cache=Cache.APPEND,
                target_day_direction=direction,
            ),
            key=lambda s: (s["points"], s["profit"]),
            reverse=True,
        )

        indicators_counter = Helper.count_indicators_usage(profitable_strategies)

        Strategy.dump(
            "DT",
            {
                **Strategy.load("DT"),
                **{f"{direction}_{PERIOD_UPDATE}": profitable_strategies},
                **{f"{direction}_indicators_stats": indicators_counter},
            },
        )

    def test(self, direction: str):
        log.info(f"Testing strategies ({direction})")

        stored_strategies = Strategy.load("DT")

        profitable_strategies = sorted(
            self.walker.traverse_strategies(
                period=PERIOD_TEST,
                cache=Cache.APPEND,
                loaded_strategies=[
                    i["strategy"]
                    for i in stored_strategies.get(f"{direction}_{PERIOD_UPDATE}", [])
                ],
                target_day_direction=direction,
            ),
            key=lambda s: s["points"] * 100 + s["profit"],
            reverse=True,
        )

        Strategy.dump(
            "DT",
            {
                **stored_strategies,
                **{f"{direction}_{PERIOD_TEST}": profitable_strategies},
                **{"act": []},
            },
        )

    def pick(self, direction) -> None:
        log.info(f"Picking strategies for direction: {direction}")

        self.walker.update_trading_settings()

        stored_strategies = Strategy.load("DT")

        strategies_to_test = [
            i["strategy"]
            for i in stored_strategies.get(f"{direction}_{PERIOD_TEST}", [])
            if int(i["efficiency"][:-1]) >= 65
        ]

        profitable_strategies = sorted(
            self.walker.traverse_strategies(
                period="1d",
                cache=Cache.SKIP,
                filter_strategies=False,
                loaded_strategies=strategies_to_test,
                history_cutoff={"hours": 2, "minutes": 30},
            ),
            key=lambda s: s["profit"],
            reverse=True,
        )

        max_profit = max([s["profit"] for s in profitable_strategies])
        profitable_strategies = [
            s["strategy"]
            for s in profitable_strategies
            if s["profit"] >= max_profit * 0.8
        ]

        Strategy.dump(
            "DT",
            {
                **stored_strategies,
                **{"act": profitable_strategies},
            },
        )


def run(update: bool = True, pick: bool = True, show_orders: bool = False) -> None:
    trading_time = TradingTime()
    calibration = Calibration()
    Helper.show_orders = show_orders

    last_direction = direction = Instrument.BULL

    # day run
    while True:
        if not pick:
            break

        try:
            trading_time.update_day_time()

            if trading_time.day_time == DayTime.MORNING:
                pass

            elif trading_time.day_time == DayTime.DAY:
                direction = calibration.walker.get_direction()

                if last_direction != direction or datetime.now().minute % 6 == 0:
                    calibration.pick(direction)

                last_direction = direction
                time.sleep(60)

            elif trading_time.day_time == DayTime.EVENING:
                break

        except Exception as e:
            log.error(f">>> {e}: {traceback.format_exc()}")

    # full calibration
    try:
        for direction in Instrument:
            if update:
                calibration.update(direction)

            calibration.test(direction)

        TeleLog(message="DT Calibration: Done")

    except Exception as e:
        log.error(f">>> {e}: {traceback.format_exc()}")

        TeleLog(crash_report=f"DT Calibration: script has crashed: {e}")

    return
