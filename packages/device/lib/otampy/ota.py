"""
This module is the corrolary to the `otampy` CLI tool. It provides device-side functionality for performing over-the-air updates on MicroPython devices.
The OTAManager class is responsible for managing the update process, including handling the update logic and communicating with the device.
This module is designed to be used in conjunction with the `otampy` CLI tool to facilitate seamless OTA updates for MicroPython devices.
"""


class OTAManager:
    """The OTAManager class provides methods for performing over-the-air updates on devices."""

    def __init__(self, uart, config=None):
        try:
            from urst import Urst

            """Initializes a new OTAManager object."""
            # Initialize URST with the UART object
            self.transport = Urst(uart)

            # Initialise the logger and configuration
            if config is None:
                config = {}
                config["LOG_LEVEL"] = "DEBUG"
                config["LOG_FILE"] = "/logs/ota.log"
            self.config = config

            self.logger = Logger(self.config.LOG_LEVEL, self.config.LOG_FILE)

            # Initialise the UART connection to the device
            self.uart = uart

        except (ImportError, AttributeError):
            print(
                "Not running on MicroPython, or machine module not available."
            )
            print("Falling back to a mock/simulated serial for demonstration.")

            # This part is just so the script can be 'run' on desktop without errors
            class MockUART:
                def write(self, data):
                    return len(data)

                def read(self, n):
                    return b""

                def any(self):
                    return 0

            self.transport = Urst(MockUART())

    def check_for_update(self, callback):
        """Checks for presence of update request flag file. If found, runn the application callback function."""
        self.logger.debug(
            "Checking for presence of update request flag file..."
        )
        pass

    def ready_for_update(self):
        """Resets the device so that boot.py gets run."""
        pass

    def handle_update(self):
        """Handles the update process on the device."""
        pass
