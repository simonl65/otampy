"""
Example boot.py
"""

import config
from machine import UART, Pin  # type: ignore

from otampy import OTA, OTALogger  # type: ignore

logger = OTALogger(
    config.LOG_FILE,
    level=config.LOG_LEVEL,
    source="boot.py",
)

uart = UART(
    config.OTA_PORT,
    baudrate=config.OTA_BAUDRATE,
    tx=Pin(config.OTA_TX_PIN),
    rx=Pin(config.OTA_RX_PIN),
)
print(uart)

ota = OTA(uart, config=config, logger=logger)

led = Pin("LED", Pin.OUT)

led.on()

logger.debug("BOOTING...")


# Check for an update request flag before continuing to the main application.
ota.boot()


led.off()

logger.debug("Loading MAIN...")
