class NullLogger:
    """Logger-compatible sink used when an application does not inject one."""

    min_level = 6

    def log(self, *_args):
        pass

    debug = info = warning = error = critical = log


class UartRequiredError(Exception):
    pass


# The boot marker. Its presence at boot means the *previous* boot never
# reached OTA.poll(), so that boot gets the wide recovery window instead of
# the short one -- long enough to overlap a power-cycled XBee's wake-up, which
# the 1s window never did (F-10).
_DEFAULT_BOOT_MARK_FILE = "otampy-boot.mark"
_DEFAULT_BOOT_RECOVERY_LISTEN_MS = 8000


def _get_config(config, name, default=None):
    getter = getattr(config, "get", None)
    if getter is not None:
        return getter(name, default)
    return getattr(config, name, default)


def _resolve_path(path):
    """Absolutise a configured path. Shared by ``boot`` and ``restore``.

    Lives here rather than in ``boot`` because ``boot`` imports ``restore``;
    the other direction would be an import cycle.
    """
    if path.startswith("/"):
        return path
    import sys

    if sys.implementation.name != "micropython":
        return path
    return "/" + path


def _config_int(config, name, default):
    """Read an integer setting, falling back to ``default`` on garbage.

    A value ``int()`` cannot read is a **typo, not an off-switch**. Failing
    closed on one would let a single mistyped config key silently disable
    whatever it guards -- for the recovery window that means removing the only
    radio recovery path. Only an explicit, in-range sentinel turns something
    off, matching ``OTA_TIMEOUT_MS`` and ``restore.read_journal``.
    """
    value = _get_config(config, name, default)
    try:
        return int(value)  # type: ignore
    except (TypeError, ValueError):
        return default


def _boot_recovery_window_ms(config):
    """The wide recovery window in ms. The single parse of that key.

    ``boot`` needs the duration and ``_boot_mark_path`` needs to know whether
    the feature is on at all; parsing in both places is how the two drift.
    """
    return _config_int(
        config,
        "OTA_BOOT_RECOVERY_LISTEN_MS",
        _DEFAULT_BOOT_RECOVERY_LISTEN_MS,
    )


def _boot_mark_path(config):
    """Resolved boot-marker path, or ``None`` when the wide window is off.

    The off-switch lives here rather than at the call sites, so ``boot`` and
    ``ota`` both read ``path = _boot_mark_path(...)`` / ``if path:`` and
    neither repeats the guard. ``0`` is therefore a true off-switch with zero
    filesystem cost.
    """
    if _boot_recovery_window_ms(config) <= 0:
        return None
    return _resolve_path(
        str(_get_config(config, "OTA_BOOT_MARK_FILE", _DEFAULT_BOOT_MARK_FILE))
    )


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
