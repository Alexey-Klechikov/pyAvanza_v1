from src.utils import Logger
from src import run_day_trading


if __name__ == "__main__":
    log = Logger(file_prefix="auto_day_trading")

    run_day_trading(dry=False)
