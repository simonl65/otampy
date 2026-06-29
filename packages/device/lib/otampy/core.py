from urst import Urst  # type: ignore

from .logger import OTALogger


class UartRequiredError(Exception):
    pass


class OTACore:
    """
    OTACore provides the base initialisation, shared state, configuration,
    logging, and reliable transport mechanisms for both boot and runtime.
    """

    def __init__(self, uart, config=None, logger=None):
        if config is None:
            config = {}
            config["LOG_LEVEL"] = "DEBUG"
            config["LOG_FILE"] = "/logs/ota.log"
            config["UPDATE_REQUEST_FLAG_FILE"] = "update_requested.flag"
        self.config = config

        self.logger = (
            logger if logger is not None else OTALogger(min_level="DEBUG")
        )

        if uart is None:
            self.logger.critical("Must provide a UART object")
            raise UartRequiredError("Must provide a UART object")

        self.uart = uart
        self.transport = Urst(self.uart)
