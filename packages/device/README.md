# OTAmpy Device Code

MicroPython code to be placed on the device to enable OTA functionality.

## Dependencies

- **urst-mpy** MicroPython implementation of the Universal Reliable Serial Transport protocol (Currently available on my [GitHub](https://github.com/simonl65/URST-mpy)).
- **log-to-file** is an optional development dependency. When it is absent,
  OTAmpy and the example application run silently.

## Installation

1. Ensure the device has MicroPython installed and running correctly.
1. Install OTAmpy and `urst-mpy` onto the device along with example `boot.py` and `main.py` with:

   ```bash
   otampy deploy --port <your-device-port>
   ```

   To include file logging during development, add `--with-logger`:

   ```bash
   otampy deploy --port <your-device-port> --with-logger
   ```

1. Update `boot.py` and `main.py` with the OTAmpy specific code as shown in `examples/`).
1. Reboot the device.
