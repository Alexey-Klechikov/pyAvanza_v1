"""
This module is used by crontab (for every day run)
"""

from module import run_portfolio_analysis

if __name__ == '__main__':
    run_portfolio_analysis()
