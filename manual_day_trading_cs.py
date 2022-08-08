"""
This module is used for manual runs
"""


from module.utils import Logger
from module import run_day_trading_cs


if __name__ == "__main__":
    log = Logger(logger_name="main", file_prefix="manual_day_trading_cs", file_log_level="INFO", console_log_level='WARNING')

    multiplier = 20
    budget = 1200

    run_day_trading_cs(multiplier, budget)
