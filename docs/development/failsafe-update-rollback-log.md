# Fail-safe Updates sub-task 3 — `ROLLBACK` command + `otampy rollback` CLI — dev log

Branch: `feature/failsafe-update-rollback`
Spec: `docs/development/failsafe-update-rollback-spec.md` (status `approve`)

## 2026-09-09 — start

Branch created from `develop` (at `ab6c71e`, sub-task 2 HIL evidence).

Ledger state at start: F-04/F-05/F-06/F-07 closed, **F-08 open (P2)** — a power
loss while `restore.py` itself is the mid-commit file. In the touched area but
deliberately out of scope here; owned by sub-task 4.

Starting at build step 1 (`restore.rollback()`).

## 2026-09-09 — steps 1 & 2

- Step 1: `restore.rollback(core)` + `_ROLLBACK_BUSY`. 5 tests in test_restore.py.
- Step 2: `manager.poll` `elif cmd == "ROLLBACK"` — lazy `from .restore import
  _ROLLBACK_BUSY, rollback`. Restore first, then reply, then (success only)
  callback → `_persist_replay_floor` → `machine.reset()`, mirroring `RB`.
  6 tests in test_ota_manager.py + 1 signed-path test in test_manager_auth.py
  (floor persisted at counter 4242 before reset).
- `uv run pytest src/otampy/device/tests/ -q` → 314 passed. Facade lazy-load
  test still green. ruff clean.
