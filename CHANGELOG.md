# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
correspond to PyPI releases of `otampy` (see `release.sh`).

## Unreleased

### Notes

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
