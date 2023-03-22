import logging
import time
import traceback

from src.dt import DayTime, Strategy, TradingTime
from src.dt.calibration.walker import Helper, Walker
from src.utils import Cache, Settings, TeleLog

log = logging.getLogger("main.dt.calibration.main")

PERIOD_UPDATE = "20d"
PERIOD_TEST = "10d"


class Calibration:
    def __init__(self):
        self.walker = Walker(Settings().load("DT"))

    def update(self, target_day_direction) -> None:
        log.info(f"Updating strategies ({target_day_direction})")

        profitable_strategies = sorted(
            self.walker.traverse_strategies(
                PERIOD_UPDATE,
                "1m",
                Cache.APPEND,
                filter_strategies=True,
                loaded_strategies=[],
                target_day_direction=target_day_direction,
            ),
            key=lambda s: (s["points"], s["profit"]),
            reverse=True,
        )

        indicators_counter = Helper.count_indicators_usage(profitable_strategies)

        Strategy.dump(
            "DT",
            {
                **Strategy.load("DT"),
                **{f"{target_day_direction}_{PERIOD_UPDATE}": profitable_strategies},
                **{f"{target_day_direction}_indicators_stats": indicators_counter},
            },
        )

    def test(self, target_day_direction: str):
        log.info(f"Testing strategies ({target_day_direction})")

        stored_strategies = Strategy.load("DT")

        profitable_strategies = sorted(
            self.walker.traverse_strategies(
                PERIOD_TEST,
                "1m",
                Cache.APPEND,
                filter_strategies=True,
                loaded_strategies=[
                    i["strategy"]
                    for i in stored_strategies.get(
                        f"{target_day_direction}_{PERIOD_UPDATE}", []
                    )
                ],
                target_day_direction=target_day_direction,
            ),
            key=lambda s: s["points"] * 100 + s["profit"],
            reverse=True,
        )

        Strategy.dump(
            "DT",
            {
                **stored_strategies,
                **{f"{target_day_direction}_{PERIOD_TEST}": profitable_strategies},
                **{"act": []},
            },
        )

    def pick(self) -> None:
        log.info("Picking strategies")

        self.walker.update_trading_settings()

        stored_strategies = Strategy.load("DT")

        strategies_to_test = []
        for direction in ["BULL", "BEAR", "range"]:
            strategies_to_test += [
                i["strategy"]
                for i in stored_strategies.get(f"{direction}_{PERIOD_TEST}", [])
                if int(i["efficiency"][:-1]) > 60
            ]
        strategies_to_test = list(set(strategies_to_test))

        profitable_strategies = sorted(
            self.walker.traverse_strategies(
                "1d",
                "1m",
                Cache.SKIP,
                filter_strategies=False,
                loaded_strategies=strategies_to_test,
            ),
            key=lambda s: s["profit"],
            reverse=True,
        )

        Strategy.dump(
            "DT",
            {
                **stored_strategies,
                **{"act": [s["strategy"] for s in profitable_strategies][:3]},
            },
        )


def run(update: bool = True, pick: bool = True, show_orders: bool = False) -> None:
    trading_time = TradingTime()
    calibration = Calibration()
    Helper.show_orders = show_orders

    # day run
    while True:
        if not pick:
            break

        try:
            trading_time.update_day_time()

            if trading_time.day_time == DayTime.MORNING:
                pass

            elif trading_time.day_time == DayTime.DAY:
                calibration.pick()

            elif trading_time.day_time == DayTime.EVENING:
                break

            time.sleep(60 * 5)

        except Exception as e:
            log.error(f">>> {e}: {traceback.format_exc()}")

    # full calibration
    try:
        for target_day_direction in ["BULL", "BEAR", "range"]:
            if update:
                calibration.update(target_day_direction)

            calibration.test(target_day_direction)

        TeleLog(message="DT Calibration: Done")

    except Exception as e:
        log.error(f">>> {e}: {traceback.format_exc()}")

        TeleLog(crash_report=f"DT Calibration: script has crashed: {e}")

    return