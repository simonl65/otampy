import packages.device.examples.config as config
from packages.device.lib.Log_to_file import Logger
from packages.device.lib.otampy.ota import OTAManager

try:
    import utime as time  # pyright: ignore[reportMissingImports]
except ImportError:
    import time

logger = Logger(config.LOG_LEVEL, config.LOG_FILE)

# Initialize UART 0 on pins GP0 (TX) and GP1 (RX)
# On a Pico, UART(0) uses GP0/GP1 by default.
try:
    import machine  # pyright: ignore[reportMissingImports]

    uart = machine.UART(
        config.OTA_PORT,
        baudrate=config.OTA_BAUDRATE,
        tx=machine.Pin(config.OTA_TX_PIN),
        rx=machine.Pin(config.OTA_RX_PIN),
    )
except ImportError:
    print("Not running on MicroPython, or machine module not available.")
    print("Falling back to a mock/simulated serial for demonstration.")

    # This part is just so the script can be 'run' on desktop without errors
    class MockUART:
        def write(self, data):
            return len(data)

        def read(self, n):
            return b"Mock read data"

        def any(self):
            return 0

    uart = MockUART()


# =============================================================================
# APPLICATION FUNCTIONS
# =============================================================================
def do_application_stuff():
    """Placeholder function for main application logic."""
    logger.info("Doing application stuff...")


def application_callback():
    """Placeholder function for application callback logic."""
    logger.info("Application callback called.")


# =============================================================================
# MAIN FUNCTION
# =============================================================================
def main():
    ota_manager = OTAManager(uart, config)

    try:
        while True:
            """Main application loop."""

            do_application_stuff()

            ota_manager.check_for_update(callback=None)

            time.sleep(1.5)

    except KeyboardInterrupt:
        logger.info("Shutting down application.")
    finally:
        logger.close()


if __name__ == "__main__":
    main()
