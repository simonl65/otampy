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
        from urst import Urst

        """Initializes a new OTAManager object."""
        # Initialise the logger and configuration
        if config is None:
            config = {}
            config["LOG_LEVEL"] = "DEBUG"
            config["LOG_FILE"] = "/logs/ota.log"
        self.config = config

        self.logger = logger if logger is not None else _NullLogger()

        # Initialise the UART connection to the device
        self.uart = uart
        if self._has_uart_interface(uart):
            self.transport = Urst(uart)
        else:
            self.logger.warning(
                "UART object is not available or does not provide the expected interface."
            )
            self.logger.debug(
                "Falling back to a mock/simulated serial for demonstration."
            )

            # This part is just so the script can be 'run' on desktop without errors
            class MockUART:
                def write(self, data):
                    return len(data)

                def read(self, n):
                    return b""

                def any(self):
                    return 0

            self.uart = MockUART()
            self.transport = Urst(self.uart)

    def check_for_update(self, callback):
        """Checks for presence of update request flag file. If found, runn the application callback function."""
        self.logger.debug(
            "Checking for presence of update request flag file..."
        )

    def ready_for_update(self):
        """Resets the device so that boot.py gets run."""
        pass

    def handle_update(self):
        """Handles the update process on the device."""
        pass
