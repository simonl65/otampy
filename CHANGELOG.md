# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
correspond to PyPI releases of `otampy` (see `release.sh`).

## Unreleased

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
