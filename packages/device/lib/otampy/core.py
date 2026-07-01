from .logger import OTALogger


class UartRequiredError(Exception):
    pass


class _ModuleConfig:
    """Expose module attributes through the mapping reads OTAmpy uses."""

    __slots__ = ("_source",)

    def __init__(self, source):
        self._source = source

    def get(self, name, default=None):
        try:
            return getattr(self._source, name)
        except Exception:
            return default

    def __getitem__(self, name):
        try:
            return getattr(self._source, name)
        except Exception as error:
            raise KeyError(name) from error


def _normalize_config(config):
    if config is None:
        config = {}
    elif not hasattr(config, "get"):
        config = _ModuleConfig(config)
    return config


class OTACore:
    """
    OTACore provides the base initialisation, shared state, configuration,
    logging, and reliable transport mechanisms for both boot and runtime.
    """

    def __init__(self, uart, config=None, logger=None):
        config = _normalize_config(config)
        if config == {}:
            config["LOG_LEVEL"] = "DEBUG"
            config["LOG_FILE"] = "/logs/ota.log"
            config["UPDATE_REQUEST_FLAG_FILE"] = "update_requested.flag"
        self.config = config

        self.logger = logger if logger is not None else OTALogger(level="DEBUG")

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
