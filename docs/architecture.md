# Architecture Documentation

This document describes the design and software architecture of **OTAmpy** — a reliable, over-the-air (OTA) application update and command interface for MicroPython devices via serial/wireless transports (e.g., XBee modules).

---

## High-Level Architecture Overview

OTAmpy is structured as a monorepo containing two primary src:

```
otampy/
└── src/otampy/        # Host CLI package (Python >= 3.12)
    ├── cli.py         # Click-based command-line interface
    ├── deploy.py      # Deploy command implementation
    └── device/        # MicroPython device library & update engine (runs on device)
```

The host CLI talks to the device over a serial interface running the **Universal Reliable Serial Transport (URST)** protocol.

---

## Device-Side Architecture (Composition & Facade)

To fit inside resource-constrained microcontrollers (like the Raspberry Pi Pico W) while maintaining a clean, DRY (Don't Repeat Yourself) design, the device code is structured around the **Facade** and **Composition** design patterns.

### Component Relationship

The library splits the shared setup/state from the specific execution control flows (boot-time updates vs. runtime loop polling):

```mermaid
classDiagram
    class OTA {
        -OTACore _core
        +boot(callback)
        +poll(callback)
    }

    class OTACore {
        +dict config
        +Urst transport
        +Logger logger
        +UART uart
    }

    class boot {
        +run(OTACore, callback)
    }

    class manager {
        +poll(OTACore, callback)
    }

    class Logger {
        +debug(msg)
        +info(msg)
        +warning(msg)
        +error(msg)
        +critical(msg)
    }

    class NullLogger {
        +int min_level
        +debug(msg)
        +info(msg)
        +warning(msg)
        +error(msg)
        +critical(msg)
    }

    OTA --> OTACore : instantiates
    OTA ..> boot : delegates boot() to
    OTA ..> manager : delegates poll() to
    OTACore --> Logger : injected or no-op
    NullLogger ..|> Logger
```

### Module Responsibilities

| File          | Module/Class            | Description                                                                                                  |
| ------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------ |
| `ota.py`      | `OTA`                   | The public **Facade** class. Exposes a simple interface to developers.                                       |
| `core.py`     | `OTACore`               | Shared state container. Handles UART/URST wrapping, default configuration setups, and logger initialization. |
| `boot.py`     | `run(core, callback)`   | Linear boot-time logic. Checks for the update flag, runs the updater callback, and cleans up the flag.       |
| `manager.py`  | `poll(core, callback)`  | Run-time polling function. Dispatches commands and lazily delegates copy transfers.                          |
| `filecopy.py` | `handle(core, command)` | Lazily loaded staged, checksum-verified runtime copy state machine.                                          |

Applications may inject any logger with the methods shown above. If they do
not, `OTACore` uses the allocation-light `NullLogger`. The example application
selects the optional `log-to-file` logger when installed and otherwise remains
silent. OTAmpy does not import a file-logging module in the production profile.
Runtime copies retain a flat transfer state on `OTACore` only while a copy is
active; file content is written and hashed in bounded chunks rather than held
in RAM.
The host CLI preserves the remote recovery control plane by rejecting a
complete removal selection before sending its first `RM`.
It also rejects arguments matching host filesystem entries unless explicitly
marked as intentional remote path names; no RM path invokes a host deletion
operation.

---

## Integration Guide

Integrating OTAmpy into a MicroPython device requires simple configuration and imports.

### 1. Device Configuration (`configota.py`)

Place a `configota.py` in the root of the device directory containing UART
connection settings. `LOG_LEVEL` and `LOG_FILE` are used by the deployed
examples only when the optional `log-to-file` package is installed:

```python
LOG_LEVEL = "DEBUG"
LOG_FILE = "/ota.log"
OTA_PORT = 1
OTA_TX_PIN = 4
OTA_RX_PIN = 5
OTA_BAUDRATE = 57600
OTA_TIMEOUT_MS = 5000
UPDATE_REQUEST_FLAG_FILE = "update_requested.flag"
```

### 2. Boot-Time Updates (`boot.py`)

During microcontroller boot, check for pending update requests before starting the main application:

```python
import config
from machine import UART, Pin
from otampy import OTA

# Initialize UART
uart = UART(
    config.OTA_PORT,
    baudrate=config.OTA_BAUDRATE,
    tx=Pin(config.OTA_TX_PIN),
    rx=Pin(config.OTA_RX_PIN),
)

# Run boot checker (non-blocking if no update requested)
OTA(uart, config=config).boot()
```

When an update is pending, boot mode accepts `UPDATE_ABORT` and automatically
abandons an inactive transfer after `OTA_TIMEOUT_MS`. Both paths delete staged
`.ota` files, clear the request flag, and continue into the current application.
Staging prevents target replacement before commit, but the current commit is a
per-file rename sequence, not a power-loss-atomic filesystem transaction.

Pass the same injected logger to `OTA` in both scripts if the application
wants logging. Omitting it selects `NullLogger`.

### 3. Application Main Loop (`main.py`)

In the application's runtime loop, run `.poll()` periodically to process remote commands from the host CLI:

```python
import config
import time
from machine import UART, Pin
from otampy import OTA

uart = UART(
    config.OTA_PORT,
    baudrate=config.OTA_BAUDRATE,
    tx=Pin(config.OTA_TX_PIN),
    rx=Pin(config.OTA_RX_PIN),
)

ota = OTA(uart, config=config)

while True:
    # 1. Do application tasks
    read_sensors()

    # 2. Periodically poll for OTA CLI commands
    ota.poll()

    time.sleep(0.1)
```

---

## Test Environment Architecture

Since both the CLI package (`src/otampy`) and the device package (`src/otampy/device`) share the package namespace `otampy`, global test suites (e.g., executing `pytest` at the repository root) could clash within the python `sys.modules` cache.

To achieve complete test isolation:

- `src/otampy/device/tests/conftest.py` runs before the device test modules are collected.
- It dynamically loads the device library into python under the virtual name **`device_otampy`**.
- This registers all device-side code (e.g., `device_otampy.ota`, `device_otampy.core`) independently, leaving the `otampy` namespace clear for the CPython host CLI package.
