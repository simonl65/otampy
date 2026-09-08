# Retain-previous commit + journal contract — dev log

Spec: `docs/development/failsafe-update-retain-previous-spec.md`
Branch: `feature/failsafe-update-retain-previous`

## 2026-09-08 — build started

Branch created from `develop` (clean, at `78ef5c3`). Findings ledger
(`docs/development/findings.md`) does not exist yet — nothing open to block
this work.

### Design decision taken in step 1 — where `_resolve_path` lives

The spec left this open ("import from `.boot` … or lift `_resolve_path` into
`core.py` … decide during build"). `boot.py` will import `restore` (steps 4-6),
so `restore` importing from `.boot` would be a cycle. Lifted `_resolve_path`
into `core.py` next to `_get_config`; `boot.py` now does
`from .core import _get_config, _resolve_path`, which keeps the module-level
name `boot._resolve_path` that the existing tests monkeypatch. One copy, no
cycle.

### Build progress

- **Step 1** (`046bffc`) — `restore.py` journal helpers + `test_restore.py`.
  One test assertion was wrong (expected re-resolved journalled paths); the
  code stores paths verbatim, so the test was corrected.
- **Step 2** (`00caaf7`) — `restore.commit()`. The in-progress pair must be
  recorded in the rollback list *before* the staging rename: if that rename
  fails, the target has already moved to `.bck` and must be rolled back too.
  Caught by `test_commit_rolls_back_whole_set_on_rename_failure`.
- **Step 3** (`5c7da3e`) — `restore.repair()`, two modes.
- **Step 4** (`b9b14e8`) — `boot.run()` calls `repair()` after the staged-RTC
  step via a local `from .restore import repair`; `ota.OTA.boot()` teardown
  releases `restore` alongside `boot`.
- **Step 5** (`ce3f0cc`) — `clear_journal()` at the top of `UPDATE_START`.
- **Step 6** (`d5a8003`) — `UPDATE_COMMIT` now just calls `commit()`;
  `COMMIT_ERR` is a documented response.
- **Step 7** (`0a3fece`) — `_cleanup_orphaned_ota` sweeps `<x>.bck` not in the
  journal; journalled backups threaded through recursion as `kept_backups`.
- **Step 8** — docs, changelog, both `configota` examples, `TODO.md`.

Pyright reports "Import '.restore' could not be resolved" for the in-function
imports in `boot.py`. Editor-only LSP artefact — the device lib is not on
pyright's path. The import works at runtime (every device test exercises it)
and pre-flight (ruff + full pytest, mirrors CI) is green at every step.

## 2026-09-08 — HIL: not yet run

Host side is complete: all 8 build steps committed, `pre_flight_check.py`
green (ruff + full pytest). Findings ledger (added by Simon at `98ea791`) is
empty — nothing blocks a merge.

**Robot not reachable from this session.** `otampy -p /dev/ttyUSB0 ping`
(direct on the gateway XBee) failed with "device reports readiness to read but
returned no data (… multiple access on port?)" after three handshake attempts
— consistent with the diff-drive-robot gateway daemon holding `/dev/ttyUSB0`,
or the robot being powered down. Not probed further: grabbing that port while
the gateway may be running, or repeated USB pokes, is exactly the
false-alarm pattern to avoid.

HIL therefore stays with Simon. Plan is the spec's Verification section
(happy path, power-loss whole-set rollback, single-generation retention, bad
firmware survives + manual `.bck` recovery). Bootstrapping needs
`otampy deploy` on the feature branch (raw-port, human-run only). Results and
every measurement to be appended here before `git flow feature finish`.
