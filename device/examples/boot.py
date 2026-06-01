from machine import UART, Pin  # pyright: ignore[reportMissingImports]
from urst import Urst
from utime import sleep_ms  # pyright: ignore[reportMissingImports]

uart = UART(0, baudrate=57600, tx=Pin(0), rx=Pin(1))
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
