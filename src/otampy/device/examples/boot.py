"""
Example boot.py
"""

import src.otampy.device.examples.config as config
from machine import UART, Pin  # type: ignore
from src.otampy import OTA, NullLogger  # type: ignore

try:
    from log_to_file import Logger  # type: ignore
except ImportError:
    logger = NullLogger()
else:
    logger = (
        Logger(config.LOG_FILE, "boot.py", level=config.LOG_LEVEL)
        or NullLogger()
    )

uart = UART(
    config.OTA_PORT,
    baudrate=config.OTA_BAUDRATE,
    tx=Pin(config.OTA_TX_PIN),
    rx=Pin(config.OTA_RX_PIN),
)
print(uart)


led = Pin("LED", Pin.OUT)

led.on()

logger.debug("BOOTING...")


# Check for an update request flag before continuing to the main application.
OTA(uart, config=config, logger=logger).boot()


led.off()

logger.debug("Loading MAIN...")
