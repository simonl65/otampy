import logging


class FixedLevelFormatter(logging.Formatter):
    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        level_width: int = 5,
        name_width: int = 20,
    ):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.level_width = level_width
        self.name_width = name_width

    def format(self, record: logging.LogRecord) -> str:
        ol, on = record.levelname, record.name
        record.levelname = ol.ljust(self.level_width)[: self.level_width]
        record.name = on.ljust(self.name_width)[: self.name_width]
        try:
            return super().format(record)
        finally:
            record.levelname, record.name = ol, on


def logging_formatter(
    fmt: str = "[%(levelname)s] [%(name)s] %(message)s",
    level: int = logging.DEBUG,
    level_width: int = 5,
    name_width: int = 20,
    handler: logging.Handler | None = None,
    name: str | None = None,
) -> None:
    """
    Configure logging with FixedLevelFormatter on a named or root logger.

    When a `name` is provided, only logs from that logger (and its children) will
    be emitted. Other loggers are suppressed by setting the root logger to CRITICAL
    level and disabling propagation on the named logger.

    Parameters
    ----------
    fmt:
        The logging format string passed to the formatter.
    level:
        The logging level to set on the target logger (e.g. DEBUG, INFO, etc).
    level_width:
        The fixed width for the level name field in formatted output.
    name_width:
        The fixed width for the logger name field in formatted output.
    handler:
        Optional handler to use instead of creating a new StreamHandler.
    name:
        Optional logger name to configure. If None, the root logger is used (which
        will include logs from ALL imported packages). If provided, only logs from
        this logger and its children will be emitted, and other loggers will be suppressed.
    """
    if handler is None:
        handler = logging.StreamHandler()
    handler.setFormatter(FixedLevelFormatter(fmt=fmt, level_width=level_width, name_width=name_width))

    if name is not None:
        # When configuring a named logger, suppress all other loggers
        # by setting root logger to CRITICAL (prevents propagation of other loggers)
        logging.root.setLevel(logging.CRITICAL)

    logger = logging.getLogger(name) if name else logging.getLogger()
    logger.handlers[:] = [handler]
    logger.setLevel(level)

    # Disable propagation for named loggers to prevent logs from bubbling up to root
    if name is not None:
        logger.propagate = False
