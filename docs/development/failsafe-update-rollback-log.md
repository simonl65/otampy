# Fail-safe Updates sub-task 3 — `ROLLBACK` command + `otampy rollback` CLI — dev log

Branch: `feature/failsafe-update-rollback`
Spec: `docs/development/failsafe-update-rollback-spec.md` (status `approve`)

## 2026-09-09 — start

Branch created from `develop` (at `ab6c71e`, sub-task 2 HIL evidence).

Ledger state at start: F-04/F-05/F-06/F-07 closed, **F-08 open (P2)** — a power
loss while `restore.py` itself is the mid-commit file. In the touched area but
deliberately out of scope here; owned by sub-task 4.

Starting at build step 1 (`restore.rollback()`).
