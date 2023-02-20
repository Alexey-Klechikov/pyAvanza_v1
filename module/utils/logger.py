"""
Logging events.
(File logger + Colored Console logger)
"""

import copy
import datetime
import logging
import os
from typing import Tuple, Union


def displace_message(displacements: tuple, messages: Union[tuple, list]) -> str:
    return " | ".join(
        map(
            lambda y: str(y[0]) + (y[1] - len(str(y[0]))) * " ",
            zip(messages, displacements),
        )
    )


def count_errors() -> int:
    for handler in logging.getLogger("main").handlers:
        if not isinstance(handler, logging.FileHandler):
            continue

        if not "ERROR" in handler.baseFilename:
            continue

        return len([line for line in open(handler.baseFilename) if "ERROR" in line])

    return 0


def count_trades() -> Tuple[dict, list]:
    handler = [
        h
        for h in logging.getLogger("main").handlers
        if isinstance(h, logging.FileHandler)
        and "ERROR" not in h.baseFilename
        and "DEBUG" not in h.baseFilename
    ].pop()

    trades = {"good": 0, "bad": 0}
    profits = []
    for line in open(handler.baseFilename):
        if not "Verdict" in line:
            continue

        try:
            if "good" in line:
                trades["good"] += 1
            elif "bad" in line:
                trades["bad"] += 1

            profits.append(line.split("Profit: ")[1].replace("\n", ""))

        except Exception as e:
            logging.error(f"Could not parse line: {line}: {e}")

    return trades, profits


class ColoredFormatter(logging.Formatter):
    """Logging Formatter to add colors and count warning / errors"""

    MAPPING = {
        "DEBUG": 37,  # white
        "INFO": 38,  # grey
        "WARNING": 33,  # yellow
        "ERROR": 31,  # red
        "CRITICAL": 41,
    }  # white on red bg

    PREFIX = "\033["
    SUFFIX = "\033[0m"

    def __init__(self, pattern: str) -> None:
        logging.Formatter.__init__(self, pattern)

        self.messages_counter = 0

    def format(self, record) -> str:
        colored_record = copy.copy(record)
        levelname = colored_record.levelname
        colored_levelname = (
            f"{self.PREFIX}{self.MAPPING.get(levelname, 38)}m{levelname}{self.SUFFIX}"
        )
        colored_record.levelname = colored_levelname

        s = logging.Formatter.format(self, colored_record)
        s = s.replace("main.", "").replace("BULL", "🟢 BULL").replace("BEAR", "🔴 BEAR")

        self.messages_counter += 1

        return s


class OneLineFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, style="%", validate=True):
        super().__init__(fmt, datefmt, style, validate)
        self.displacements = {
            0: {"type": "time", "size": 8},
            1: {"type": "logger", "size": 9},
            2: {"type": "message", "size": 22},
        }

    def format(self, record) -> str:
        s = super(OneLineFormatter, self).format(record)
        s = (
            s.replace("\n", "")
            .replace("main.", "")
            .replace("BULL", "🟢 BULL")
            .replace("BEAR", "🔴 BEAR")
        )

        if s.find("Done"):
            s = s.split("--")[0]

        for i, block in enumerate(s.split("]")[:3]):
            s = s.replace(
                f"{block}]",
                f"{block}]" + (" " * (self.displacements[i]["size"] - len(block))),
            )

            if self.displacements[i]["type"] == "message":
                self.displacements[i]["size"] = max(
                    len(block), self.displacements[i]["size"]
                )

        return s


class LevelFilter(logging.Filter):
    def __init__(self, log_levels: list):
        log_level_to_int = {
            "DEBUG": 10,
            "INFO": 20,
            "WARNING": 30,
            "ERROR": 40,
        }

        self._low = log_level_to_int[log_levels[0]]
        self._high = log_level_to_int[log_levels[1]]
        logging.Filter.__init__(self)

    def filter(self, record):
        return self._low <= record.levelno <= self._high


class Logger:
    def __init__(
        self,
        file_prefix: str,
        logger_name: str = "main",
        console_log_levels: list = ["INFO", "WARNING"],
    ):
        self.log = logging.getLogger(logger_name)
        self.set_handlers(
            console_log_levels,
            self._get_log_file_name(file_prefix),
        )
        self.log.setLevel(os.environ.get("LOGLEVEL", "DEBUG"))

    def _get_log_file_name(self, file_prefix: str) -> str:
        log_dir = os.path.join(
            "/".join(os.path.abspath(__file__).split("/")[:-3]), "logs"
        )
        if not os.path.exists(log_dir):
            os.mkdir(log_dir)

        return f"{log_dir}/{file_prefix}_"

    def _create_console_handler(self, log_levels: list) -> None:
        ch = logging.StreamHandler()
        ch.addFilter(LevelFilter(log_levels))
        cf = ColoredFormatter("[%(levelname)s] [%(name)s] - %(message)s")
        ch.setFormatter(cf)
        self.log.addHandler(ch)

    def _create_file_handler(
        self, file_name: str, log_levels: list, write_mode: str
    ) -> None:
        fh = logging.FileHandler(file_name, write_mode)
        fh.addFilter(LevelFilter(log_levels))
        ff = OneLineFormatter(
            "[%(levelname)s] [%(asctime)s] [%(name)s] - %(message)s",
            datefmt="%H:%M:%S",
        )
        fh.setFormatter(ff)
        self.log.addHandler(fh)

    def set_handlers(
        self,
        console_log_levels: list,
        log_file_name: str,
    ) -> None:
        self._create_console_handler(console_log_levels)

        self._create_file_handler(
            file_name=f"{log_file_name}{datetime.datetime.now():%Y-%m-%d}.log",
            log_levels=["INFO", "WARNING"],
            write_mode="a",
        )

        self._create_file_handler(
            file_name=f"{log_file_name}DEBUG.log",
            log_levels=["DEBUG", "WARNING"],
            write_mode="w",
        )
        self._create_file_handler(
            file_name=f"{log_file_name}ERROR.log",
            log_levels=["ERROR", "ERROR"],
            write_mode="w",
        )
