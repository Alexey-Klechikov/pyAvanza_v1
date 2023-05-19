from src.utils import Logger
from src import run_day_trading_testing


if __name__ == "__main__":
    Logger(file_prefix="manual_day_trading_testing")

    target_dates = [
        "2023-05-05",
        "2023-05-04",
        "2023-05-03",
        "2023-05-02",
        "2023-04-28",
        "2023-04-27",
        "2023-04-26",
        "2023-04-25",
        "2023-04-24",
    ]

    run_day_trading_testing(target_dates)
