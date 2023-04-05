from src.utils import Logger
from src import run_day_trading_testing


if __name__ == "__main__":
    Logger(file_prefix="manual_day_trading_testing")

    target_dates = ["2023-04-03", "2023-03-27", "2023-03-28", "2023-03-29", "2023-03-31"]

    run_day_trading_testing(target_dates)
