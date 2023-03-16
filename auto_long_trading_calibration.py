from scr.utils import Logger
from scr import run_long_trading_calibration


if __name__ == "__main__":
    Logger(file_prefix="auto_long_trading_calibration")

    run_long_trading_calibration()
