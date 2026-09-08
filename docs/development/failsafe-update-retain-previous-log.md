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
