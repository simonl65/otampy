# OTAmpy - Over The Air system for MicroPython

OTAmpy is a lightweight Over-The-Air (OTA) file and system management suite for MicroPython microcontrollers (like Raspberry Pi Pico, ESP32, ESP8266, etc.). It enables robust remote code updates and device control over serial wireless modules (such as XBee) or transparent serial UART connections.

OTAmpy operates on top of the **Universal Reliable Serial Transport (URST)** protocol, ensuring error-free packets, data checking, and automatic recovery even over noisy or high-latency wireless links.

---

## Features

- **Robust OTA Firmware Updates**: Stages incoming `.ota` files on the device filesystem and atomically swaps them upon a successful checksum validation.
- **Interactive File Management**: Upload, download, view (`cat`), or remove (`rm`) files on-device remotely.
- **Hardware Remote Controls**: Remotely trigger hardware reboots (`rb`) or soft resets (`sr`).
- **Telemetry Compatibility**: Safe coexistence of background raw telemetry output streams (ASCII) with on-demand OTAmpy command frames on a single shared UART connection.
- **Fail-Safe Warnings**: Red-colored validation prompts in the CLI before running invasive or destructive commands.
- **Resilient Connectivity**: Smart connection attempts and retries built into the CLI to accommodate sleeping transceivers or high-latency links.
- **Diagnostic Tools**: Simple health checks (`ping`) and detailed memory queries (`mem`) tracking real-time RAM and Flash usage.

---

## Repository Structure

The codebase is split into two packages:

1. **`packages/device/`**: MicroPython firmware running on the microcontroller.
2. **`packages/cli/`**: Python CLI developer tool running on the host computer.

---

## Installation

### 1. Developer CLI Installation

First, ensure you have [UV](https://github.com/astral-sh/uv) installed. Then install the `otampy` command-line utility:

```bash
uv tool install -e packages/cli
```

### 2. Device Firmware Installation

1. Create `packages/device/examples/config.py` from
   `packages/device/examples/config.example.py` and set the UART pins and
   baud rate for your board.
2. Deploy OTAmpy, URST, and the example `boot.py` and `main.py`:

   ```bash
   otampy deploy --port /dev/ttyACM0
   ```

   > [!WARNING]
   > `deploy` erases the device filesystem before copying the deployment.

3. For development file logging, add `--with-logger`. The standard production
   profile does not install a logger and runs silently.
4. Call `ota.poll()` inside your application main loop to enable on-demand
   background listening.

See the [deployment guide](docs/deployment.md) and
[device integration guide](packages/device/README.md) for logger injection,
deployment options, and complete examples.

---

## Usage

Check device health:

```bash
otampy --port /dev/ttyUSB0 ping
```

List files on the device:

```bash
otampy --port /dev/ttyUSB0 ls
```

Query device memory and storage space:

```bash
otampy --port /dev/ttyUSB0 mem
```

Enable host CLI diagnostics for the current command:

```bash
otampy --log-level DEBUG --port /dev/ttyUSB0 ping
```

When `--log-level` is supplied, OTAmpy offers to retain it for the current
shell session or permanently. This host option is separate from device file
logging enabled by `otampy deploy --with-logger`.

Trigger an OTA firmware update:

```bash
otampy --port /dev/ttyUSB0 upd
```

For more options and examples, refer to the [CLI README](packages/cli/README.md).

---

## License

This project is licensed under the [Sustainable Use License](LICENSE.md). Prohibits commercial monetization without a commercial license agreement.
