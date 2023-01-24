"""
This module is used by crontab (for every day run)
"""

from module.utils import Logger
from module import run_long_trading


if __name__ == "__main__":
    Logger(logger_name="main", file_prefix="auto_long_trading")

    run_long_trading()
