"""
This module is used by crontab (for every day run)
"""

from module.utils import Logger
from module import run_portfolio_analysis


if __name__ == "__main__":
    Logger(logger_name="main", file_prefix="auto_portfolio_analysis")

    run_portfolio_analysis()
