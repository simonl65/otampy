# OTAmpy Communication Protocol

This document defines the communication protocol between the OTAmpy Host CLI and the OTAmpy Device library running on MicroPython over the **Universal Reliable Serial Transport (URST)** transport layer.

---

## 1. Protocol Architecture & Framing

```
┌─────────────────────────────────────────────────────────┐
│                   Application Layer                     │
│       Commands & Responses (UTF-8 Colon-Separated)      │
├─────────────────────────────────────────────────────────┤
│                Reliable Transport Layer                 │
│         URST (Packet Delivery / CRC / Retries)          │
├─────────────────────────────────────────────────────────┤
│                    Physical Layer                       │
│               UART Serial Interface (8N1)               │
└─────────────────────────────────────────────────────────┘
```

- **Physical Layer**: Standard UART connection, recommended at `57600` baud rate for XBee modules.
- **Transport Layer (URST)**: Handles frame boundaries, CRC checksums, sequencing, and packet retries. The application layer assumes **guaranteed error-free packet delivery**.
- **Application Layer**: Message payloads are UTF-8 encoded strings formatted as colon-separated fields:
  ```
  COMMAND[:ARG1[:ARG2[:...]]]
  ```

---

## 2. Command & Response Reference

Every request from the Host CLI expects a corresponding response from the Device.

### 2.1 Control Commands

| Request | Response | Description                                         |
| ------- | -------- | --------------------------------------------------- |
| `PING`  | `PONG`   | Connection health check.                            |
| `BL`    | `BL_OK`  | Reboot device into its hardware bootloader.         |
| `RB`    | `RB_OK`  | Trigger a hardware hard reboot (`machine.reset()`). |
| `SR`    | `SR_OK`  | Trigger a soft reboot (`machine.soft_reset()`).     |

### 2.2 File System Commands

| Request     | Response                 | Description                                                          |
| ----------- | ------------------------ | -------------------------------------------------------------------- |
| `LS[:path]` | `LS_OK:[file1,dir2,...]` | List contents of a directory. Returns comma-separated list of items. |
| `CAT:path`  | `CAT_OK:content`         | Read a text file's contents from the device.                         |
| `RM:path`   | `RM_OK`                  | Remove a file or directory from the device.                          |

The official CLI refuses to send `RM` for `/boot.py`, `/main.py`,
`/config.py`, `/lib/otampy`, `/lib/urst`, their descendants, or ancestors
needed to contain them. Use the staged copy or update sequence to replace
those paths. This is a host CLI safety policy; custom clients that issue raw
protocol commands are responsible for applying an equivalent guard.
The CLI's `rm` command maps every accepted argument to this remote `RM`
request and never deletes a host filesystem path.
An optional host-side `:` prefix explicitly marks a remote path and is removed
before the request is sent; for example, `:/logs/old.txt` becomes
`RM:/logs/old.txt`.

### 2.3 Runtime Copy Commands

These commands stream one file to a checksum-verified staging path while the
application continues running. A successful `CP_END` commits the file without
rebooting.

| Request / Msg                   | Response       | Description                                      |
| ------------------------------- | -------------- | ------------------------------------------------ |
| `CP_START:path:size:sha256`      | `CP_READY`     | Start a staged file copy.                        |
| `CP_CHUNK:seq:base64_data`       | `CP_ACK:seq`   | Append one ordered, base64-encoded chunk.        |
| `CP_END`                        | `CP_OK`        | Verify size/checksum and commit the staged file. |
| `CP_ABORT`                      | `CP_ABORTED`   | Close and remove the active staging file.        |
| Any invalid copy request        | `ERROR:reason` | Abort and clean up the active copy where needed. |

### 2.4 Update Sequence Commands

These commands handle the transition from runtime (`main.py`) to bootloader (`boot.py`) and the subsequent file transfer.

| Request / Msg                         | Sender | Response                       | Description                                                                                            |
| ------------------------------------- | ------ | ------------------------------ | ------------------------------------------------------------------------------------------------------ |
| `UPDATE_REQUEST`                      | Host   | `REBOOTING`<br>`BUSY`          | Request device to enter update mode. Device calls application safe callback, sets flag, and reboots.   |
| `READY`                               | Device | (None)                         | Broadcasted by `boot.py` after reboot to signal it is ready for the update payload.                    |
| `UPDATE_START:file_count:total_bytes` | Host   | `SPACE_OK`<br>`SPACE_ERR`      | Initiates the OTA transfer session. Device checks disk space.                                          |
| `FILE_START:path:size:sha256`         | Host   | `FILE_OK`<br>`FILE_ERR`        | Announce upcoming file. Device prepares target path (`path.ota`).                                      |
| `CHUNK:seq:data`                      | Host   | `CHUNK_ACK:seq`<br>`CHUNK_ERR` | Send file chunk of configurable size (e.g., 256/512 bytes).                                            |
| `FILE_END`                            | Host   | `FILE_OK`<br>`FILE_ERR`        | Finalise current file. Device verifies SHA-256 checksum.                                               |
| `UPDATE_COMMIT`                       | Host   | `COMMIT_OK`                    | Complete update. Device renames all `.ota` files, clears flag, and reboots to run the new application. |

---

## 3. Protocol Flow Sequences

### 3.1 Handshake & Diagnostics (`PING`)

```
Host CLI                    Device
   │                           │
   │ ──── PING ──────────────> │
   │ <─── PONG ─────────────── │
   │                           │
```

### 3.2 Directory Listing (`LS`)

```
Host CLI                    Device
   │                           │
   │ ──── LS:/lib ───────────> │
   │ <─── LS_OK:a.py,b.py ──── │ (Or LS_ERR:path_not_found)
   │                           │
```

### 3.3 Runtime File Copy

```
Host CLI                         Device (main.py)
   │                                    │
   │ ── CP_START:path:size:sha256 ────> │ (opens path.cp)
   │ <─ CP_READY ────────────────────── │
   │ ── CP_CHUNK:0:base64_data ───────> │ (writes and hashes)
   │ <─ CP_ACK:0 ────────────────────── │
   │ ── CP_END ───────────────────────> │ (verifies and commits)
   │ <─ CP_OK ───────────────────────── │
   │                                    │ (continues running)
```

### 3.4 Over-The-Air Update Flow (Two-Phase)

The update sequence transitions the device from the active application running in `main.py` to a dedicated update loader running in `boot.py`:

```
Host CLI                           Device (main.py)              Device (boot.py)
   │                                      │                             │
   │ ── UPDATE_REQUEST ─────────────────> │                             │
   │                                      │ (calls safe_callback())     │
   │                                      │ (writes update.flag)        │
   │ <─ REBOOTING ────────────────────────│                             │
   │                                      │ (reboots device)            │
   ▼                                      ▼                             │
   (Waits for device boot)                                              │
   │                                                                    │
   │ <─ READY ───────────────────────────────────────────────────────── │ (Sends READY)
   │                                                                    │
   │ ── UPDATE_START:2:10240 ─────────────────────────────────────────> │ (Checks free space)
   │ <─ SPACE_OK ────────────────────────────────────────────────────── │
   │                                                                    │
   │ ── FILE_START:main.py:5120:sha256 ───────────────────────────────> │ (Creates main.py.ota)
   │ <─ FILE_OK ─────────────────────────────────────────────────────── │
   │                                                                    │
   │ ── CHUNK:0:base64_data ──────────────────────────────────────────> │ (Size is configurable)
   │ <─ CHUNK_ACK:0 ─────────────────────────────────────────────────── │
   │ ── CHUNK:1:base64_data ──────────────────────────────────────────> │
   │ <─ CHUNK_ACK:1 ─────────────────────────────────────────────────── │
   │                                                                    │
   │ ── FILE_END ─────────────────────────────────────────────────────> │ (Verifies checksum)
   │ <─ FILE_OK ─────────────────────────────────────────────────────── │
   │                                                                    │
   │ ── UPDATE_COMMIT ────────────────────────────────────────────────> │ (Renames .ota files,
   │ <─ COMMIT_OK ───────────────────────────────────────────────────── │  clears flag, reboots)
```

During reboot, `boot.py` detects the `update_requested.flag` file, renames the `.ota` files to their final names, removes the flag file, and boots into `main.py`.
