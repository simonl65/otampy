# Shared UART telemetry example.
import machine
import utime

from otampy import OTA  # pyright: ignore[reportAttributeAccessIssue]

# Initialize UART (GP4 = TX, GP5 = RX on standard Pico)
uart = machine.UART(1, baudrate=57600, tx=machine.Pin(4), rx=machine.Pin(5))

# Initialize the OTA facade
ota = OTA(uart)

print("OTAmpy shared UART telemetry example started.")
print("Transmitting telemetry and polling for OTA commands...")

last_telemetry = utime.ticks_ms()
counter = 0

while True:
    # 1. Poll for incoming OTA commands
    ota.poll()

    # 2. Transmit telemetry every 2000 ms
    now = utime.ticks_ms()
    if utime.ticks_diff(now, last_telemetry) >= 2000:
        counter += 1
        telemetry_str = f"TELEMETRY: count={counter:d} uptime_ms={now:d}\n"
        uart.write(telemetry_str)
        print("Sent:", telemetry_str.strip())
        last_telemetry = now

    # Sleep 10ms to prevent CPU starvation
    utime.sleep_ms(1)
