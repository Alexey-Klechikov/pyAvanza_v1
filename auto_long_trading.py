from module.utils import Logger
from module import run_long_trading


if __name__ == "__main__":
    Logger(file_prefix="auto_long_trading")

    run_long_trading()
