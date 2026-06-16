import config
from log_to_file import Logger  # type: ignore

from Blink import Blink  # type: ignore
from otampy.ota import OTAManager  # type: ignore

blinker = Blink(pin="LED")

try:
    import utime as time  # pyright: ignore[reportMissingImports]
except ImportError:
    import time


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


logger = Logger(config.LOG_FILE, "main.py", level=config.LOG_LEVEL)
logger = logger if logger is not None else _NullLogger()

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
    ota_manager = OTAManager(uart, config=config, logger=logger)

    try:
        while True:
            """Main application loop."""

            do_application_stuff()

            ota_manager.check_for_update(callback=application_callback)

            blinker.blink(1)
            time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt: Shutting down application.")

    finally:
        logger.info("Shutdown complete.")
        for _ in range(10):
            blinker.blink(2)
            time.sleep(0.5)


if __name__ == "__main__":
    main()
