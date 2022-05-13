"""
This module is used by crontab (for once per week run)
"""

from module import run_watchlists_analysis
from module.utils import Logger


if __name__ == "__main__":
    Logger(logger_name="main", file_prefix="auto_watchlists_analysis")

    run_watchlists_analysis()
