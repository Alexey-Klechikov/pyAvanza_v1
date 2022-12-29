"""
Logging events.
(File logger + Colored Console logger)
"""

import copy
import datetime
import logging
import os


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
        s = s.replace("BULL", "🟢 BULL").replace("BEAR", "🔴 BEAR")

        self.messages_counter += 1

        return s


class OneLineFormatter(logging.Formatter):
    def format(self, record) -> str:
        s = super(OneLineFormatter, self).format(record)
        s = s.replace("\n", "").replace("BULL", "🟢 BULL").replace("BEAR", "🔴 BEAR")

        if s.find("Done"):
            s = s.split("--")[0]

        for (block, length) in zip(s.split("]")[:3], [8, 17, 30]):
            s = s.replace(f"{block}]", f"{block}]" + (" " * (length - len(block))))

        return s


class Logger:
    def __init__(
        self,
        logger_name: str,
        file_prefix: str,
        log_level: str = "DEBUG",
        file_log_level: str = "INFO",
        console_log_level: str = "INFO",
    ):
        self.file_log_level = file_log_level
        self.console_log_level = console_log_level
        self.log_file_name = self.get_log_file_name(file_prefix)
        self.log = logging.getLogger(logger_name)
        self.set_handlers(console_show=True, save_file=True)
        self.log.setLevel(os.environ.get("LOGLEVEL", log_level))

    def get_log_file_name(self, file_prefix: str) -> str:
        log_dir = os.path.join(
            "/".join(os.path.abspath(__file__).split("/")[:-3]), "logs"
        )
        if not os.path.exists(log_dir):
            os.mkdir(log_dir)

        return f"{log_dir}/{file_prefix}_"

    def set_handlers(self, console_show: bool, save_file: bool) -> None:
        if console_show:
            ch = logging.StreamHandler()
            ch.setLevel(self.console_log_level)
            cf = ColoredFormatter("[%(levelname)s] [%(name)s] - %(message)s")
            ch.setFormatter(cf)
            self.log.addHandler(ch)

        if save_file:
            fh = logging.FileHandler(
                f"{self.log_file_name}{datetime.datetime.now():%Y-%m-%d_%H.%M}.log"
            )
            fh.setLevel(self.file_log_level)
            ff = OneLineFormatter(
                "[%(levelname)s] [%(asctime)s] [%(name)s] - %(message)s",
                datefmt="%m-%d, %H:%M:%S",
            )
            fh.setFormatter(ff)
            self.log.addHandler(fh)

    def reset_file_handler(self) -> None:
        fh = [i for i in self.log.handlers if isinstance(i, logging.FileHandler)][0]

        fh.close()
        self.log.removeHandler(fh)

        self.set_handlers(console_show=False, save_file=True)
