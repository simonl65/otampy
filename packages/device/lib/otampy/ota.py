"""
This module is the corrolary to the `otampy` CLI tool. It provides device-side functionality for performing over-the-air updates on MicroPython devices.
The OTAManager class is responsible for managing the update process, including handling the update logic and communicating with the device.
This module is designed to be used in conjunction with the `otampy` CLI tool to facilitate seamless OTA updates for MicroPython devices.
"""

from time import time


class _NullLogger:
    __slots__ = ()

    def _log(self, level, msg):
        print("[" + str(time()) + "] [" + level + "] " + msg)

    def debug(self, msg):
        self._log("DEBUG", msg)

    def info(self, msg):
        self._log("INFO", msg)

    def warning(self, msg):
        self._log("WARNING", msg)

    def error(self, msg):
        self._log("ERROR", msg)

    def critical(self, msg):
        self._log("CRITICAL", msg)

    def exception(self, msg):
        self._log("ERROR", msg)


class _MockUART:
    __slots__ = ()

    def write(self, data):
        return len(data)

    def read(self, n):
        return b""

    def any(self):
        return 0


class OTAManager:
    """The OTAManager class provides methods for performing over-the-air updates on devices."""

    def _has_uart_interface(self, uart):
        try:
            return (
                callable(uart.write)
                and callable(uart.read)
                and callable(uart.any)
            )
        except AttributeError:
            return False

    def __init__(self, uart, config=None, logger=None):
        """Initializes a new OTAManager object."""
        # Initialise the logger and configuration
        if config is None:
            config = {}
            config["LOG_LEVEL"] = "DEBUG"
            config["LOG_FILE"] = "/logs/ota.log"
            config["UPDATE_REQUEST_FLAG_FILE"] = "update_requested.flag"
        self.config = config

        self.logger = logger if logger is not None else _NullLogger()

        # Initialise the UART connection to the device
        self.uart = uart
        if not self._has_uart_interface(self.uart):
            self.logger.warning(
                "UART object is not available or does not provide the expected interface."
            )
            self.logger.debug(
                "Falling back to a mock/simulated serial for demonstration."
            )
            self.uart = _MockUART()

        from urst import Urst  # type: ignore

        self.transport = Urst(self.uart)

    def check_for_update(self, callback):
        """Look only for the configured update-request flag file and run callback if present."""
        self.logger.debug("Checking for update request flag file...")
        try:
            import uos as _os  # type: ignore
        except Exception:
            import os as _os  # type: ignore

        flag = self.config["UPDATE_REQUEST_FLAG_FILE"]
        if not flag:
            return

        try:
            _os.stat(flag)
        except Exception:
            return

        try:
            self.logger.info(f"Update request flag found: {flag}")
        except Exception:
            pass

        if callable(callback):
            try:
                callback()
            except Exception as exc:
                try:
                    self.logger.error(f"Application callback raised: {exc}")
                except Exception:
                    pass

        try:
            _os.remove(flag)
        except Exception:
            try:
                getattr(_os, "unlink", lambda _p: None)(flag)
            except Exception:
                try:
                    self.logger.debug(f"Could not remove update flag: {flag}")
                except Exception:
                    pass

    def ready_for_update(self):
        """Resets the device so that boot.py gets run."""
        pass

    def handle_update(self):
        """Handles the update process on the device."""
        pass
