# Findings ledger

Durable record of code-review findings. IDs are permanent and never reused.
See `~/.claude/skills/sl-findings` for the process.

Gate rule: an **open** or **fixed** P0/P1 blocks a merge. P2/P3 do not.

---

## Open / fixed

_(none — F-01..F-03 closed, see below)_

## Closed

### F-01 — `ChannelSerial.in_waiting` and `_pump` block on an empty serial port

- **Severity:** P2
- **Status:** closed
- **Area:** `src/otampy/` (channel.py; activated by the mux CLI wiring)
- **Found:** 2026-09-08 by /code-review (feature/channel-mux-cli-mode)
- **Evidence:** `src/otampy/channel.py:153` — `_pump` does
  `pending = getattr(self._ser, "in_waiting", 0) or 1` then
  `self._ser.read(pending)`. When the raw port's buffer is momentarily empty,
  `pending` is `1` and `serial.Serial.read(1)` blocks up to
  `serial_timeout_seconds` (default 2.0). `ChannelSerial.in_waiting`
  (`channel.py:174`) calls `_pump` first, so it blocks too — but a real
  `serial.Serial.in_waiting` never blocks. URST's `read_frame`
  (`urst/codec_layer.py`) does `bytes_to_read = max(1, self.ser.in_waiting)`
  then `self.ser.read(bytes_to_read)` — two `_pump` calls per loop iteration, so
  in mux mode one iteration can stall ~2×`serial_timeout` (~4 s) against a
  silent peer. Reproduced: with a raw port whose `read` sleeps 500 ms,
  `ChannelSerial(raw).in_waiting` took 500 ms and `.read(10)` a further 500 ms.
- **Impact:** Against a responsive device the exchange still completes (the
  end-to-end `test_mux_ping_roundtrip_returns_pong` passes), but on a slow or
  lossy link mux mode is ~2× slower to retry/give up than direct mode, and
  `read_frame`/`send_reliable` overshoot their millisecond timeout budgets.
  Direct mode is unaffected (`serial.in_waiting` is non-blocking there).
- **Suggested fix:** in `_pump`, read only `self._ser.in_waiting` bytes and
  return early when that is 0 (never fall back to a blocking `read(1)`).
- **Resolution:** 2026-09-08, `feature/channel-mux-cli-mode`. `_pump`
  (`src/otampy/channel.py:152`) now reads `getattr(self._ser, "in_waiting", 0)`
  and only calls `self._ser.read(pending)` when `pending` is non-zero — no
  `or 1` fallback. `ChannelSerial.read` returns `b""` promptly and URST's
  `read_frame` poll loop does the waiting. Tests:
  `tests/test_channel.py::TestChannelSerial::test_pump_does_not_read_when_port_is_empty`
  (fake serial whose `read` raises) and `test_pump_reads_only_what_is_pending`.
- **Closed:** 2026-09-08, /sl-findings review. Re-read `channel.py:152-167` as it
  now stands: `pending = getattr(self._ser, "in_waiting", 0)` with no `or 1`,
  `read()` only called when `pending` is truthy, `read()`/`in_waiting` return
  promptly. Blocking path gone. Full suite green (513). New Risk noted below
  (`.any()`-only ports). Re-review was same-session/same-agent as the fix; the
  producing `/code-review` was independent.

### F-02 — Mux CLI eagerly imports `urst` at `otampy.cli` import time

- **Severity:** P3
- **Status:** closed
- **Area:** `src/otampy/cli.py`
- **Found:** 2026-09-08 by /code-review (feature/channel-mux-cli-mode)
- **Evidence:** `src/otampy/cli.py:21` adds `from .channel import ChannelSerial`
  at module scope; `channel.py` does `from urst.codec_layer import cobs_decode,
  cobs_encode` at *its* module scope. Confirmed: `import otampy.cli` now leaves
  `urst` and `urst.codec_layer` in `sys.modules` (they were not before — the
  rest of cli.py keeps `import serial` / `from urst import Urst` function-local,
  and even guards the type-only imports under `TYPE_CHECKING`). `serial` is
  still lazy.
- **Impact:** `otampy --help`, shell completion and every non-device subcommand
  now pay the `urst` import (small — a pure-Python module plus a 256-entry CRC
  table build). Minor, but it breaks the deliberate lazy-import pattern this
  diff otherwise preserves.
- **Suggested fix:** move `from otampy.channel import ChannelSerial` inside
  `_open_transport`, alongside the existing `import serial` / `from urst import
  Urst`.
- **Resolution:** 2026-09-08, `feature/channel-mux-cli-mode`. Moved
  `from .channel import ChannelSerial` from `cli.py` module scope into
  `_open_transport`. Verified: `import otampy.cli` leaves neither `urst` nor
  `serial` in `sys.modules`. Test:
  `tests/test_mux_cli.py::TestLazyImport::test_importing_cli_does_not_pull_in_urst_or_serial`
  (subprocess).
- **Closed:** 2026-09-08, /sl-findings review. `ChannelSerial` now appears in
  `cli.py` only at `_open_transport`'s local import and its one use site
  (grep-verified); no module-scope reference. Subprocess test confirms `import
  otampy.cli` leaves `urst`/`serial` out of `sys.modules`.

### F-03 — A malformed `OTAMPY_MUX` fails every command, including the ones to fix it

- **Severity:** P2
- **Status:** closed
- **Area:** `src/otampy/cli.py`
- **Found:** 2026-09-08 by /code-review (feature/channel-mux-cli-mode)
- **Evidence:** `src/otampy/cli.py:831` — the `cli` group callback runs
  `ctx.obj["mux"] = mux if mux is not None else get_mux_enabled()` for **every**
  subcommand, and `get_mux_enabled()` (`cli.py:518`) raises `ClickException` on
  an unrecognised `OTAMPY_MUX` token. Reproduced: with `OTAMPY_MUX=maybe`,
  `otampy mux --show`, `otampy mux --clear` and `otampy ports --show` all exit 1
  with `Error: OTAMPY_MUX must be one of …` — the user cannot use the `mux`
  command to inspect or clear the setting while the bad env var is present.
- **Impact:** Self-inflicted lockout from a typo in an env var. Recovery is
  `unset OTAMPY_MUX` (the error message names the var), so impact is limited,
  but a config-inspection/repair command should not be blocked by the config it
  inspects.
- **Suggested fix:** in the `cli` callback, treat an unparseable `OTAMPY_MUX` as
  "unset" with a warning (fall through to the saved setting), or defer the
  strict parse to the point of use so `otampy mux` still runs.
- **Resolution:** 2026-09-08, `feature/channel-mux-cli-mode`. `get_mux_enabled`
  (`src/otampy/cli.py`) no longer raises on an unrecognised token — it prints
  `Warning: ignoring OTAMPY_MUX=… ` to stderr and falls through to the config
  chain (new `_parse_mux_token` / `_mux_from_config` helpers). `_mux_state`
  appends `(env OTAMPY_MUX=… invalid, ignored)` to the source so `otampy mux
  --show` still reports it. Verified: `OTAMPY_MUX=maybe otampy ping` and
  `otampy mux --clear` now exit 0 with a warning. Tests:
  `test_invalid_env_token_is_ignored_with_warning`,
  `test_invalid_env_falls_through_to_default`,
  `TestMuxCommand::test_show_still_works_with_a_malformed_env_var`.
- **Closed:** 2026-09-08, /sl-findings review. `get_mux_enabled` (`cli.py:532`)
  has no `raise` path — unrecognised token → stderr warning → `_mux_from_config`.
  Its only caller is the `cli` group callback (`cli.py:848`); `_mux_state` uses
  `_parse_mux_token` directly. Re-verified live: `OTAMPY_MUX=maybe otampy ping`
  and `otampy mux --clear` both exit 0. The empty-string-is-disable behaviour is
  unchanged (tracked as a Risk).

---

## Risks

Concerns worth keeping but not confirmed defects. No ID, block nothing.

- **`ChannelSerial` decoded-buffer overflow drops the oldest bytes.**
  `channel.py:161` caps the decoded channel-0 buffer at `OTA_BUFFER_BYTES`
  (2048) and drops from the front on overflow, which would truncate an in-flight
  URST frame. Not filed as a finding because URST is stop-and-wait — the host
  reads each frame (and each fragment) before the next arrives, so >2 KB of
  unread decoded data has no known path. Mirrors the shipped device
  `_VirtualPort._feed` behaviour. Revisit if a large unsolicited burst path
  appears.
- **`OTAMPY_MUX=` (set but empty) is treated as an explicit "disable".**
  `_MUX_FALSE_TOKENS` (`cli.py:94`) includes `""`, so an empty `OTAMPY_MUX`
  overrides a saved `mux = true` and silently selects direct mode. Deliberate in
  the current design and asserted by `test_env_token_parsing`, but many CLIs
  treat an empty env var as unset. `otampy mux --show` does report the source as
  `env OTAMPY_MUX`, so it is discoverable. Reconsider if it bites.
- **`ChannelSerial` only reads via `in_waiting`, not `any()`.** After the F-01
  fix, `_pump` (`channel.py:156`) does `getattr(self._ser, "in_waiting", 0)` and
  reads nothing if that attribute is absent — so a MicroPython-style port
  exposing only `.any()` would receive nothing. Not a defect today: `cli.py`'s
  `_open_transport` always wraps a real `serial.Serial`, and every test double
  provides `in_waiting`. If `ChannelSerial` is reused with a non-pyserial port,
  add an `elif hasattr(self._ser, "any")` branch like `urst.codec_layer` has.
