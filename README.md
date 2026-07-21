# OTAmpy — Over-The-Air Update Suite for MicroPython

![Static Badge](<https://img.shields.io/badge/status-stable_(2.3.0)-green>)

[![License: SUL-1.0](https://img.shields.io/badge/license-SUL--1.0-blue.svg)](LICENSE.md)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![PyPI version](https://img.shields.io/pypi/v/otampy.svg)](https://pypi.org/project/otampy/)

OTAmpy is a lightweight Over-The-Air (OTA) file and system management suite for MicroPython microcontrollers (Raspberry Pi Pico, ESP32, ESP8266, and compatible boards). It provides robust remote firmware updates and device control over wireless serial modules (such as XBee) or any transparent UART connection.

OTAmpy is built on top of the **Universal Reliable Serial Transport (URST)** protocol, which guarantees error-free framing, integrity checking, and automatic recovery even over noisy or high-latency wireless links.

View the latest version at [https://otampy.codeability.co.uk/](https://otampy.codeability.co.uk/)

**DISCLAIMER** This is not intended as professional grade OTA. Use at your own risk.

---

## Features

- **Transactional OTA firmware updates** — files are staged, SHA-256 verified, and atomically committed; a failed transfer leaves the running firmware untouched.
- **Interactive file management** — upload (`cp`, `upd`), view (`cat`), or remove (`rm`) files on the device.
- **Recovery protection** — `rm` refuses to delete boot, main, configuration, OTAmpy, or URST files needed for future wireless maintenance; no force option exists.
- **Remote reboot and reset** — trigger a hard reboot (`rb`) or MicroPython soft reset (`sr`) over the air.
- **Diagnostic commands** — `ping` health checks and `mem` RAM/flash queries.
- **Port management** — `ports` lists and selects adapters; `OTAMPY_PORT` and persistent `~/.config/otampy/config.json` settings avoid repeating `--port` on every command.
- **Target-matched bytecode deployment** — `--bytecode` compiles OTAmpy and URST to `.mpy` using the connected device's exact `.mpy` format and small-int width.
- **Fail-safe CLI** — destructive commands display a confirmation prompt before contacting the device.

---

## Repository Structure

```
otampy/
├── src/otampy/           # Host CLI package (Python ≥ 3.12)
│   ├── cli.py            # Click-based command-line interface
│   ├── deploy.py         # Deploy command implementation
│   └── device/           # MicroPython device library (bundled in releases)
│       ├── lib/otampy/   # Device-side OTA library
│       └── examples/     # Example boot.py, main.py, config files
├── docs/                 # Deployment, release, architecture, and protocol guides
├── tests/                # Host-side pytest suite
└── scripts/              # Automated release gate
```

The published package contains both the CLI and a read-only copy of the device library. The canonical device source lives in `src/otampy/device/`; see the [deployment guide](docs/deployment.md) for how it is bundled.

---

## Installation

Assumes your project will be using UV

```bash
uv add otampy
otampy init
# Edit configota.py
```

During development you can use `pipx install git+https://github.com/simonl65/otampy.git@develop --force` to install the latest development version.

`init` creates `boot.py`, `main.py`, and `configota.py` in your project at the location (`device-dir`) of your choosing. Edit `configota.py` to set the UART pins, baud rate, and timeout for your board. `init` will not overwrite existing files but will prompt you; use `--force` only when intentionally replacing all three.

Preview then perform the initial USB deployment:

> **WARNING**  
> `deploy` erases the device filesystem before copying files. Back up any application data and configuration first.

```bash
# Edit configota.py before deployment
otampy deploy --port /dev/ttyACM0 --dry-run
otampy deploy --port /dev/ttyACM0
```

The installed package contains the versioned OTAmpy device library and the templates used by `init`. Your project owns `boot.py`, `main.py`, and `configota.py`; upgrading the package does not overwrite them.

### Developer installation from this repository

Ensure [uv](https://github.com/astral-sh/uv) is installed, then:

```bash
cd /path/to/otampy
uv sync
uv tool install -e .
```

### Device library setup (repository checkout)

1. **Copy** `src/otampy/device/examples/config.example.py` to `src/otampy/device/examples/configota.py` (do not rename) and set the UART pins and baud rate for your board.
2. Deploy the device library, example scripts, and URST to your device:

   ```bash
   otampy deploy --port /dev/ttyACM0
   ```

3. Optionally add `--with-logger` to install the [`log-to-file`](https://github.com/simonl65/log-to-file) development logger. The default profile runs silently via `NullLogger`.
4. For a smaller, target-matched deployment, install `mpy-cross` and pass `--bytecode`. OTAmpy queries the connected firmware's `.mpy` format before erasing anything.

   ```bash
   uv tool install mpy-cross
   otampy deploy --port /dev/ttyACM0 --bytecode
   ```

5. Call `ota.poll()` inside your application main loop to enable background OTA listening.

See the [deployment guide](docs/deployment.md) and [device integration guide](src/otampy/device/README.md) for the complete set of deployment options, logger injection, and integration examples.

---

## Usage

All commands follow this pattern:

```bash
otampy [global-options] <command> [command-options]
```

### Global options

| Option              | Description                                                           |
| ------------------- | --------------------------------------------------------------------- |
| `-p`, `--port PORT` | Select the OTA UART adapter (e.g. `/dev/ttyUSB0`, `COM3`).            |
| `-b`, `--baud RATE` | Set the baud rate.                                                    |
| `--log-level LEVEL` | Host CLI logging: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |

The default log level is `ERROR`. When `--log-level` is supplied, the CLI offers to retain the setting permanently (`p`), for the current shell session (`s`), or only for the current command (`c`).

Permanent port settings are stored per project and log-level settings globally
in `~/.config/otampy/config.json`:

```json
{
  "projects": {
    "/path/to/project": {
      "default_port": "/dev/ttyUSB0"
    }
  },
  "global": {
    "log_level": "DEBUG"
  }
}
```

Session-only selections use files in the operating system's temporary directory
(normally `/tmp` on Linux) and do not alter the permanent configuration. On
Windows, they apply to the active Windows logon session. `OTAMPY_PORT` and
`OTAMPY_LOG_LEVEL` environment variables override saved settings.

### Commands

| Command      | Arguments             | Description                                                         |
| ------------ | --------------------- | ------------------------------------------------------------------- |
| `cat`        | `file`                | Print a file from the device.                                       |
| `cp`         | `source[:dest] [...]` | Copy files or folders to the device without rebooting.              |
| `deploy`     | _(see below)_         | Erase and deploy the full device library over USB.                  |
| `device-dir` | —                     | Show or manage the saved project directory for deploy and updates.  |
| `init`       | `[directory]`         | Scaffold `boot.py`, `main.py`, and `configota.py`.                  |
| `log-level`  |                       | Show or manage the saved CLI log level.                             |
| `ls`         | `[path]`              | List device directory contents.                                     |
| `mem`        | —                     | Query device RAM and flash utilisation.                             |
| `ping`       | —                     | Connection health check - should receive PONG.                      |
| `ports`      | —                     | List available serial adapters; mark and store a selection.         |
| `rb`         | `[--set-time]`        | Hard reboot the device (with confirmation).                         |
| `rm`         | `path [...]`          | Remove paths from the device (with confirmation - not recoverable). |
| `rtc`        | —                     | Display the current device RTC timestamp without rebooting.         |
| `sr`         | `[--set-time]`        | MicroPython soft reset (with confirmation).                         |
| `upd`        | `[--set-time] [--all-files] [source[:dest] ...]` | Transactional OTA firmware update.<sup>1</sup>          |

<sup>1</sup> Updates take place after the device has rebooted; the update process is handled by `boot.py`. With no sources specified, `upd` selects `boot.py`, `main.py`, `configota.py`, and all Python files under `lib/` in the saved device directory.

### Deployment Options

| Option                | Effect                                                    |
| --------------------- | --------------------------------------------------------- |
| `-p`, `--port`        | Select the USB/serial device used by `mpremote`.          |
| `--device-dir`        | Select the directory containing `boot.py`, `main.py`, and `configota.py`. |
| `--with-logger`       | Install the optional `log-to-file` package.               |
| `--bytecode`, `--mpy` | Compile OTAmpy and URST into target-matched `.mpy` files. |
| `--mpy-cross`         | Select the `mpy-cross` executable or command.             |
| `--no-mip`            | Install neither URST nor the optional logger.             |
| `--no-reset`          | Leave the board without a final reset.                    |
| `--set-time`          | Set the device RTC from the host during final boot.       |
| `--dry-run`           | Print the complete `mpremote` command without running it. |
| `--mpremote`          | Use a specific `mpremote` executable.                     |

### Common examples

Select a port for subsequent commands (avoids repeating `--port`):

```bash
otampy ports
```

NOTE: The following commands assume you've set the port.

Check device connection health:

```bash
otampy ping
```

List device files:

```bash
otampy ls
otampy ls /lib
```

Query device memory and storage:

```bash
otampy mem
```

Copy files or folders to the device (without reboot):

```bash
otampy cp settings.json:config/settings.json
otampy cp assets:assets/
otampy cp 'device/lib/*:lib/'
```

`cp` accepts multiple sources, folders, and local wildcard patterns (`*`, `?`, `[]`, `**`). Folder contents are copied recursively; empty folders are not created. Files are streamed to checksum-verified staging files and committed individually while the device continues running. Copies targeting root `/boot.py` or `/main.py` produce a reminder that the replacement will take effect on the next restart.

Local `cp` and `upd` source paths are resolved from the project root: `/device/*:/`
copies `<project-root>/device/*` to the device filesystem root. The path after
`:` is always a remote device path.

Remove files or directories (recovery paths are protected):

```bash
otampy rm old.py config.old
otampy rm 'lib/plugins/*.py'
```

Quote wildcards to prevent the host shell from expanding them locally (e.g., `otampy rm '*'`). Prefix an argument with `:` (e.g., `:notes.txt`) or use `--literal-remote-paths` if the filename also exists locally to prevent protection/verification aborts. Removing a non-empty directory requires a confirmation prompt.

To preserve remote recovery, `rm` cannot remove root `/boot.py`, `/main.py`, `/configota.py`, anything under `/lib/otampy` or `/lib/urst`, or an ancestor such as `/lib` or `/`.

Trigger an OTA firmware update (defaults to `boot.py`, `main.py`, `configota.py`, and all `lib/` Python files in the saved device directory):

```bash
otampy upd
```

To update every file in that directory (including non-Python assets), use `--all-files`. OTAmpy lists the files and asks for confirmation before contacting the device:

```bash
otampy upd --all-files
```

Update specific files or mapped paths:

```bash
otampy upd main.py configota.py
otampy upd 'device/lib/something/*.py:lib/something/'
```

Directories include all Python files recursively. Local `*`, `?`, `[]`, and `**` patterns are supported. A pattern matching multiple files must map to a destination ending in `/`. If any source or pattern has no matches, the update stops before contacting the device.

Enable **host-side** diagnostics for a single command:

```bash
otampy --log-level DEBUG ping
```

---

## Device Integration

Call `ota.poll()` in your application loop:

```python
from otampy import OTA
from machine import UART

uart = UART(1, baudrate=9600, tx=Pin(4), rx=Pin(5))
ota = OTA(uart, config=config)

while True:
    ota.poll()
    # ... application logic
```

**Important!** - If your device needs to be set to a safe state before a reboot/reset you can add a callback function to the `ota.poll()` call:

```python
def prepare_for_shutdown():
    # ... application safety logic

while True:
    ota.poll(callback=prepare_for_shutdown)
    # ... application logic
```

This will invoke `prepare_for_shutdown()` before continuing to reboot/reset.

Inject any logger that implements `debug`, `info`, `warning`, `error`, and `critical`:

```python
from log_to_file import Logger
from otampy import OTA

logger = Logger("/logs/ota.log", "some identifier", level="DEBUG")
ota = OTA(uart, config=config, logger=logger)
```

When no logger is provided, `OTA` uses an allocation-light `NullLogger`. `NullLogger` is also importable directly for applications that want an unconditional logger variable:

```python
from otampy import NullLogger
logger = NullLogger()
```

See the [device integration guide](src/otampy/device/README.md) for the full configuration reference.

---

## Contributing

Contributions are welcome. Please follow the process below to keep the codebase consistent and the release gate green.

### Getting started

1. Fork the repository and create a feature branch from `develop`:

   ```bash
   git checkout develop
   git checkout -b feature/your-feature-name
   ```

2. Install the development dependencies:

   ```bash
   uv sync --group dev
   ```

3. Make your changes. Match the existing code style; the project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.

### Running tests

```bash
uv run pytest
```

The test suite requires no connected hardware. Coverage is reported automatically.

Run the linter:

```bash
uv run ruff check .
uv run ruff format --check .
```

### Submitting a pull request

- Target the `develop` branch, not `main`.
- Ensure `ruff check` and `pytest` both pass before opening a PR.
- Describe what the change does, why it is needed, and how it was tested.
- For changes to the device library, note any impact on flash or RAM footprint.
- Keep commits focused and write clear, semantic and scoped commit messages (e.g. `feat(core): add ability to walk on water`).

### Reporting issues

Open a GitHub issue and include:

- A minimal reproduction case.
- The host OS, Python version, and OTAmpy version (`otampy --version`).
- The target board, MicroPython version, and transport (XBee model, direct UART, etc.).
- Any relevant host CLI and/or device logs (For CLI use: `--log-level DEBUG`. For device set `LOG_LEVEL="DEBUG"` in `configota.py`).

### Release process

Releases are cut by maintainers using the automated gate described in the [release guide](docs/releasing.md). Do not build publishable artifacts manually.

---

## Documentation

| Document                                                | Description                                                      |
| ------------------------------------------------------- | ---------------------------------------------------------------- |
| [Deployment guide](docs/deployment.md)                  | All `deploy` options, logging profiles, and bytecode deployment. |
| [Device integration guide](src/otampy/device/README.md) | Device-side setup, logger injection, and runtime file copy.      |
| [Protocol specification](docs/protocol.md)              | URST framing, packet types, and error recovery.                  |
| [Architecture overview](docs/architecture.md)           | Component relationships and design decisions.                    |
| [Release guide](docs/releasing.md)                      | Versioning, the automated release gate, and publishing.          |

---

## License

OTAmpy is released under the [Sustainable Use License](LICENSE.md).

Non-commercial and internal business use is permitted free of charge. Commercial redistribution or monetisation requires a separate commercial licence. Contact [oss@codeability.co.uk](mailto:oss@codeability.co.uk) for commercial licensing enquiries.
