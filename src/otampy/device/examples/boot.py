"""
Example boot.py
"""

import configota as config  # type: ignore
from machine import UART, Pin  # type: ignore
from otampy.mux import SerialMux  # type: ignore

from otampy import OTA, NullLogger  # type: ignore

try:
    from log_to_file import Logger  # type: ignore
except ImportError:
    logger = NullLogger()
else:
    logger = (
        Logger(
            config.LOG_FILE,
            "boot.py",
            level=config.LOG_LEVEL,
            max_bytes=getattr(config, "LOG_MAX_BYTES", 10240),
            backup_count=getattr(config, "LOG_BACKUP_COUNT", 1),
            use_ticks=getattr(config, "LOG_USE_TICKS", False),
        )
        or NullLogger()
    )

# `uart` is shared between OTAmpy and the application (see main.py's
# do_application_stuff()). SerialMux gives each side an isolated channel
# over that one physical UART, so the application can never steal bytes
# meant for OTA framing (or vice versa).
uart = UART(
    config.OTA_PORT,
    baudrate=config.OTA_BAUDRATE,
    tx=Pin(config.OTA_TX_PIN),
    rx=Pin(config.OTA_RX_PIN),
)
mux = SerialMux(uart)
print(uart)


led = Pin("LED", Pin.OUT)

led.on()

logger.debug("BOOTING...")


# Check for an update request flag before continuing to the main application.
OTA(mux.ota_port, config=config, logger=logger).boot()


led.off()

logger.debug("Loading MAIN...")
