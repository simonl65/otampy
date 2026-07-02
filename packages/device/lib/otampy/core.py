class NullLogger:
    """Logger-compatible sink used when an application does not inject one."""

    min_level = 6

    def log(self, *_args):
        pass

    debug = info = warning = error = critical = log


class UartRequiredError(Exception):
    pass


def _get_config(config, name, default=None):
    getter = getattr(config, "get", None)
    if getter is not None:
        return getter(name, default)
    return getattr(config, name, default)


class OTACore:
    """
    OTACore provides the base initialisation, shared state, configuration,
    logging, and reliable transport mechanisms for both boot and runtime.
    """

    def __init__(self, uart, config=None, logger=None):
        if config is None:
            config = {}
        if config == {}:
            config["LOG_LEVEL"] = "DEBUG"
            config["LOG_FILE"] = "/logs/ota.log"
            config["UPDATE_REQUEST_FLAG_FILE"] = "update_requested.flag"
        self.config = config

        self.logger = logger if logger is not None else NullLogger()

        if uart is None:
            self.logger.critical("Must provide a UART object")
            raise UartRequiredError("Must provide a UART object")

        self.uart = uart
        self._transport = None

    @property
    def transport(self):
        """Create the reliable transport only when an operating mode needs it."""
        if self._transport is None:
            from urst import Urst  # type: ignore

            self._transport = Urst(self.uart)
        return self._transport

    @transport.setter
    def transport(self, transport):
        self._transport = transport
