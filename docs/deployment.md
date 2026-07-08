# Device deployment

The `otampy deploy` command installs the device library, example application,
and MicroPython dependencies over a direct USB/serial connection.

> [!WARNING]
> Deployment erases the device filesystem. Back up application data and
> configuration before continuing.

## Prerequisites

- A connected MicroPython device accessible to `mpremote`.
- The OTAmpy CLI and `mpremote` installed on the host.
- A configured OTAmpy project.

For a project using an installed OTAmpy package, create the project-owned
device files and edit the generated configuration:

```bash
otampy init
```

This creates `device/boot.py`, `device/main.py`, and `device/configota.py`.
Set the UART port, pins, baud rate, and timeout in `device/configota.py`.
`otampy init` refuses to overwrite any of these files unless `--force` is
given.

In an OTAmpy source checkout, deployment remains compatible with
`packages/device`: create `packages/device/examples/configota.py` from
`config.example.py`.

Use a dry run to inspect the operation without changing the device:

```bash
otampy deploy --port /dev/ttyACM0 --dry-run
```

Run the command from the project root or pass `--device-dir /path/to/project/device`.

## Source profile

For an installed package, the default profile installs:

- the versioned device library bundled with the installed OTAmpy package as
  `/lib`;
- the project's `device/configota.py`, `device/boot.py`, and `device/main.py` at
  the device root;
- URST using MicroPython's `mip`.

When run from this repository, it instead uses the canonical
`packages/device/lib/` and `packages/device/examples/` files directly.

```bash
otampy deploy --port /dev/ttyACM0
```

No file logger is installed. OTAmpy and the examples use `NullLogger`, so the
application runs silently without importing a file-logging implementation.

This profile keeps OTAmpy and URST as editable `.py` files and is the
recommended development profile.

## Development logging profile

Add `--with-logger` to install `log-to-file` alongside URST:

```bash
otampy deploy --port /dev/ttyACM0 --with-logger
```

The example `boot.py` and `main.py` detect that package and construct
`log_to_file.Logger` using `LOG_FILE` and `LOG_LEVEL` from `configota.py`. If the
package is later absent, the same scripts fall back to `NullLogger`; no source
change is required.

Applications may instead inject any logger implementing `debug`, `info`,
`warning`, `error`, and `critical`:

```python
from otampy import OTA

logger = MyLogger()
ota = OTA(uart, config=config, logger=logger)
```

## Target-matched bytecode profile

Install MicroPython's `mpy-cross` tool, or provide a command that runs it:

```bash
uv tool install mpy-cross
```

Then deploy with `--bytecode` (also available as `--mpy`):

```bash
otampy deploy --port /dev/ttyACM0 --bytecode
```

The bytecode profile:

1. queries `sys.implementation._mpy` and the target's positive small-int
   width;
2. compiles OTAmpy, `Blink`, and the CLI's installed URST package into a
   temporary `/lib` tree;
3. rejects wrong `.mpy` versions, excessive small-int widths, and unexpected
   architecture-specific output before erasing the device;
4. deploys only `.mpy` library/dependency modules. `boot.py`, `main.py`, and
   `configota.py` remain source files.

Use `--mpy-cross` when the compiler is not directly on `PATH`, for example:

```bash
otampy deploy --port /dev/ttyACM0 --bytecode --mpy-cross "uvx --from mpy-cross mpy-cross"
```

The compiler only emits portable MicroPython bytecode; OTAmpy does not request
native architecture output. Rebuild for each target firmware rather than
copying `.mpy` files between devices. MicroPython source files take precedence
over matching `.mpy` files, so do not mix both forms in `/lib`.

The bytecode profile already packages URST and therefore performs no MIP
installation. It cannot be combined with `--with-logger`; use the source
profile for development file logging.

## Options

| Option                   | Description                                                        |
| ------------------------ | ------------------------------------------------------------------ |
| `-p`, `--port PORT`      | Select the device port, such as `/dev/ttyACM0` or `COM3`.          |
| `--device-dir DIRECTORY` | Select the directory containing `device/` templates.               |
| `--with-logger`          | Install `log-to-file` for development logging.                     |
| `--bytecode`, `--mpy`    | Compile and deploy target-matched `.mpy` libraries.                |
| `--mpy-cross COMMAND`    | Select the compiler executable or command.                         |
| `--no-mip`               | Skip every MIP dependency, including URST and the optional logger. |
| `--no-reset`             | Do not reset the device after deployment.                          |
| `--dry-run`              | Print the `mpremote` command without executing it.                 |
| `--mpremote PATH`        | Select a different `mpremote` executable.                          |

`--with-logger` has no effect when combined with `--no-mip`.
Use `--no-mip` only when the required packages are frozen into the firmware or
will be installed separately; after the filesystem erase, OTAmpy cannot poll
without URST. `--no-mip` has no additional effect on the bytecode profile.

The global `otampy --log-level LEVEL` option controls host CLI diagnostics; it
does not enable device logging. When supplied explicitly, the CLI offers to
retain that level for the shell session or permanently. Permanent host CLI
settings are stored in `~/.config/otampy/config.json`; session-only settings
use the operating system's temporary directory.

## Verification

After deployment, verify the OTA UART through its host-side adapter:

```bash
otampy --port /dev/ttyUSB0 ping
```

A working deployment prints `Success: Received PONG from device.` The USB
deployment port and OTA UART adapter are commonly different devices, as in the
examples above.
