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
| `SR`    | `SR_OK`  | Trigger a soft reboot (`sys.exit()`).               |

### 2.2 File System Commands

| Request     | Response                 | Description                                                          |
| ----------- | ------------------------ | -------------------------------------------------------------------- |
| `LS[:path]` | `LS_OK:[file1,dir2,...]` | List contents of a directory. Returns comma-separated list of items. |
| `CAT:path`  | `CAT_OK:content`         | Read a text file's contents from the device.                         |
| `RM:path`   | `RM_OK`                  | Remove a file or directory from the device.                          |

### 2.3 Update Sequence Commands

| Request                               | Response                       | Description                                                             |
| ------------------------------------- | ------------------------------ | ----------------------------------------------------------------------- |
| `UPDATE_START:file_count:total_bytes` | `SPACE_OK`<br>`SPACE_ERR`      | Initiates the OTA update session. Device checks disk space.             |
| `FILE_START:path:size:sha256`         | `FILE_OK`<br>`FILE_ERR`        | Announce upcoming file. Device prepares target path (`path.ota`).       |
| `CHUNK:seq:data`                      | `CHUNK_ACK:seq`<br>`CHUNK_ERR` | Send file chunk (base64 encoded or raw bytes).                          |
| `FILE_END`                            | `FILE_OK`<br>`FILE_ERR`        | Finalise current file. Device verifies SHA-256 checksum.                |
| `UPDATE_COMMIT`                       | `COMMIT_OK`                    | Complete update. Device writes `update_requested.flag` and soft-resets. |

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

### 3.3 Over-The-Air Update Flow

The update sequence is structured to be atomic. Files are written with a `.ota` temporary suffix and are only committed (renamed) during the bootloader stage in `boot.py` to prevent corrupting the runtime application if the update is interrupted.

```
Host CLI                                        Device (main.py)
   │                                                   │
   │ ── UPDATE_START:2:10240 (2 files, 10KB total) ──> │
   │ <─ SPACE_OK ───────────────────────────────────── │ (Checks free space)
   │                                                   │
   │ ── FILE_START:main.py:5120:sha256 ──────────────> │ (Creates main.py.ota)
   │ <─ FILE_OK ────────────────────────────────────── │
   │                                                   │
   │ ── CHUNK:0:base64_data ─────────────────────────> │
   │ <─ CHUNK_ACK:0 ────────────────────────────────── │
   │ ── CHUNK:1:base64_data ─────────────────────────> │
   │ <─ CHUNK_ACK:1 ────────────────────────────────── │
   │                                                   │
   │ ── FILE_END ────────────────────────────────────> │ (Verifies checksum)
   │ <─ FILE_OK ────────────────────────────────────── │
   │                                                   │
   │ ── UPDATE_COMMIT ───────────────────────────────> │
   │ <─ COMMIT_OK ──────────────────────────────────── │
   │                                                   │ (Writes update flag & reboots)
```

During reboot, `boot.py` detects the `update_requested.flag` file, renames the `.ota` files to their final names, removes the flag file, and boots into `main.py`.
