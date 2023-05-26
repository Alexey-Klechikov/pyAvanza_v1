from src.utils import Logger
from src import run_day_trading_testing


if __name__ == "__main__":
    Logger(file_prefix="manual_day_trading_testing")

    target_dates = [
        "2023-05-25",
    ]

    run_day_trading_testing(target_dates)
