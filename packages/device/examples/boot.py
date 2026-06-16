import config
from machine import UART, Pin  # type: ignore
from urst import Urst  # type: ignore
from utime import sleep_ms  # type: ignore

uart = UART(
    config.OTA_PORT,
    baudrate=config.OTA_BAUDRATE,
    tx=Pin(config.OTA_TX_PIN),
    rx=Pin(config.OTA_RX_PIN),
)
print(uart)

urst = Urst(uart)

led = Pin("LED", Pin.OUT)

led.on()

urst.send(b"BOOTING...\n")

for _ in range(40):
    sleep_ms(100)
    led.toggle()

led.on()

urst.send(b"Loading MAIN...\n")

sleep_ms(200)
