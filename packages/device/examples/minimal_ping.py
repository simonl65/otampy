# Super minimal device script to test PING/PONG handshake.
import machine

from otampy import OTA  # pyright: ignore[reportAttributeAccessIssue]

# Initialize UART (GP4 is TX, GP5 is RX on standard Raspberry Pi Pico)
uart = machine.UART(1, baudrate=57600, tx=machine.Pin(4), rx=machine.Pin(5))

# Initialize the OTA facade
ota = OTA(uart)

print("OTAmpy minimal ping example started.")
print("Waiting for PING commands over UART...")

while True:
    # Poll for incoming commands
    ota.poll()
