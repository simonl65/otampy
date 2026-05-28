# OTAmpy Device Code

MicroPython code to be placed on the device to enable OTA functionality.

## Dependencies

- **urst-mpy** MicroPython implementation of the Universal Reliable Serial Transport protocol (Currently available on my [GitHub](https://github.com/simonl65/URST-mpy)).

## Installation

1. Ensure the device has MicroPython installed and running correctly.
1. Install `urst-mpy` onto the device with:

   ```bash
   mpremote mip install github:simonl65/URST-mpy
   ```

1. Copy all folders and files in this `/device` folder to the root of the device.
1. Update `main.py` with with the OTAmpy specific code shown in `main-example.py`).
1. Reboot the device.
