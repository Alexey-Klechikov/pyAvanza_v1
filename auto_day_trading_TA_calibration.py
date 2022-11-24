"""
This module is used for automated runs (cron)
"""


from module import run_day_trading_ta_calibration
from module.utils import Logger

if __name__ == "__main__":
    log = Logger(
        logger_name="main",
        file_prefix="auto_day_trading_ta_calibration",
        console_log_level="INFO",
    )

    run_day_trading_ta_calibration()
