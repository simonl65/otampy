import config
from log_to_file import Logger  # type: ignore

from Blink import Blink  # type: ignore
from otampy import OTA, OTALogger  # type: ignore

blinker = Blink(pin="LED")

try:
    import utime as time  # pyright: ignore[reportMissingImports]
except ImportError:
    import time

logger = (
    Logger(config.LOG_FILE, "main.py", level=config.LOG_LEVEL) or OTALogger()
)

# Initialize UART 1 on pins GP4 (TX) and GP5 (RX)
try:
    import machine  # pyright: ignore[reportMissingImports]

    uart = machine.UART(
        config.OTA_PORT,
        baudrate=config.OTA_BAUDRATE,
        tx=machine.Pin(config.OTA_TX_PIN),
        rx=machine.Pin(config.OTA_RX_PIN),
    )
except ImportError:
    logger.warning(
        "Not running on MicroPython, or machine module not available."
    )
    logger.debug("Falling back to a mock/simulated serial for demonstration.")

    # This part is just so the script can be 'run' on desktop without errors
    class MockUART:
        def write(self, data):
            return len(data)

        def read(self, n=None):
            return b"Mock read data"

        def any(self):
            return 0

    uart = MockUART()


# =============================================================================
# APPLICATION FUNCTIONS
# =============================================================================
def do_application_stuff():
    """Placeholder function for main application logic."""
    data = uart.read()
    if data:
        logger.debug(f"data: {data}")


def application_callback():
    """Placeholder function for application callback logic."""
    logger.info("Application callback called.")


# =============================================================================
# MAIN FUNCTION
# =============================================================================
def main():
    ota = OTA(uart, config=config, logger=logger)

    # Cache attributes/methods to eliminate loop lookup overhead
    ota_poll = ota.poll
    do_app = do_application_stuff
    blink_func = blinker.blink
    sleep_func = time.sleep

    try:
        while True:
            """Main application loop."""

            do_app()

            # Poll OTA commands from the host CLI over UART.
            ota_poll(callback=application_callback)

            blink_func(1)
            sleep_func(0.1)

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt: Shutting down application.")

    finally:
        logger.info("Shutdown complete.")
        for _ in range(10):
            blinker.blink(2)
            time.sleep(0.5)


if __name__ == "__main__":
    main()
