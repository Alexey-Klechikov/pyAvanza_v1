from src import run_day_trading_calibration
from src.utils import Logger

if __name__ == "__main__":
    log = Logger(file_prefix="auto_day_trading_calibration")

    run_day_trading_calibration()
