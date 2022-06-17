"""
This module is used for manual runs
"""


from module.utils import Logger
from module import run_day_trading


if __name__ == "__main__":
    log = Logger(logger_name="main", file_prefix="manual_rtt", file_log_level="WARNING")

    multiplier = 18
    budget = 20000

    run_day_trading(multiplier, budget)
