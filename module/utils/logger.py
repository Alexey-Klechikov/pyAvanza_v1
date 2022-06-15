"""
Logging events.
(File logger + Colored Console logger)
"""

import os
import copy
import logging
import datetime


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

    def __init__(self, pattern):
        logging.Formatter.__init__(self, pattern)
        self.ptn = pattern

    def format(self, record):
        colored_record = copy.copy(record)
        levelname = colored_record.levelname
        colored_levelname = (
            f"{self.PREFIX}{self.MAPPING.get(levelname, 38)}m{levelname}{self.SUFFIX}"
        )
        colored_record.levelname = colored_levelname
        return logging.Formatter.format(self, colored_record)


class OneLineFormatter(logging.Formatter):
    def format(self, record):
        s = super(OneLineFormatter, self).format(record)
        s = s.replace("\n", "")
        if s.find("Done"):
            s = s.split("--")[0]

        return s


class Logger:
    def __init__(self, logger_name, file_prefix, log_level="INFO"):
        self.log_file_name = self.get_log_file_name(file_prefix)
        self.log = logging.getLogger(logger_name)
        self.set_handlers(console_bool=True, file_bool=True)
        self.log.setLevel(os.environ.get("LOGLEVEL", log_level))

    def get_log_file_name(self, file_prefix):
        log_dir = os.path.join(
            "/".join(os.path.abspath(__file__).split("/")[:-3]), "logs"
        )
        if not os.path.exists(log_dir):
            os.mkdir(log_dir)

        return f"{log_dir}/{file_prefix}_"

    def set_handlers(self, console_bool, file_bool):
        if console_bool:
            # Add console handler using our custom ColoredFormatter
            ch = logging.StreamHandler()
            ch.setLevel(logging.DEBUG)
            cf = ColoredFormatter("[%(levelname)s] [%(name)s] - %(message)s")
            ch.setFormatter(cf)
            self.log.addHandler(ch)

        if file_bool:
            # Add file handler
            fh = logging.FileHandler(
                f"{self.log_file_name}{datetime.datetime.now():%Y-%m-%d_%H.%M}.log"
            )
            fh.setLevel(logging.DEBUG)
            ff = OneLineFormatter(
                "[%(levelname)s] [%(asctime)s] [%(name)s] - %(message)s"
            )
            fh.setFormatter(ff)
            self.log.addHandler(fh)

    def reset_file_handler(self):
        fh = [i for i in self.log.handlers if isinstance(i, logging.FileHandler)][0]

        fh.close()
        self.log.removeHandler(fh)

        self.set_handlers(console_bool=False, file_bool=True)
