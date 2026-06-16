from machine import Pin  # type: ignore
from utime import sleep_ms  # type: ignore


class Blink:
    def __init__(self, pin="LED"):
        self.pin = pin

    def blink(self, times):
        led = Pin(self.pin, Pin.OUT)
        for _ in range(times):
            led.on()
            sleep_ms(50)
            led.off()
            sleep_ms(50)
