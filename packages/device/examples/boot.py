import config
from log_to_file import Logger  # type: ignore
from machine import UART, Pin  # type: ignore
from urst import Urst  # type: ignore
from utime import sleep_ms  # type: ignore

from otampy.ota import (  # type: ignore
    OTALogger,
    OTAManager,
)

logger = (
    Logger(config.LOG_FILE, "boot.py", level=config.LOG_LEVEL) or OTALogger()
)

uart = UART(
    config.OTA_PORT,
    baudrate=config.OTA_BAUDRATE,
    tx=Pin(config.OTA_TX_PIN),
    rx=Pin(config.OTA_RX_PIN),
)
print(uart)

urst = Urst(uart)

ota_manager = OTAManager(uart, config=config, logger=None)

led = Pin("LED", Pin.OUT)

led.on()

urst.send(b"BOOTING...\n")

ota_manager.check_for_update()

urst.send(b"Loading MAIN...\n")

sleep_ms(200)
