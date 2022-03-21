"""
This module is used by crontab (for once per week run)
"""

from module import run_watchlists_analysis

if __name__ == '__main__':
    run_watchlists_analysis()