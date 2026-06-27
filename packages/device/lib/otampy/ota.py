"""
This module is the corrolary to the `otampy` CLI tool. It provides device-side functionality for performing over-the-air updates on MicroPython devices.
The OTAManager class is responsible for managing the update process, including handling the update logic and communicating with the device.
This module is designed to be used in conjunction with the `otampy` CLI tool to facilitate seamless OTA updates for MicroPython devices.
"""

from time import time

try:
    import uos as _os
except Exception:
    import os as _os


class OTALogger:
    """
    Fallback logging - Logs messages to stdout
    """

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


class OTAManager:
    """
    The OTAManager class provides methods for:
        - Checking for OTA commands
        - Performing over-the-air updates
    """

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

        self.logger = logger if logger is not None else OTALogger()

        # Initialise the UART connection to the device
        self.uart = uart

        from urst import Urst  # type: ignore

        self.transport = Urst(self.uart)

    # =========================================================================
    # RUN-TIME PROCESSES (main.py)
    # =========================================================================
    def check_for_update(self, callback):
        """Check transport for update command and run callback if present"""
        print("TODO: Implement check_for_update")

    def ready_for_update(self):
        """Resets the device so that boot.py gets run."""
        print("TODO: Implement ready_for_update")

    # =========================================================================
    # BOOT PROCESSING (boot.py)
    # =========================================================================
    def check_for_update_file(self, callback):
        """Check if we have the configured update-request flag file and run update process if present."""
        self.logger.debug("Checking for update request flag file...")
        flag = self.config["UPDATE_REQUEST_FLAG_FILE"]

        # MUST have a flag to check for
        if not flag:
            self.logger.error("Missing filename for update request flag file")
            return

        # Do we have the flag file
        if self._do_we_have_update_flag(flag):
            self.logger.debug(f"Update request flag found: {flag}")
            self.handle_update(flag)

        # Hijack the boot process to do the update
        # return self.handle_update(flag)

    def _do_we_have_update_flag(self, flag):
        """Checks for existance of the flag file and returns boolean"""

        # Does flag exist in file system?
        try:
            _os.stat(flag)
            return True
        except OSError:
            return False

    # TODO: Implement the update process
    def handle_update(self, flag):
        """Handles the update process on the device."""
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
