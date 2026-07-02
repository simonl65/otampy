# Device deployment

The `otampy deploy` command installs the device library, example application,
and MicroPython dependencies over a direct USB/serial connection.

> [!WARNING]
> Deployment erases the device filesystem. Back up application data and
> configuration before continuing.

## Prerequisites

- A connected MicroPython device accessible to `mpremote`.
- The OTAmpy CLI and `mpremote` installed on the host.
- A configured `packages/device/examples/config.py`. Copy
  `config.example.py` if it does not exist, then set the UART port, pins, baud
  rate, and timeout for the board.

Use a dry run to inspect the operation without changing the device:

```bash
otampy deploy --port /dev/ttyACM0 --dry-run
```

## Production profile

The default profile installs:

- `packages/device/lib/` as `/lib`;
- the configured `config.py`, plus example `boot.py` and `main.py`, at the
  device root;
- URST using MicroPython's `mip`.

```bash
otampy deploy --port /dev/ttyACM0
```

No file logger is installed. OTAmpy and the examples use `NullLogger`, so the
application runs silently without importing a file-logging implementation.

## Development logging profile

Add `--with-logger` to install `log-to-file` alongside URST:

```bash
otampy deploy --port /dev/ttyACM0 --with-logger
```

The example `boot.py` and `main.py` detect that package and construct
`log_to_file.Logger` using `LOG_FILE` and `LOG_LEVEL` from `config.py`. If the
package is later absent, the same scripts fall back to `NullLogger`; no source
change is required.

Applications may instead inject any logger implementing `debug`, `info`,
`warning`, `error`, and `critical`:

```python
from otampy import OTA

logger = MyLogger()
ota = OTA(uart, config=config, logger=logger)
```

## Options

| Option | Description |
| --- | --- |
| `-p`, `--port PORT` | Select the device port, such as `/dev/ttyACM0` or `COM3`. |
| `--with-logger` | Install `log-to-file` for development logging. |
| `--no-mip` | Skip every MIP dependency, including URST and the optional logger. |
| `--no-reset` | Do not reset the device after deployment. |
| `--dry-run` | Print the `mpremote` command without executing it. |
| `--mpremote PATH` | Select a different `mpremote` executable. |

`--with-logger` has no effect when combined with `--no-mip`.
Use `--no-mip` only when the required packages are frozen into the firmware or
will be installed separately; after the filesystem erase, OTAmpy cannot poll
without URST.

The global `otampy --log-level LEVEL` option controls host CLI diagnostics; it
does not enable device logging. When supplied explicitly, the CLI offers to
retain that level for the shell session or permanently.

## Verification

After deployment, verify the OTA UART through its host-side adapter:

```bash
otampy --port /dev/ttyUSB0 ping
```

A working deployment prints `Success: Received PONG from device.` The USB
deployment port and OTA UART adapter are commonly different devices, as in the
examples above.
