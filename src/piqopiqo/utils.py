from enum import StrEnum
import logging
import os
import sys

import coloredlogs


def setup_logging(logger=None):
    fmt = "%(asctime)s %(levelname)-8s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    # Always ensure the root logger is set to INFO
    root_logger = logging.getLogger()
    coloredlogs.install(
        level=logging.INFO,
        logger=root_logger,
        isatty=True,
        fmt=fmt,
        stream=sys.stdout,
        datefmt=datefmt,
    )

    level_for_passed = logging.DEBUG if os.getenv("DEBUG") == "1" else logging.INFO
    if logger and logger is not root_logger:
        coloredlogs.install(
            level=level_for_passed,
            logger=logger,
            isatty=True,
            fmt=fmt,
            stream=sys.stdout,
            datefmt=datefmt,
        )


class UpperStrEnum(StrEnum):
    @staticmethod
    def _generate_next_value_(name, start, count, last_values):
        return name
