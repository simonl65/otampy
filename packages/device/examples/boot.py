import config
from log_to_file import Logger  # type: ignore
from machine import UART, Pin  # type: ignore
from utime import sleep_ms  # type: ignore

from otampy import OTA, OTALogger  # type: ignore

logger = Logger(
    config.LOG_FILE, "boot.py", level=config.LOG_LEVEL
) or OTALogger(level=config.LOG_LEVEL)

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

ota._core.transport.send(b"BOOTING...\n")

# Check for an update request flag before continuing to the main application.
ota.boot()

ota._core.transport.send(b"Loading MAIN...\n")

sleep_ms(200)
