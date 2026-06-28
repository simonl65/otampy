"""
This module is the corrolary to the `otampy` CLI tool. It provides device-side functionality for performing over-the-air updates on MicroPython devices.
The OTAManager class is responsible for managing the update process, including handling the update logic and communicating with the device.
This module is designed to be used in conjunction with the `otampy` CLI tool to facilitate seamless OTA updates for MicroPython devices.
"""

from time import time

from urst import Urst  # type: ignore

try:
    import uos as _os
except Exception:
    import os as _os


OTA_COMMANDS = [
    "PING",  # Respond with "PONG"
    "CAT",  # View content of file
    "LS",  # List folder content
    "RM",  # Remove item(s)
    "BL",  # Enter bootloader
    "RB",  # Hard reset
    "SR",  # Soft reset
    "UPDATE_REQUEST",  # Initiate firmware update process
]


class OTALogger:
    """
    Fallback logging - Logs messages to stdout
    """

    log_levels = [
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ]

    def __init__(self, path="ota.log", min_level="ERROR"):
        self.path = path
        self.min_level = self.log_levels.index(min_level)

    def _log(self, level, msg):
        if self.log_levels.index(level) < self.min_level:
            return
        MIN_TS_WIDTH = 18
        MIN_LEVEL_WIDTH = 8
        line = (
            "["
            + (str(time())[:MIN_TS_WIDTH]).ljust(MIN_TS_WIDTH, " ")
            + "] ["
            + (level[:MIN_LEVEL_WIDTH]).ljust(MIN_LEVEL_WIDTH, " ")
            + "] "
            + msg
            + "\n"
        )
        try:
            with open(self.path, "a") as f:
                f.write(line)
        except OSError:
            print(line)

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


class UartRequiredError(Exception):
    pass


# =============================================================================
# RUN-TIME PROCESSES (main.py)
# =============================================================================
class OTAManager:
    """
    The OTAManager class provides methods for:
        - Checking for OTA commands
        - Performing over-the-air updates
    """

    def __init__(self, uart, config=None, logger=None):
        # Initialise the logger and configuration
        if config is None:
            config = {}
            config["LOG_LEVEL"] = "DEBUG"
            config["LOG_FILE"] = "/logs/ota.log"
            config["UPDATE_REQUEST_FLAG_FILE"] = "update_requested.flag"
        self.config = config

        # Use OTALogger if none passed-in
        self.logger = (
            logger if logger is not None else OTALogger(min_level="DEBUG")
        )

        # Initialise the UART connection to the device
        if uart is None:
            self.logger.critical("Must provide a UART object")
            raise UartRequiredError("Must provide a UART object")
        else:
            self.uart = uart
            self.transport = Urst(self.uart)

    def check_for_update(self, callback):
        """Check transport for update command and run callback if present"""
        print("TODO: Implement check_for_update")

    def ready_for_update(self):
        """Resets the device so that boot.py gets run."""
        print("TODO: Implement ready_for_update")


# =============================================================================
# BOO-TIME PROCESSES (boot.py)
# =============================================================================
class OTABoot:
    """
    Boot-time processing
    """

    def __init__(self, uart, config=None, logger=None):
        # Initialise the logger and configuration
        if config is None:
            config = {}
            config["LOG_LEVEL"] = "DEBUG"
            config["LOG_FILE"] = "/logs/ota.log"
            config["UPDATE_REQUEST_FLAG_FILE"] = "update_requested.flag"
        self.config = config

        # Use OTALogger if none passed-in
        self.logger = logger if logger is not None else OTALogger()

        # Initialise the UART connection to the device
        self.uart = uart

        from urst import Urst  # type: ignore

        self.transport = Urst(self.uart)

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
