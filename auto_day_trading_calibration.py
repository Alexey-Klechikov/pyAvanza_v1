from scr import run_day_trading_calibration
from scr.utils import Logger

if __name__ == "__main__":
    log = Logger(file_prefix="auto_day_trading_calibration")

    run_day_trading_calibration(update=True, pick=True, show_orders=False)
