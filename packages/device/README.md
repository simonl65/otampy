# OTAmpy Device Code

MicroPython code to be placed on the device to enable OTA functionality.

## Dependencies

- **[urst-mpy](https://github.com/simonl65/URST-mpy)** is the required
  MicroPython implementation of the Universal Reliable Serial Transport
  protocol.
- **[log-to-file](https://github.com/simonl65/log-to-file)** is an optional
  development dependency. When it is absent, OTAmpy and the example
  application run silently.

## Installation

1. Ensure the device has MicroPython installed and running correctly.
2. Copy `examples/config.example.py` to `examples/config.py` and edit its UART
   settings.
3. Install OTAmpy and `urst-mpy` along with the example `boot.py` and `main.py`:

   ```bash
   otampy deploy --port <your-device-port>
   ```

   This command erases the device filesystem before copying the new
   deployment. Use `--dry-run` to inspect the command first.

4. To include file logging during development, add `--with-logger`:

   ```bash
   otampy deploy --port <your-device-port> --with-logger
   ```

   The example scripts automatically use `log_to_file.Logger` when it is
   installed and otherwise use `NullLogger`.

5. For a smaller deployment without development file logging, install
   `mpy-cross` and use the target-matched bytecode profile:

   ```bash
   otampy deploy --port <your-device-port> --bytecode
   ```

   OTAmpy checks the connected firmware's `.mpy` format and small-int width
   before erasing the device. It compiles OTAmpy, `Blink`, and URST; the root
   `boot.py`, `main.py`, and `config.py` remain readable source.

See the repository [deployment guide](../../docs/deployment.md) for all deploy
options.

## Logging

Logging is optional and is not required by the OTA protocol. With no logger
argument, `OTA` creates an allocation-light `NullLogger`:

```python
ota = OTA(uart, config=config)
```

Applications can inject `log-to-file` or any compatible logger:

```python
from log_to_file import Logger
from otampy import OTA

logger = Logger("/logs/ota.log", "main.py", level="DEBUG")
ota = OTA(uart, config=config, logger=logger)
```

A compatible logger provides `debug`, `info`, `warning`, `error`, and
`critical` methods. The methods should accept a message followed by optional
`%`-formatting arguments. A `min_level` integer is optional; OTAmpy only uses
it to avoid constructing debug cleanup messages when debugging is disabled.

`NullLogger` is also public for applications that want one logger variable
while keeping calls unconditional:

```python
from otampy import NullLogger

logger = NullLogger()
logger.debug("This is intentionally discarded")
```

`LOG_FILE` and `LOG_LEVEL` in the example configuration are consumed by the
example scripts only when `log-to-file` is installed.
