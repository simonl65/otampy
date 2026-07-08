"""
Example main.py
"""

import configota as config  # type: ignore
import machine  # type: ignore
import utime as time  # type: ignore
from Blink import Blink  # type: ignore

from otampy import OTA, NullLogger  # type: ignore

blink = Blink(pin="LED")


try:
    from log_to_file import Logger  # type: ignore
except ImportError:
    logger = NullLogger()
else:
    logger = Logger(config.LOG_FILE, "main.py", level=config.LOG_LEVEL) or NullLogger()

logger.debug("MAIN start-up...")


uart = machine.UART(
    config.OTA_PORT,
    baudrate=config.OTA_BAUDRATE,
    tx=machine.Pin(config.OTA_TX_PIN),
    rx=machine.Pin(config.OTA_RX_PIN),
)


# =============================================================================
# APPLICATION FUNCTIONS
# =============================================================================
def do_application_stuff():
    """Placeholder function for main application logic."""
    data = uart.read()
    if data:
        logger.debug(f"data: {data}")


def prepare_for_shutdown():
    """Make the device safe before shutdown"""
    logger.info("Making device safe for shutdown")
    # TODO: Implement device shutdown procedure
    logger.info("Device now safe for shutdown")


# =============================================================================
# MAIN FUNCTION
# =============================================================================
def main():
    # Instantiate OTA with our UART (and optionally config and logger)
    ota = OTA(uart, config=config, logger=logger)

    # Cache attributes/methods to eliminate loop lookup overhead
    ota_poll = ota.poll
    do_app = do_application_stuff
    blink_func = blink.blink
    sleep_func = time.sleep

    logger.debug("Application main loop started")
    shutdown_reason = "Unknown reason"
    try:
        while True:
            """Main application loop"""

            do_app()

            # Poll OTA commands from the host CLI over UART.
            ota_poll(callback=prepare_for_shutdown)

            blink_func(1)
            sleep_func(0.1)

    except KeyboardInterrupt:
        shutdown_reason = "KeyboardInterrupt"
        logger.info("KeyboardInterrupt: Shutting down application")

    except SystemExit:
        # machine.soft_reset() raises SystemExit. Capture the reason so the
        # finally block can log it, then re-raise so MicroPython performs the
        # actual soft reset after finally completes.
        shutdown_reason = "remote soft-reset command (SR)"
        raise

    except Exception as ex:
        import io
        import sys

        s = io.StringIO()
        sys.print_exception(
            ex,
            s,  # type: ignore
        )
        shutdown_reason = type(ex).__name__
        logger.error("Application exception:\n%s", s.getvalue())  # type: ignore

    finally:
        logger.info("Shutdown started: %s", shutdown_reason)
        for _ in range(5):
            blink.blink(2)
            time.sleep(0.25)
        # Make application safe
        prepare_for_shutdown()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
