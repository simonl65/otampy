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

### Step 2 — `ChannelCodec`
(next)
