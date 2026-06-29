# OTAmpy Device Code

MicroPython code to be placed on the device to enable OTA functionality.

## Dependencies

- **urst-mpy** MicroPython implementation of the Universal Reliable Serial Transport protocol (Currently available on my [GitHub](https://github.com/simonl65/URST-mpy)).
- **log-to-file** [GitHub](https://github.com/simonl65/log-to-file)

## Installation

1. Ensure the device has MicroPython installed and running correctly.
1. Install OTAmpy, `urst-mpy` and `log-to-file` onto the device along with example `boot.py` and `main.py` with:

   ```bash
   otampy deploy --port <your-device-port>
   ```

1. Update `boot.py` and `main.py` with the OTAmpy specific code as shown in `examples/`).
1. Reboot the device.
