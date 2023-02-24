from module import run_day_trading_calibration
from module.utils import Logger

if __name__ == "__main__":
    log = Logger(file_prefix="auto_day_trading_calibration")

    run_day_trading_calibration(update=True, adjust=True, show_orders=False)
