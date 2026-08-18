# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
correspond to PyPI releases of `otampy` (see `release.sh`).

## [4.4.0] - 2026-08-18

### Added

- **`upd` now reports transfer progress within each file, not just at its start.** A single update is dominated by its largest file: at the 128-byte transfer chunk size a ~34 kB `main.py` is ~268 chunks, and every chunk is an ack round-trip over the link. Announcing a file and then saying nothing until the next one began made the longest part of an update indistinguishable from a hang -- in a terminal, and in anything capturing the output (a dashboard, a log, CI).
  - On a terminal, a live progress bar per file, showing position in the manifest, percentage, transfer rate and time remaining.
  - When the output is not a terminal, plain lines at 25% steps (`main.py: 50% (17152/34188 bytes)`). A redrawn bar is meaningless once captured, and its control codes are just litter in whatever reads it. Rich decides this from the real stream, so redirecting is enough to select it.
  - The per-file announcement now carries its position in the manifest: `[2/13] main.py (34188 bytes)`.
  - Progress is only advanced once the device has acked a chunk, so it reflects bytes the device took rather than bytes written to the wire.
- **`upd --no-progress`** restores exactly the previous output: one plain `Transferring <path> (<n> bytes)...` line per file, no counter and no percentages. For scripts and captured runs where the extra lines are noise.

## [4.3.1] - 2026-08-17

### Fixed

- **`otampy cat` corrupted piped/captured output, breaking any exact byte-for-byte use (e.g. file-integrity verification against the source file).** Three separate bugs, all in the `cat` command:
  - The `"Showing content of specified file: ..."` status line printed to stdout instead of stderr, always prepending itself to the captured content.
  - The raw device file content was printed through `Console.print()` with Rich markup enabled, so any literal `[...]` in the file -- list literals, dict/subscript syntax, bracketed comments -- was silently swallowed as an unrecognized style tag. Real data loss, not a formatting artifact; not recoverable downstream once printed. Fixed with `markup=False`.
  - `Console.print()` appends its own trailing newline regardless of whether the content already ends in one, so `cat` always emitted one extra blank line beyond the file's actual content. Fixed with `end=""`.

  Found via `diff-drive-robot`'s `bin/robot-hil-check`, which diffs `otampy cat`'s output against the repo's source file to prove a deploy landed -- all three bugs made that check permanently fail regardless of whether the device content actually matched.
  - `tests/test_cli.py::test_cli_cat_status_message_goes_to_stderr`, `test_cli_cat_does_not_interpret_brackets_as_markup`

## [4.3.0] - 2026-08-14

### Added

- **`SerialMux(uart, min_tx_gap_ms=0)`: an opt-in minimum gap enforced between the end of one physical UART write and the start of the next, across both the OTA and app channels.**

  Bench testing on `diff-drive-robot` (old MaxStream XBee Pro 802.15.4 radios, transparent/AP=0 mode) found that a device transmitting frames back-to-back with no inter-frame gap reliably corrupts reception at the other end -- confirmed fixed by pacing transmissions at >=20ms, and confirmed not explainable by payload size or `RO` (packetization timeout). Mirrors `urst-mpy` 3.2.0's `CodecLayer(min_tx_gap_ms=...)`, but at the mux layer, since a mux user's channel-1 (app) traffic sits entirely outside URST and shares the same physical UART -- only enforcing the gap in `urst-mpy` couldn't protect against an app-channel write landing right after an OTA-channel write.

  `SerialMux._write_channel()`'s inner `_write()` closure is the single point both channels' physical `uart.write()` calls already go through, so the gap is tracked once on the mux instance and applies uniformly regardless of which channel wrote last. Default `0` -- zero behaviour change for existing users/hardware.

  - `src/otampy/device/tests/test_mux.py::TestMinTxGap` covers the default no-op case, sleeping for the remaining gap across a channel-0-then-channel-1 write pair, and not sleeping once the gap has naturally elapsed.

## [4.2.4] - 2026-08-13

### Fixed

- **`manager.py`'s manual fragment loop (`_send_response()`) no longer sends ABORT or an `ERROR:Fragment transfer failed` reply when `send_reliable()` failed because a CONNECT already reset the peer's session (US-003, `urst-mpy`'s corresponding fix).** Both used to fire unconditionally on any fragment-send failure; when the failure is a mid-stream CONNECT reset, the peer that would receive either one has already moved on to a new session and never asked about this message -- sending them anyway just adds another stale frame to the exact problem US-003 exists to stop. Both call sites (lines ~106, ~129) now check the new `protocol.session_reset_during_send` flag first. Requires `urst-mpy`'s unreleased US-003 fix (`develop`, `a2f1a8c`); the existing `>=3.0.0` pin (no upper bound) will pick it up once released, no pin change needed.
  - `src/otampy/device/tests/test_ota_manager.py::test_manager_suppresses_abort_and_reply_when_peer_reset_the_session` covers the suppression; `conftest.py`'s `FakeProtocol` gained `session_reset_during_send` and an `aborted` list to make ABORT calls observable.

## [4.2.3] - 2026-08-11

### Fixed

- **The CLI abandoned a fragmented reply the moment the device paused mid-stream, instead of waiting out the pause.** `_query()` treated the first empty `read()` as a timeout and raised, then retried the whole command with a fresh transport. `Urst.read()` is single-shot -- it returns `b""` on a frame-read timeout while keeping the partial reassembly -- so any device pause longer than `ACK_TIMEOUT_MS` (1s) mid-response ended the transfer. Measured on real hardware: a Pico W replying to `CAT` with 56 fragments stalls ~1.2s between fragments, so the retry's CONNECT collided with the still-streaming response and desynchronised both ends; `cat` of a device log failed every single time.

  `_read_full_reply()` now keeps reading while URST reports a reassembly in progress, so §6.3.4's (much longer) reassembly deadline is what actually decides to give up. Measured over the radio link, resetting the device between attempts: `cat boot.py` went from 0/3 to 2/3 successful. The remaining failure is a device-side abort (`send_reliable` exhausting its retries) and was not fixed here -- see US-003 above.

## [4.2.2] - 2026-08-10

### Changed

- **Device library (`manager.py`, `filecopy.py`, `boot.py`) now replies via `transport.reply()` instead of `transport.send()`**, using `urst-mpy`'s §5.8 Request ID correlation (released in `urst-mpy` 3.0.0). Every command handler answers whatever it most recently read, so this is a mechanical `send()` -> `reply()` rename at each reply call site; `boot.py`'s unprompted `READY` push (sent before any command is received, to kick off an OTA session) is the one call site that correctly stays on `send()`.
  - `manager.py::_send_response()`'s manual fragment loop (bypasses `Urst.send()`'s own fragmentation to keep `gc.collect()` calls between fragments) now threads `request_id` through to `protocol.send_reliable()` by hand, and calls `protocol.send_abort()` on retry exhaustion -- neither comes for free outside `Urst.send()`.
  - No change needed on the CLI side: `_query()`'s existing `transport.send(command)` / `transport.read()` pattern already matches the new default (`request_id=None` starts a new request), unchanged.
  - `urst-mpy` dependency widened from `>=1.0.0,<3.0.0` to `>=3.0.0` to pick up `Urst.reply()`/Request ID support.

## [4.2.1] - 2026-08-10

### Fixed

- **`mux.py`'s `SerialMux.service()` crashed on the very first frame it ever
  parsed on real MicroPython hardware**, with `TypeError: 'bytearray'
  object doesn't support item deletion`. It trimmed consumed bytes off the
  front of `_rx_buffer` with `del self._rx_buffer[: idx + 1]`; MicroPython's
  `bytearray` doesn't support item/slice deletion at all (only CPython's
  does), so this raised on every device, unconditionally, the moment any
  outer frame was received.

  Reproduced against a real deployment (diff-drive-robot): `main.py`'s
  loop died with this traceback on startup, every boot.

  `service()` now trims via slice reassignment
  (`self._rx_buffer = self._rx_buffer[idx + 1 :]`) instead, matching the
  pattern already used elsewhere in `mux.py` (e.g. `_VirtualPort._feed`).
  The existing `test_service_trims_rx_buffer_in_place_without_reallocating`
  test had asserted the old `del`-based behaviour as a desired
  optimization; it passed because CPython's `bytearray` *does* support
  slice deletion, masking the MicroPython incompatibility entirely from
  the test suite. Renamed to
  `test_service_trims_rx_buffer_via_slice_reassignment` and rewritten to
  assert only the correct trimming behaviour, not a specific
  (MicroPython-incompatible) mechanism.

## [4.2.0] - 2026-08-10

### Fixed

- **`upd`'s per-step reads (`SPACE_OK`/`FILE_OK`/`CHUNK_ACK`/`DELETE_OK`/
  `COMMIT_OK`/`UPDATE_ABORTED`) gave up after a single empty
  `transport.read()`, treating a merely-late reply as a failed transfer.**
  `Urst.send()` already delivers each command reliably (URST-level
  ACK/NAK with retries) before `_update_files` moves on to read the
  device's application-level reply; but that reply is itself sent via the
  device's own `send_reliable()`, which can still be mid-retry well after
  our single read's `ACK_TIMEOUT_MS` window elapses. A missing reply is
  therefore not proof it was lost, only that we haven't seen it yet.

  Reproduced against a real deployment (diff-drive-robot, over a marginal
  radio link, after the `urst-mpy` NAK/desync fix below): an `upd`
  progressed far further than before but still failed outright on what
  the device-side log showed was a purely late `CHUNK_ACK`.

  New `_read_reply()` retries the *read* (never resends the command) up
  to `transfer_reply_retries` (new config, default 3) times when the read
  comes back empty; an explicit reply, even a rejection, is returned
  immediately and never retried, since only silence is ambiguous.
  - `tests/test_cli.py::test_cli_update_retries_read_through_late_reply_without_resending`
    covers the happy path (an empty read recovered by retrying the read,
    with the command sent exactly once). `test_cli_update_aborts_before_commit_on_transfer_failure`
    was updated to genuinely exhaust the retry budget rather than fail on
    a single empty read, since that's no longer sufficient by itself.

### Changed

- Widened the `urst-mpy` dependency pin from `>=1.0.0,<2.0.0` to
  `>=1.0.0,<3.0.0` so `uv lock -P urst-mpy` picks up `urst-mpy` 2.0.0
  (released to carry the NAK/desync fix noted below; its only breaking
  change -- removing the unused `urst.__version__` attribute -- isn't
  referenced anywhere in otampy). `uv.lock` now resolves `urst-mpy==2.0.0`.

### Notes

- **A second, deterministic root cause of `Error: Fragment transfer
  failed` / stuck `upd` transfers was in `urst-mpy`, not otampy: a NAK
  triggered a blind retransmit of the identical frame instead of
  connection re-establishment.** Per the URST spec, a NAK means the peer's
  sequence state has desynchronized and MUST be resolved via `CONNECT`,
  not by resending what was just rejected -- `urst-mpy`'s
  `ProtocolLayer.send_reliable()` did the latter, which can livelock
  forever against a genuinely desynchronized peer (confirmed live: 12
  consecutive NAKs on the same chunk during an `upd`). No otampy code
  change needed for the fix itself; see the dependency pin update above.
  - Fix, tests, and full analysis: `urst-mpy` `238fee6` (`develop`),
    released as `urst-mpy` [v2.0.0](https://github.com/simonl65/URST-mpy/releases/tag/v2.0.0).

- **Root-caused an intermittent `Error: Fragment transfer failed` /
  mismatched-response class of bug to `urst-mpy`, not otampy.** Diagnosed
  via a real deployment (diff-drive-robot) where `otampy cat` returned a
  stale `PONG` (from an earlier `ping`) instead of the expected `CAT_OK`
  response. Root cause: `urst.ProtocolLayer.connect()` never drained bytes
  already buffered on the transport before starting a new session, so a
  long-lived relay (a gateway PTY, in this case) could hand a fresh CLI
  invocation a response frame left over from a previous one. otampy's own
  code isn't implicated -- `cli.py`'s response-prefix check
  (`_query`/`_handle_device_error`) is in fact what surfaced the mismatch
  clearly enough to diagnose it.
  - Fix, tests, and full analysis: `urst-mpy` [#4](https://github.com/simonl65/URST-mpy/issues/4),
    fixed on `develop` at `f7cc7e4`.
  - **Decision:** no otampy code change needed. `pyproject.toml` already
    pins `urst-mpy>=1.0.0,<2.0.0`, so otampy will pick up the fix on the
    next `urst-mpy` patch/minor release without a version bump here.
    Action needed once that release ships: `uv lock -P urst-mpy` (or
    equivalent) in any project consuming otampy, to actually pull the
    fixed version in -- the existing pin permits it but won't fetch it on
    its own. See project README / release notes for the otampy version
    that first ships with the fixed `urst-mpy` as its resolved dependency.
