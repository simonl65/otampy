# Channel-mux mode: opt-in on both ends — spec

**TODO item:** `[ ] Channel-mux mode: opt-in on both ends.` (top of `TODO.md` → "Tasks in priority order")  
**Status:** approved  
**Components:** `src/otampy/` (host CLI package), `src/otampy/device/` (device library + examples), `docs/`  
**Dev log:** `docs/development/channel-mux-opt-in-log.md` (created by `/sl-build`)

This file specs **sub-task 1 only**. Sub-tasks 2 and 3 get their own specs once 1 lands.

---

## Background (why this task exists)

Commit `6f2bd1b` ("feat(device): add SerialMux and wire it into the example scaffold")
changed the shipped `src/otampy/device/examples/boot.py` and `main.py` to:

```python
mux = SerialMux(uart)
ota = OTA(mux.ota_port, config=config, logger=logger)
```

`OTA` wraps whatever port it is handed in `Urst` (`device/lib/otampy/core.py:53`), so
every URST frame the device emits is now wrapped a second time by
`SerialMux._write_channel` (`device/lib/otampy/mux.py:149-160`) as:

```
COBS_encode( channel_id_byte + inner_URST_frame ) + 0x00
```

The host CLI builds `Urst(serial.Serial(...))` on the **raw** port
(`cli.py:973, 1422, 1829, 2205`) and has no channel layer anywhere
(`grep -n "channel\|mux\|SerialMux" src/otampy/cli.py` → nothing). So:

- **Host → device:** `SerialMux.service()` COBS-decodes the CLI's frame and reads
  `decoded[0]` as the channel id. That is the first byte of a COBS-encoded URST frame,
  always ≥ 1, never `0x00`, so it never matches `_ota_channel` and the frame is
  **silently dropped as an unknown channel**. `ota.poll()` never sees the command.
- **Device → host:** never reached.

Result: `otampy deploy --device-dir src/otampy/device/examples` followed by
`otampy ping` times out with no error, every time.

`docs/architecture.md`'s Integration Guide still shows the pre-`6f2bd1b` direct-mode
examples, so the two docs already disagree about what the scaffold does.

A working host counterpart already exists in another project:
`diff-drive-robot/gateway/src/mux_host.py` (a threaded daemon `SerialMux` whose frame
core is byte-identical to the device `mux.py`). This task ports that frame core — not
the daemon — into `otampy`.

---

## Goal

After sub-task 1: `otampy` contains a documented, tested host-side implementation of the
channel-mux outer frame, and `docs/protocol.md` defines that frame format as an optional
transport layer. Nothing in the CLI or the examples changes yet — `otampy ping` against a
direct-mode device still works, and against a mux-mode device still fails (fixed in
sub-task 2). The observable deliverable is: `uv run pytest -q tests/test_channel.py
tests/test_channel_conformance.py` passes, and `docs/protocol.md` has a "Channel-mux
framing" section.

## In scope

- New `docs/protocol.md` section defining the outer-frame format, channel-id assignment,
  the direct-vs-mux mode decision, and the one-sided-mismatch failure mode.
- New module `src/otampy/channel.py`:
  - `ChannelCodec` — pure encode + stateful deframe of the outer frame.
  - `ChannelSerial` — a synchronous, OTA-channel-only adapter that duck-types the
    serial interface URST's codec layer calls, wrapping a real `serial.Serial`.
- `tests/test_channel.py` — unit coverage of both classes.
- `tests/test_channel_conformance.py` — proves the host encoder/deframer agrees
  byte-for-byte with what the device `mux.py` test helper produces and consumes.

## Out of scope

- **Wiring `ChannelSerial` into the CLI** — sub-task 2. No `--mux` flag, no config key,
  no change to `_query` / the four `Urst(ser)` sites in this sub-task.
- **Changing the example scaffold or `otampy init`** — sub-task 3.
- **Any change to `device/lib/otampy/mux.py`** — the device side already emits the
  format this sub-task documents and matches; touching it risks the existing
  diff-drive-robot deployment for no gain here.
- **Telemetry / channel-1 handling, threading, auto-reconnect, `port_resolver`,
  status callbacks** — `mux_host.py` has these because it is a long-lived daemon; the
  CLI is a short-lived single-command process and does not need them. Explicitly not
  ported.
- **Consolidating `diff-drive-robot`'s `mux_host.py` onto this module** — tracked in
  `diff-drive-robot/TODO.md`, done after `otampy` releases this.

## Protocol decision

- **Existing OTAmpy/URST command reusable?** N/A — this is a framing layer below URST,
  not an application command. URST itself is unchanged and stays channel-unaware.
- **Wire format:** the channel-mux outer frame is **byte-identical** to what
  `device/lib/otampy/mux.py` emits today: `COBS_encode(channel_id ‖ inner) ‖ 0x00`.
  `channel 0x00` = OTA/URST (reliable), `channel 0x01` = application (best-effort),
  unknown channel ids dropped. No change to the bytes on the wire for any existing
  mux-mode user; this sub-task only adds a host implementation and documents the
  format. No `PROTOCOL_VERSION` bump (URST's version is untouched; the mux frame is an
  `otampy` transport option, versioned by `otampy`'s own release).
- **Direct mode stays the default** on both device and CLI. Mux mode is a deliberate
  two-sided choice; a one-sided mismatch produces the silent timeout described in
  Background, and `docs/protocol.md` must say so explicitly (mirroring the auth
  "enable the device last" note).
- **`deploy` stays direct-mode only** (raw-port human provisioning).
- **Signed off:** 2026-09-08 by Simon.

## Data and contracts

### Outer frame — **load-bearing**

```
frame  = COBS_encode( channel_id ‖ payload ) ‖ 0x00
```

- `channel_id`: one byte. `0x00` = OTA/URST, `0x01` = application. Others: dropped on
  receive.
- `payload`: for channel 0, exactly the bytes URST's own codec layer would have
  written to / read from a raw port (its inner COBS frame, delimiters and all — see the
  conformance test; do **not** hand-derive whether the inner frame carries a leading
  `0x00`).
- COBS: `urst.codec_layer.cobs_encode` / `cobs_decode` — the same implementation the
  device `mux.py` imports (`device/tests/test_mux.py::test_mux_uses_urst_cobs_implementation`).
- `0x00` is the outer frame delimiter. A run of frames relies on each frame's trailing
  delimiter; a leading delimiter is tolerated (empty frame between two `0x00`s is
  skipped), matching `mux.py:189` and `urst/codec_layer.py:246-248`.

### Named constants (in `src/otampy/channel.py`)

| Constant | Value | Mirrors |
| --- | --- | --- |
| `OTA_CHANNEL` | `0x00` | `mux.DEFAULT_OTA_CHANNEL`, `mux_host.CHANNEL_OTA` |
| `APP_CHANNEL` | `0x01` | `mux.DEFAULT_APP_CHANNEL`, `mux_host.CHANNEL_TELEMETRY` |
| `FRAME_DELIM` | `b"\x00"` | `mux._FRAME_DELIM_BYTES` |
| `MAX_OUTER_FRAME_BYTES` | `1024` | `mux.MAX_OUTER_FRAME_BYTES` |
| `OTA_BUFFER_BYTES` | `2048` | `mux.OTA_BUFFER_BYTES` |
| `DEFAULT_MIN_TX_GAP_MS` | `0` | `mux` / `mux_host` default |

No new entry in a config-reference doc for sub-task 1 (nothing is user-configurable
until the CLI flag lands in sub-task 2). Note in the log that sub-task 2 must document
`--mux` and the channel-id / `min_tx_gap_ms` settings.

### `ChannelCodec`

- `encode(channel_id: int, payload: bytes) -> bytes` — one outer frame.
- `feed(data: bytes) -> None` — append raw received bytes to an internal buffer.
- `frames() -> Iterator[tuple[int, bytes]]` — yield `(channel_id, payload)` for every
  complete, valid outer frame currently buffered; consume them from the buffer.
  Corrupt COBS → drop that frame, resync on the next `0x00` (increment a
  `frames_dropped` counter). Frame longer than `MAX_OUTER_FRAME_BYTES` → drop. Buffer
  exceeding `MAX_OUTER_FRAME_BYTES` with no delimiter → clear (resync).
- `reset() -> None` — discard the internal buffer.

### `ChannelSerial` — **load-bearing** (URST depends on this shape)

Wraps a serial-like object (`self._ser`) and a `ChannelCodec`. Surfaces only
channel 0. Methods/attrs URST's codec layer and the CLI touch (verified against
`urst/codec_layer.py:196-223,256-263` and `cli.py:967-972`):

| Member | Behaviour |
| --- | --- |
| `write(data: bytes) -> int` | `self._ser.write(codec.encode(OTA_CHANNEL, data))`; if `min_tx_gap_ms`, sleep the remaining gap first, measured from the previous write's `flush()` return. Returns `len(data)` (the count URST expects, not the framed length). |
| `flush()` | delegate to `self._ser.flush()`. |
| `read(n: int = 1) -> bytes` | pump: `self._ser.read(self._ser.in_waiting or 1)` → `codec.feed(...)` → drain `codec.frames()`, appending channel-0 payloads to an internal decoded buffer (bounded by `OTA_BUFFER_BYTES`, oldest dropped on overflow). Return up to `n` bytes from that buffer; `b""` if empty. |
| `in_waiting` (property) | length of the internal **decoded** channel-0 buffer (not raw serial bytes) — so URST's `read(in_waiting)` asks for a count it can actually get. Pumps first, like `_VirtualPort.any()`. |
| `reset_input_buffer()` | `self._ser.reset_input_buffer()`, `codec.reset()`, clear the decoded buffer. |
| `reset_output_buffer()` | delegate. |
| `close()` | delegate. |

`dtr` / `rts` are set by the CLI on the raw `serial.Serial` before it is wrapped
(sub-task 2 concern) — `ChannelSerial` does not need them.

Single-threaded and synchronous by design — no locks (unlike `mux_host._VirtualPort`).

## Build steps

- [x] **1. Document the channel-mux frame in `docs/protocol.md`**
  - What changes: new section (e.g. `## 1.3 Channel-mux framing (optional)`) after the
    existing §1.1 "Sharing the UART with application code". Define the outer frame,
    `channel 0x00` / `0x01`, that direct mode (no outer frame) is the default on both
    ends, that mux mode must be enabled on **both** ends, and that a one-sided mismatch
    presents as a silent command timeout. Update the §1 architecture diagram to show
    the optional layer. Add a one-line pointer from §1.1 to the new section. Fix the
    stale claim in §1.1 that "the shipped `boot.py`/`main.py` examples use" the mux
    (they will not, after sub-task 3 — word it as "the shared-UART example set uses").
  - Test: none — documentation.
  - Done when: the section exists, describes the exact byte format in the Data and
    contracts table above, and Simon has read it at the review gate.

- [ ] **2. `ChannelCodec` in `src/otampy/channel.py`**
  - What changes: new `src/otampy/channel.py` with the module constants and
    `ChannelCodec` (`encode`, `feed`, `frames`, `reset`, `frames_dropped`). Imports
    `cobs_encode` / `cobs_decode` from `urst.codec_layer`.
  - Test: `tests/test_channel.py::TestChannelCodec` — round-trip `encode`→`feed`→
    `frames`; a frame delivered one byte at a time across many `feed` calls; two frames
    (channels 0 and 1) in one `feed`, both yielded with correct ids; a corrupt-COBS
    frame dropped and the following good frame still yielded (`frames_dropped == 1`); an
    over-long frame dropped; a delimiter-free buffer past `MAX_OUTER_FRAME_BYTES`
    cleared.
  - Done when: `uv run pytest -q tests/test_channel.py::TestChannelCodec` passes.

- [ ] **3. `ChannelSerial` in `src/otampy/channel.py`**
  - What changes: add `ChannelSerial` (table above) to the same module.
  - Test: `tests/test_channel.py::TestChannelSerial` against a fake serial —
    `write` puts a correctly framed channel-0 frame on the fake; `read` returns only
    decoded channel-0 payload and ignores an interleaved channel-1 frame; `in_waiting`
    reports decoded-byte count and pumps; `reset_input_buffer` clears a half-received
    frame so the next frame still decodes; with `min_tx_gap_ms=20` a second `write`
    within 20 ms sleeps the remainder and one after 20 ms does not (patch the clock).
    Plus `TestChannelSerial::test_urst_roundtrip`: `Urst(ChannelSerial(fake))` completes
    a `PING`→`PONG` exchange where the fake is primed with the mux-framed `PONG`
    response (canned bytes from step 4's helper).
  - Done when: `uv run pytest -q tests/test_channel.py` passes.

- [ ] **4. Cross-implementation conformance test**
  - What changes: `tests/test_channel_conformance.py`. Reuse the exact frame the device
    suite builds — replicate `device/tests/test_mux.py::outer_frame(channel, payload)`
    (or import the constant bytes) and assert:
    (a) `ChannelCodec().encode(OTA_CHANNEL, inner) == outer_frame(0x00, inner)` for a
    representative `inner` (e.g. `b"\x00URST\x00"` and a 200-byte payload with embedded
    zeros);
    (b) feeding `outer_frame(0x00, inner)` to `ChannelCodec` yields `(0x00, inner)`;
    (c) feeding `outer_frame(0x01, b"...")` yields `(0x01, ...)` and a channel-99 frame
    yields nothing.
  - Test: this step *is* the test.
  - Done when: `uv run pytest -q tests/test_channel_conformance.py` passes, with the
    assertions comparing concrete byte sequences (not re-derived through the same code
    path on both sides).

## Verification

- **Host:** `python3 .agents/scripts/pre_flight_check.py` (mirrors CI: `ruff check`,
  `ruff format`, full `pytest`). Per-step: `uv run pytest -q tests/test_channel.py
  tests/test_channel_conformance.py`.
- **Hardware:** none for sub-task 1 — no code path reaches a device until sub-task 2
  wires the CLI. State this explicitly in the log so it is not mistaken for a skipped
  check.
- **Manual:** Simon runs `uv run pytest -q tests/test_channel*.py` and reads the new
  `docs/protocol.md` section.

## Risks and open questions

- **Inner-frame byte layout.** Whether URST's inner frame carries a leading `0x00` is
  not assumed anywhere in this spec — step 4's conformance test pins host↔device
  agreement against concrete bytes. If step 4 reveals `mux_host.py` and `mux.py`
  themselves disagree with current URST output, stop and raise it (it would mean
  diff-drive-robot is relying on incidental behaviour).
- **`in_waiting` semantics.** URST's codec does `bytes_to_read = max(1, self.ser.in_waiting)`
  then `self.ser.read(bytes_to_read)` (`codec_layer.py:256-263`). `ChannelSerial.in_waiting`
  must therefore mean "decoded channel-0 bytes available", or URST can spin. Covered by
  `TestChannelSerial`, but flag it in review.
- **Namespace isolation in the conformance test.** `src/otampy/device/tests/conftest.py`
  loads the device lib as `device_otampy` and keeps the `otampy` namespace clear.
  `tests/test_channel_conformance.py` lives in the **host** `tests/` dir and must not
  depend on `device_otampy` — hence "replicate or hard-code the frame bytes" rather
  than importing the device helper. Confirm the host test run does not pull in the
  device conftest.
- **`reset_input_buffer` call site.** The CLI currently calls it on the raw `ser`
  before constructing `Urst` (`cli.py:971`). Sub-task 2 must move that call onto the
  `ChannelSerial` wrapper (or call both) so the deframer is also cleared between retry
  attempts — note for the sub-task 2 spec, not actioned here.
- **`mux.py:179` `while True:`** is an open deferred NASA-review item (`TODO.md`).
  `ChannelCodec.frames()` must not reproduce that pattern — it iterates the buffer with
  a bounded loop (no delimiter → return) and is covered by the over-long / no-delimiter
  tests.

## Notes for the build

- `mux_host.py`'s frame core is the reference: `_write_channel` (encode) and
  `_process_chunk` (deframe + route) — port the logic, drop the threading, the
  `telemetry_queue`, `_reconnect`, `port_resolver` and `_on_status`.
- Keep `ChannelCodec` free of any serial/IO — it is pure bytes-in/bytes-out so the
  conformance test and future reuse (diff-drive-robot) stay simple.
- `.agents/AGENTS.md`: TDD (test in the same step's diff), no magic numbers (constants
  table above), DRY (import COBS from `urst`, do not re-implement).
- After this sub-task, update `TODO.md` sub-task 1's checkbox and record the resolved
  inner-frame layout question in the dev log for sub-task 2 to build on.
