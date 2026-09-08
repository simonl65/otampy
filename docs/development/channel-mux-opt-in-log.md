# Channel-mux mode: opt-in on both ends — dev log

Spec: `docs/development/channel-mux-opt-in-spec.md` (sub-task 1 only).
Branch: `feature/channel-mux-opt-in`.

## Context established at start

- `otampy` depends on `urst-mpy>=3.0.0`; the installed `urst` package is that
  MicroPython lib running on desktop CPython via its shims. `urst.codec_layer`
  exports `cobs_encode` / `cobs_decode` — the same implementation the device
  `mux.py` imports.
- The reference `diff-drive-robot/gateway/src/mux_host.py` named in the spec is
  **not present / empty** in this checkout. Frame core is instead ported from the
  device `src/otampy/device/lib/otampy/mux.py` (`_write_channel` = encode,
  `service()` = deframe), which the spec confirms is byte-identical.
- URST's codec layer (`CodecLayer.write_frame` / `read_frame`,
  `.venv/.../urst/codec_layer.py:222-270`) calls on its serial object:
  `write(frame)` then `flush()` (if present); `in_waiting` (property) →
  `read(max(1, in_waiting))`. The CLI additionally calls `reset_input_buffer()`,
  `reset_output_buffer()`, and sets `dtr` / `rts` on the raw port before wrapping
  (`cli.py:965-972`).
- Baseline test suite: `459 passed` (`uv run pytest -q`).
- **Hardware: no HIL evidence for sub-task 1 by design** — no code path reaches a
  device until sub-task 2 wires the CLI. Host tests are the whole gate.

## Progress

### Step 1 — document the channel-mux frame in `docs/protocol.md` — DONE

- Added §1.3 "Channel-mux framing (optional)" after §1.2, defining the outer
  frame `COBS_encode(channel_id ‖ payload) ‖ 0x00`, the `0x00`/`0x01` channel
  ids, direct mode as the both-ends default, the two-sided-choice rule, and the
  silent-timeout one-sided-mismatch failure mode.
- Updated the §1 layer diagram to show the optional channel-mux layer and added
  a bullet under it.
- Reworded the stale §1.1 claim ("the shipped `boot.py`/`main.py` examples use")
  to "the shared-UART example set uses", with a pointer to §1.3.
- Numbered it 1.3 (after 1.2) rather than inserting between 1.1 and 1.2 to keep
  section numbering monotonic — spec said "after §1.1 … number it 1.3", which is
  contradictory; chose monotonic ordering.

**Note for sub-task 2:** must document the `--mux` flag, the `otampy.toml` key,
and the channel-id / `min_tx_gap_ms` settings — §1.3 currently documents the
wire format only, nothing user-configurable.

**Pre-flight friction:** `python3 .agents/scripts/pre_flight_check.py` runs
`ruff format .` which reformats 6 pre-existing files unrelated to this task
(`src/otampy/auth.py`, `device/lib/otampy/manager.py`, and 4 device test files)
and auto-stages them. Reverted those; they are pre-existing formatting drift and
want their own commit, not bundling into this feature. Flagged to Simon.

### Step 2 — `ChannelCodec` in `src/otampy/channel.py` — DONE

- New `src/otampy/channel.py`: module constants (`OTA_CHANNEL`, `APP_CHANNEL`,
  `FRAME_DELIM`, `MAX_OUTER_FRAME_BYTES`, `OTA_BUFFER_BYTES`,
  `DEFAULT_MIN_TX_GAP_MS`) + `ChannelCodec` (`encode`, `feed`, `frames`,
  `reset`, `frames_dropped`). Imports `cobs_encode` / `cobs_decode` from
  `urst.codec_layer` (`# type: ignore`, matching device `mux.py`).
- `frames()` is a bounded generator — no `while True` (spec risk note re
  `mux.py:179`). Each pass consumes ≥1 delimiter from a finite buffer and
  returns as soon as `find(FRAME_DELIM)` fails; the no-delimiter overflow clear
  runs after the loop.
- Deframe logic ported from device `mux.py::service()`; encode from
  `_write_channel`.
- `tests/test_channel.py::TestChannelCodec` — 9 tests, all green. Reference
  frame `_outer()` built independently of `ChannelCodec.encode` so the
  round-trip tests aren't circular.
- Gate: `pre_flight_check.py` exit 0; `uv run pytest -q tests/test_channel.py`
  → 9 passed.

### Step 3 — `ChannelSerial` in `src/otampy/channel.py` — DONE

- Added `ChannelSerial(ser, codec=None, min_tx_gap_ms=0)`: `write` (frames on
  `OTA_CHANNEL`, returns `len(data)`), `flush` (delegates + records the
  last-write timestamp), `read`/`in_waiting` (pump raw → `codec.feed` →
  drain `codec.frames()` → decoded channel-0 buffer bounded by
  `OTA_BUFFER_BYTES`), `reset_input_buffer` (raw reset + `codec.reset()` +
  clear decoded), `reset_output_buffer`/`close` (delegate).
- `min_tx_gap_ms` gap is measured from the previous **`flush()`** return
  (matches URST `write_frame` = write-then-flush). No flush ⇒ no gap
  enforcement — documented in the class.
- Module `_now_ms` / `_sleep_ms` are the monkeypatch seams for the gap test
  (mirrors device `mux._ticks_ms` / `_sleep_ms`).
- `tests/test_channel.py::TestChannelSerial` (7) + `TestChannelSerialUrstRoundtrip`
  (1). Roundtrip uses a **thread-based dual real-`Urst` loopback** over an
  in-memory cross-pipe, both ends wrapped in `ChannelSerial`: `host.send(b"PING")`
  / background `dev.read()`+`dev.reply(b"PONG")` / `host.read()` → `b"PONG"`.
  This exercises the real URST CONNECT handshake + reliable ACKs through the
  mux frame in both directions — stronger than priming canned bytes, and it
  sidesteps hand-deriving the inner-frame layout.
- **`from urst import Urst` is shadowed** by the device-test conftest's
  `FakeUrst` once the device suite is collected (`sys.modules["urst"]` swap).
  The real class is still reachable as `from urst.core_handler import Urst`
  (that submodule is not swapped) — the roundtrip test uses that, with a
  comment.

### Step 4 — cross-implementation conformance test — DONE

- `tests/test_channel_conformance.py` (4 tests). Replicates device
  `test_mux.py::outer_frame` and pins it against **hard-coded byte sequences**
  captured once (`010105555253540100` for `outer_frame(0x00, b"\x00URST\x00")`),
  so a COBS/framing drift on either side is a byte mismatch, not a hidden
  shared-path pass.
  - (a) `ChannelCodec().encode(0x00, inner) == outer_frame(0x00, inner)` for
    `b"\x00URST\x00"` and a 768-byte payload full of embedded `0x00`.
  - (b) feeding `outer_frame(0x00, inner)` yields `(0x00, inner)`.
  - (c) `outer_frame(0x01, …)` yields `(0x01, …)`; a channel-99 frame yields
    nothing.
- Does **not** import `device_otampy` — host `tests/` only. Confirmed the host
  `tests/` run does not depend on the device conftest for these
  (`uv run pytest -q tests/test_channel*.py` passes standalone: 22 tests;
  full suite 481 passed).

### RESOLVED — inner-frame byte layout (for sub-task 2)

The spec's open question: does URST's inner frame carry a leading `0x00`?
**Answer: it does not need hand-deriving and sub-task 2 must not assume either
way.** `ChannelSerial` treats channel-0 payload as an opaque passthrough of
whatever URST's `CodecLayer` writes / reads — the roundtrip test proves a real
URST exchange survives the wrap unmodified. The device `mux.py` does the same
(opaque `ota_port`). No layout assumption is baked into `channel.py`.

### Notes carried forward to sub-task 2

- Wire `ChannelSerial` into the 4 `Urst(ser)` sites (`cli.py:973, 1422, 1829,
  2205`); add `--mux` flag + `otampy.toml` key; move the `reset_input_buffer()`
  call (`cli.py:971`) onto the wrapper (or call both).
- Document `--mux`, channel-id and `min_tx_gap_ms` settings in `protocol.md`
  §1.3 (currently wire-format only).
- `ChannelCodec` takes `ota_channel` / `app_channel` args (default 0/1) so the
  configurable-channel-id requirement is already supported at the codec level.
