"""
This module is used by crontab (for once per week run)
"""

from module.utils import Logger
from module import run_watchlists_analysis


if __name__ == "__main__":
    Logger(logger_name="main", file_prefix="auto_watchlists_analysis")

    run_watchlists_analysis()
