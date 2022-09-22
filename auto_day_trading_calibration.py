"""
This module is used for automated runs (cron)
"""


from module.utils import Logger
from module import run_day_trading_calibration


if __name__ == "__main__":
    log = Logger(
        logger_name="main",
        file_prefix="auto_day_trading_calibration",
        console_log_level="INFO",
    )

    run_day_trading_calibration()
