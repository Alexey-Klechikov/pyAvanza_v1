"""
This module is used for automated runs (cron)
"""


from module.utils import Logger
from module import run_day_trading_cs


if __name__ == "__main__":
    log = Logger(logger_name="main", file_prefix="manual_day_trading_cs", file_log_level="INFO", console_log_level='WARNING')

    run_day_trading_cs()
