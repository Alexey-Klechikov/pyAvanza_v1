"""
This module is used by crontab (for once per week run)
"""

from module.utils import Logger
from module import run_long_trading_calibration


if __name__ == "__main__":
    Logger(logger_name="main", file_prefix="auto_long_trading_calibration")

    run_long_trading_calibration()
