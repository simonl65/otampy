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
│           Channel-mux Framing (optional — §1.3)         │
│      COBS(channel_id ‖ URST frame) — off by default      │
├─────────────────────────────────────────────────────────┤
│                    Physical Layer                       │
│               UART Serial Interface (8N1)               │
└─────────────────────────────────────────────────────────┘
```

- **Physical Layer**: Standard UART connection, recommended at `57600` baud rate for XBee modules.
- **Transport Layer (URST)**: Handles frame boundaries, CRC checksums, sequencing, and packet retries. The application layer assumes **guaranteed error-free packet delivery**. URST is point-to-point and channel-unaware.
- **Channel-mux Framing (optional)**: An extra outer frame that lets one UART carry URST traffic alongside the project's own application stream. **Absent by default** — see §1.3. When enabled it must be enabled on **both** ends.
- **Application Layer**: Message payloads are UTF-8 encoded strings formatted as colon-separated fields:
  ```
  COMMAND[:ARG1[:ARG2[:...]]]
  ```

### 1.1 Sharing the UART with application code

If your project's own code needs the same physical UART OTAmpy is using
(e.g. a control/telemetry stream sharing one radio link), do **not** call
`uart.read()`/`uart.write()` directly anywhere outside of `OTA(...)`. Both
sides read the same buffer, so whichever one calls `read()` first on a
given loop tick silently steals the other's bytes -- most commonly this
shows up as OTAmpy handshakes/commands timing out with no error, because
the CONNECT or command frame never reached URST.

Use `otampy.mux.SerialMux` to split one UART into isolated channels:

```python
from otampy.mux import SerialMux

mux = SerialMux(uart)
ota = OTA(mux.ota_port, config=config, logger=logger)

# elsewhere in your loop, instead of uart.read()/uart.write():
mux.service()             # pump the real UART -- call every loop tick
mux.send_app(payload)      # write on your application's channel
data = mux.poll_app()      # newest pending payload on your channel, or None
```

This is the pattern the shared-UART example set uses — scaffold it with
`otampy init --mux` (the default `otampy init` is direct mode). It changes
the bytes on the wire (see §1.3), so the host CLI must be told to speak the
same framing — a mux device paired with a plain-URST host times out silently.

### 1.2 Authenticated commands (optional)

The command surface in section 2 is reachable by anything that can reach
the device's UART. On a wired link that is the same trust boundary as
physical access, but on a radio link -- where OTAmpy is most useful -- it
means any station in range can read, overwrite, delete or reboot the
device with no credential.

Setting `OTA_REQUIRE_AUTH = True` in `configota.py` makes the device
require every command to arrive inside a signed envelope:

```text
AUTH:<counter>:<hex-mac>:<original command>
```

| Field | Meaning |
| --- | --- |
| `counter` | Host-issued, strictly increasing. Replay protection. |
| `hex-mac` | `HMAC-SHA256(key, b"otampy-ch0\x00" + counter + b":" + command)`, truncated to 8 bytes and hex-encoded. |
| `original command` | Any command from section 2, unchanged -- colons and all. |

The device verifies the MAC, then checks the counter is strictly greater
than the highest it has already accepted, then dispatches the inner
command through the ordinary parser. A command that fails either check is
answered with `ERROR:Unauthenticated` or `ERROR:Replayed` and is never
dispatched.

The host signs when `OTAMPY_COMMAND_AUTH_KEY` is set in the environment;
it must be the same 64 hex characters as the device's `COMMAND_AUTH_KEY`.
A fresh counter is issued per send attempt, so the CLI's own retries are
not mistaken for replays.

**Defaults are unchanged.** With `OTA_REQUIRE_AUTH` unset the device
accepts bare commands exactly as before, and with no
`OTAMPY_COMMAND_AUTH_KEY` the CLI sends them. Enabling this is a
deliberate, two-sided act.

**Enable the device last.** A device that requires authentication will
reject a CLI that is not yet configured to sign, and recovery is over
USB. Set `OTAMPY_COMMAND_AUTH_KEY` on the host, confirm a signed command
works, and only then set `OTA_REQUIRE_AUTH = True` on the device.

Related settings:

| Setting | Where | Default | Meaning |
| --- | --- | --- | --- |
| `OTA_REQUIRE_AUTH` | `configota.py` | `False` | Require the envelope. With no usable key, rejects everything. |
| `COMMAND_AUTH_KEY` | `configota.py` | unset | 64 hex characters (32 bytes). |
| `OTA_REPLAY_FLOOR_FILE` | `configota.py` | `otampy-replay-floor` | Where the counter is saved before a commanded reset, so a captured `RB` cannot be replayed afterwards. |
| `OTA_ALLOWED_PATH_PREFIXES` | `configota.py` | unset (all) | Restrict `CP_START`/`CAT`/`RM` targets. `..` is always refused, configured or not. |
| `OTAMPY_COMMAND_AUTH_KEY` | host env | unset | The host's copy of the key. Unset means send bare commands. |
| `OTAMPY_COUNTER_FILE` | host env | `~/.local/state/otampy/command-counter` | Where the host's counter persists across runs. |

### 1.3 Channel-mux framing (optional)

By **default there is no outer frame**: URST frames go straight onto the
UART, and this is what the CLI and the default `otampy init` scaffold both
do. You only need this section if your project shares the UART with its own
traffic via `otampy.mux.SerialMux` (the `otampy init --mux` scaffold, §1.1).

When mux mode is used, every URST frame is wrapped in one outer frame:

```
frame  = COBS_encode( channel_id ‖ payload ) ‖ 0x00
```

| Element | Meaning |
| --- | --- |
| `channel_id` | One byte. `0x00` = OTA/URST (reliable). `0x01` = application stream (best-effort). Other ids are **dropped on receive**. |
| `payload` | For channel `0x00`, exactly the bytes URST would otherwise have written to / read from the raw UART — its own inner COBS frame, delimiters included, untouched. |
| `COBS_encode` | The same implementation URST uses internally (`urst.codec_layer.cobs_encode` / `cobs_decode`). |
| `0x00` | Outer-frame delimiter. A leading/empty delimiter between frames is tolerated (the empty frame is skipped). |

Channel ids are configurable on both ends but **must match**. The reference
values live in named constants — device: `mux.DEFAULT_OTA_CHANNEL` /
`DEFAULT_APP_CHANNEL`; host: `otampy.channel.OTA_CHANNEL` / `APP_CHANNEL`
(both `0x00` / `0x01`). A receiver drops any outer frame that fails COBS
decode (resyncing on the next `0x00`), exceeds `MAX_OUTER_FRAME_BYTES`
(1024), or names an unknown channel.

**Mux mode is a deliberate two-sided choice.** Direct mode (no outer frame)
is the default on both the device and the CLI. If only one end uses the
outer frame, every command — including `PING` — **times out with no error**:
the plain-URST end reads the other end's COBS/channel byte as the start of a
URST frame, never completes it, and never replies. This mirrors the "enable
the device last" caution for authenticated commands (§1.2): bring the two
ends into agreement deliberately, and verify with a `PING` before relying on
it.

`deploy` (raw-port provisioning) is always direct mode.

This outer frame is an `otampy` transport option, versioned by `otampy`'s
own releases. It does not change URST's `PROTOCOL_VERSION` — URST itself is
unchanged and stays channel-unaware.

**Enabling mux mode on the host.** The CLI is direct by default. Turn the
outer frame on with the `--mux` flag for a single command, or save it:

| Setting | Where | Default | Meaning |
| --- | --- | --- | --- |
| `--mux` / `--no-mux` | CLI option (before the subcommand) | off | Force mux / direct for this one command, ignoring the saved setting. |
| `OTAMPY_MUX` | host env | unset | `1`/`true`/`yes`/`on` or `0`/`false`/`no`/`off`. Overrides the saved setting. |
| `mux` | `~/.config/otampy/config.json` (project, then global) | unset | Persistent default. Set with `otampy mux --enable` / `--disable` / `--clear`, or the interactive `otampy mux`. |

Resolution order: `OTAMPY_MUX` → session config → project config → global
config → direct. `otampy mux --show` prints the resolved value and where it
came from. `deploy` ignores all of the above. The device must be running
`otampy.mux.SerialMux` (§1.1) for any of this to connect — a `--mux` CLI
against a direct device is the one-sided mismatch above.

---

## 2. Command & Response Reference

Every request from the Host CLI expects a corresponding response from the Device.

### 2.1 Control Commands

| Request | Response                                                              | Description                                                                            |
| ------- | --------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `PING`  | `PONG`                                                                | Connection health check.                                                               |
| `RTC`   | `RTC_OK:(year, month, day, weekday, hour, minute, second, subsecond)` | Return the raw RTC tuple without resetting the device. The CLI formats it for display. |
| `RB`    | `RB_OK`                                                               | Trigger a hardware hard reboot (`machine.reset()`).                                    |
| `SR`    | `SR_OK`                                                               | Trigger a soft reboot (`machine.soft_reset()`).                                        |
| `CONFIRM` | `CONFIRM_OK`<br>`CONFIRM_ERR` | Take the running update candidate off trial (stop auto-rollback). Idempotent. `CONFIRM_ERR` only when a commit marker is still present. See §2.4. |
| `UPDATE_STATE` | `STATE_OK:<trial\|stable>:<attempt>` | Read-only. Report whether the running build is on trial (with the boot count) or confirmed/stable (`0`). |

### 2.2 File System Commands

| Request     | Response                 | Description                                                          |
| ----------- | ------------------------ | -------------------------------------------------------------------- |
| `LS[:path]` | `LS_OK:[file1,dir2,...]` | List contents of a directory. Returns comma-separated list of items. |
| `CAT:path` | `CAT_OK:bytes` | Read a fixed-size file snapshot through one reliably fragmented URST response. |
| `RM:path`   | `RM_OK`                  | Remove a file or directory from the device.                          |

The official CLI refuses to send `RM` for `/boot.py`, `/main.py`,
`/configota.py`, `/lib/otampy`, `/lib/urst`, their descendants, or ancestors
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

| Request / Msg               | Response       | Description                                      |
| --------------------------- | -------------- | ------------------------------------------------ |
| `CP_START:path:size:sha256` | `CP_READY`     | Start a staged file copy.                        |
| `CP_CHUNK:seq:base64_data`  | `CP_ACK:seq`   | Append one ordered, base64-encoded chunk.        |
| `CP_END`                    | `CP_OK`        | Verify size/checksum and commit the staged file. |
| `CP_ABORT`                  | `CP_ABORTED`   | Close and remove the active staging file.        |
| Any invalid copy request    | `ERROR:reason` | Abort and clean up the active copy where needed. |

### 2.4 Update Sequence Commands

These commands handle the transition from runtime (`main.py`) to bootloader (`boot.py`) and the subsequent file transfer.

| Request / Msg                         | Sender | Response                       | Description                                                                                                                         |
| ------------------------------------- | ------ | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| `UPDATE_REQUEST`                      | Host   | `REBOOTING`<br>`BUSY`          | Request device to enter update mode. Device calls application safe callback, sets flag, and reboots.                                |
| `READY`                               | Device | (None)                         | Broadcasted by `boot.py` after reboot to signal it is ready for the update payload.                                                 |
| `UPDATE_START:file_count:total_bytes` | Host   | `SPACE_OK`<br>`SPACE_ERR`      | Initiates the OTA transfer session. Device discards the previously retained generation (journal + `.bck` files), then checks disk space. |
| `FILE_START:path:size:sha256`         | Host   | `FILE_OK`<br>`FILE_ERR`        | Announce upcoming file. Device prepares target path (`path.ota`).                                                                   |
| `CHUNK:seq:data`                      | Host   | `CHUNK_ACK:seq`<br>`CHUNK_ERR` | Send a file chunk. OTAmpy defaults to 128 raw bytes and caps chunks at 132 bytes so the encoded message fits in one URST frame.     |
| `FILE_END`                            | Host   | `FILE_OK`<br>`FILE_ERR`        | Finalise current file. Device verifies SHA-256 checksum.                                                                            |
| `UPDATE_ABORT`                        | Host   | `UPDATE_ABORTED`               | Cancel before commit. Device closes the active file, removes session staging files and the update flag, then continues normal boot. |
| `UPDATE_COMMIT`                       | Host   | `COMMIT_OK`<br>`COMMIT_ERR`    | Complete update. All-or-nothing: device renames each target to `<target>.bck`, moves the `.ota` into place, and writes `OTA_JOURNAL_FILE`. On any failure the whole set is rolled back from `.bck` and `COMMIT_ERR` is returned. Then clears flag and reboots. |
| `CONFIRM`                             | Host / app | `CONFIRM_OK`<br>`CONFIRM_ERR` | Take the just-committed candidate off trial. See the trial-boot lifecycle below. |
| `UPDATE_STATE`                        | Host   | `STATE_OK:<trial\|stable>:<attempt>` | Read-only trial-state query. |

#### Trial boot, confirmation, and auto-restore

A committed update is **on trial**, not immediately permanent. `boot.py`
counts every boot into an unconfirmed candidate in the retain-previous
journal (line 1 holds the base-10 count). Once the count passes
`OTA_TRIAL_BOOTS` (default `3`) the device restores the entire previous
generation from its `.bck` files and reboots onto it, with no host
involvement. The auto-restore trigger is therefore **a reboot during the
trial window** — a crash to reset, a panic, a brownout, the application's
watchdog firing, or a manual power cycle. A candidate that hangs without
resetting is *not* auto-restored; run `otampy rollback` (planned) or use the
boot-time recovery window. Applications are expected to run their own
watchdog, which supplies the reset.

A candidate leaves trial when:

- the host sends `CONFIRM` — `otampy upd` does this automatically after a
  post-reboot `PING` unless `--no-confirm` is given; or
- the application calls `ota.confirm()` after its own health check.

Confirming flips journal line 1 to `confirmed` and **only stops the counter**.
It does not delete the retained `.bck` set — the previous generation stays
recoverable until the next update's `UPDATE_START` clears it. `CONFIRM` is
idempotent and returns `CONFIRM_ERR` only if a commit marker is still present
(a commit is mid-flight).

`CONFIRM` after `PING` is a shallow check: it proves the poll loop is
reachable, not that the application logic is correct. A candidate that
answers `PING` then misbehaves is already confirmed.

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
   │ ── UPDATE_COMMIT ────────────────────────────────────────────────> │ (Retains .bck, renames
   │ <─ COMMIT_OK ───────────────────────────────────────────────────── │  .ota in, clears flag, reboots)
```

Before `UPDATE_COMMIT`, staged files never replace their targets. If the CLI detects a transfer error or is interrupted, it sends `UPDATE_ABORT`; the device discards the staged files and continues its normal boot. If the link is unavailable, `boot.py` performs the same recovery after `OTA_TIMEOUT_MS` without a packet (5 seconds by default).

`UPDATE_COMMIT` is all-or-nothing. Before the first rename the device writes
`OTA_JOURNAL_FILE` with a `committing` marker and the target list, renames each
target to `<target>.bck` and the staged `.ota` into place, then flips the marker
to `0` — the start of the trial-boot count. If a rename fails, the whole set is
rolled back from the `.bck` files and `COMMIT_ERR` is returned — the device
stays entirely on the previous generation. If power is lost mid-commit, the
marker survives and `boot.py`'s `repair()` restores every journalled `.bck` on
the next boot. The device is therefore never left on a mixed-version tree
within a single commit.

`COMMIT_OK` does **not** make the update permanent — the candidate is on
trial until `CONFIRM` (or `ota.confirm()`), and a reboot before then
auto-restores the previous generation once the boot count passes
`OTA_TRIAL_BOOTS`. See §2.4.

This is still a sequence of ordinary `rename` calls, not one filesystem-atomic
transaction: recovery is best-effort and converges over reboots. A hard
power-loss-atomic guarantee needs a dual-slot deployment layout. `OTA_JOURNAL_FILE`
must point at a dedicated scratch path, never a real source file.

`UPDATE_START` discards the previously retained generation (its journal and
`.bck` files), so at most one previous generation is kept for manual recovery.
