"""
This module is used by crontab (for every day run)
"""

from module import run_portfolio_analysis
from module.utils import Logger


if __name__ == "__main__":
    Logger(logger_name="main", file_prefix="auto_portfolio_analysis")

    run_portfolio_analysis()
