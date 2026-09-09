# Trial boot, health confirmation, auto-restore — spec

**TODO item:** `[ ] 2. Trial boot, health confirmation, auto-restore.` (sub-task 2 of **Fail-safe Updates**)
**Status:** approved
**Components:** `src/otampy/device/lib/otampy/` (`restore.py`, `boot.py`, `ota.py`, `manager.py`), `src/otampy/cli.py`, `src/otampy/device/examples/`, `docs/protocol.md`, `docs/architecture.md`, `CHANGELOG.md`
**Dev log:** `docs/development/failsafe-update-trial-boot-log.md` (created by `/sl-build`)

## Goal

After this ships, a freshly committed update is **on trial** until something
confirms it. `boot.py` counts each boot into an unconfirmed candidate in the
retain-previous journal; once the count passes `OTA_TRIAL_BOOTS` the device
restores the entire previous generation from its `.bck` files and reboots onto
it, with no host involvement. A candidate is taken off trial by `CONFIRM` (sent
by the host after a post-reboot `PING`, automatically at the end of
`otampy upd` unless `--no-confirm`) or by `ota.confirm()` (called by the
application after its own health check). Confirming only stops the trial
counter — it does **not** delete the retained `.bck` set, so the previous
generation stays recoverable (manually now, via `otampy rollback` in sub-task 3)
until the next update's `UPDATE_START` clears it. A new read-only `UPDATE_STATE`
command reports `STATE_OK:<trial|stable>:<attempt>`.

The auto-rollback trigger is **a reboot during the trial window** — a crash to
reset, a panic, a brownout, the application's own watchdog firing, or a manual
power cycle. A candidate that hangs without resetting does not advance the
counter and is not auto-rolled-back; that case is covered by `otampy rollback`
over the link (sub-task 3) and the boot-time recovery listen window
(sub-task 4). Applications are expected to run their own watchdog (as
`diff-drive-robot` does), which supplies the reset.

## In scope

- **Journal grammar extension.** Line 1 gains a third value: `confirmed`, in
  addition to `committing` (sub-task 1) and a base-10 attempt counter.
  `read_journal` returns a `state` string (`"committing"` / `"trial"` /
  `"confirmed"`) in place of sub-task 1's `in_progress` bool. All in-repo
  callers updated in the same step.
- **`restore.restore_all(core)`** — the whole-set restore primitive: rename
  every journalled `<path>.bck` back over its target, then remove the journal.
  `repair()`'s `committing` branch is refactored to call it. Sub-task 3's
  `ROLLBACK` reuses it.
- **`restore.trial(core)`** — called from `boot.run()` on every boot. When the
  journal state is `trial`: increment the counter, persist it, and if it now
  exceeds `OTA_TRIAL_BOOTS`, `restore_all()` and return a `"rolled_back"`
  sentinel so `boot.run()` performs `machine.reset()`. No-op in every other
  state.
- **`restore.confirm(core)`** — flip journal line 1 from the counter to
  `confirmed`, keeping the path list. Idempotent; `True` when the candidate is
  (now or already) confirmed or there is nothing on trial, `False` only if a
  commit is mid-flight.
- **`restore.state(core)`** — `-> (label, attempt)` for `UPDATE_STATE`;
  `("trial", n)` while counting, `("stable", 0)` once confirmed or with no
  journal.
- **F-07 fold-in.** `repair()` and `trial()` write the journal only when they
  changed something (marker flip, a restore, or a counter increment).
- **`boot.run()`** — call `trial(core)` immediately after `repair(core)`; on the
  `"rolled_back"` sentinel, log and `machine.reset()` (local import).
- **`manager.poll`** — dispatch `CONFIRM` → `CONFIRM_OK`/`CONFIRM_ERR` and
  `UPDATE_STATE` → `STATE_OK:<label>:<attempt>`. Both via lazy
  `from .restore import …` per command, so `manager` import stays light
  (the lazy-load facade test still passes).
- **`ota.confirm()`** — one-line facade over `restore.confirm(self._core)`.
- **Host `otampy upd`** — after `COMMIT_OK`, once the device is reachable again,
  `PING` then `CONFIRM` (expecting `CONFIRM_OK`). `--no-confirm` skips it and
  prints how the candidate is confirmed or will auto-roll-back. A `PING` that
  never succeeds within `update_ready_timeout_seconds` prints a clear warning
  (candidate NOT confirmed; auto-rollback after `OTA_TRIAL_BOOTS` reboots) and
  exits non-zero.
- **Host `otampy confirm`** and **`otampy state`** commands.
- **New device config key `OTA_TRIAL_BOOTS`** (default `3`), documented in
  `docs/architecture.md` §1 and `configota.example.py`.
- **Docs** — `docs/protocol.md` §2.1/§2.4 (the two new commands, the trial-boot
  lifecycle), `docs/architecture.md` (trial boot + confirm + `OTA_TRIAL_BOOTS`),
  `CHANGELOG.md` `Unreleased`.
- **Tests** — additions to `test_restore.py`, `test_ota_boot.py`,
  `test_ota_manager.py`, `test_ota_facade.py`, `tests/test_cli.py`,
  `tests/test_examples.py`.

## Out of scope

- **`ROLLBACK` command and `otampy rollback`** — sub-task 3. This spec builds
  `restore_all()` and the retained-`.bck`-after-confirm model that sub-task 3
  depends on, but adds no user-initiated revert path.
- **Boot-time recovery listen window; F-08** (`restore.py` lost mid-commit) —
  sub-task 4.
- **A watchdog-backed trial timeout** — a candidate that hangs without
  resetting is not auto-rolled-back. Signed off as reboot-triggered only
  (2026-09-09): the application owns its watchdog, and sub-tasks 3/4 cover the
  stranded-device cases. Not built, documented as a limitation.
- **Deep application health checks.** `CONFIRM` after `PING` confirms only that
  the candidate booted far enough to serve OTA over the poll loop — not that
  the application logic is correct. A candidate that answers `PING` then
  misbehaves is already confirmed and needs `otampy rollback` (sub-task 3).
- **Deleting the retained generation on `CONFIRM`.** Deliberately not done (see
  Goal) — `UPDATE_START` remains the only thing that clears it, unchanged from
  sub-task 1.
- **Filesystem-atomic transactions** — same boundary as sub-task 1.

## Protocol decision

- **Existing OTAmpy/URST command reusable?** No. None of `PING` / `RB` /
  `UPDATE_*` can signal "accept the running candidate" or "report update state".
  `CONFIRM` and `UPDATE_STATE` are genuinely new.
- **Channel:** 0 (reliable). Same command surface as `PING`/`RB`, dispatched by
  `manager.poll`, wrapped by the auth envelope automatically when
  `OTA_REQUIRE_AUTH` is set. Neither command resets the board, so neither needs
  `_persist_replay_floor` (unlike `RB`/`SR`/`UPDATE_REQUEST`).
- **Wire format change?** No URST change. Two new application-layer commands on
  channel 0; `PROTOCOL_VERSION` does not move. Host `cli.py` and device
  `manager.py` change together; no gateway/mux involvement (channel 0 only).
- **Signed off:** 2026-09-08 by Simon — the Fail-safe Updates protocol
  decision explicitly names `ROLLBACK`, `CONFIRM`, `UPDATE_STATE` as the
  planned new channel-0 commands. Three sub-decisions confirmed 2026-09-09:
  reboot-triggered trial only; `CONFIRM` retains `.bck` until `UPDATE_START`;
  `otampy upd` auto-confirms with `--no-confirm`.

## Data and contracts

### Journal line 1 — **load-bearing** (extends sub-task 1)

| Line 1 value | `state` | Meaning | `boot.run()` action |
| --- | --- | --- | --- |
| `committing` (or unrecognised) | `"committing"` | A commit is partway through | `repair()` → `restore_all()` (whole set back, journal removed) |
| base-10 int `n` ≥ 0 | `"trial"` | Committed candidate, `n` boots counted, unconfirmed | `trial()` increments; `restore_all()` + reset when `n > OTA_TRIAL_BOOTS` |
| `confirmed` | `"confirmed"` | Candidate accepted; `.bck` retained for recovery, no trial counting | none |

- Lines 2..n (retained target paths) are unchanged from sub-task 1.
- A missing/empty journal parses as `(attempt=0, state="confirmed", paths=[])`
  — i.e. "nothing on trial", the same effect the old `(0, False, [])` had for
  the callers that matter (`trial()`/`state()` no-op, `clear_journal` no-op).
- `commit()` still writes line 1 as `committing` then flips to `0`
  (unchanged) — `0` now reads as `state="trial"`, `attempt=0`.

### `restore.py` public surface — **load-bearing**

| Function | Contract |
| --- | --- |
| `read_journal(core)` | `-> (attempt:int, state:str, paths:list[str])`. `state ∈ {"committing","trial","confirmed"}`. Never raises. `(0, "confirmed", [])` when absent/empty. Unrecognised line 1 → `state="committing"` (fail safe). |
| `write_journal(core, line1, paths)` | Unchanged. `line1` is `"committing"`, `"confirmed"`, or an int. |
| `clear_journal(core)` | Unchanged — removes every `<path>.bck` then the journal. Called by `UPDATE_START`. |
| `commit(core, files, delete_paths)` | Unchanged from sub-task 1. |
| `restore_all(core)` | Rename every journalled `<path>.bck` that exists back over its target (removing a partial target first), then remove the journal file. Returns the count restored. Never raises. Bounded by journal length. |
| `repair(core)` | `state=="committing"` → `restore_all(core)`. `state=="trial"` → restore only paths whose target is missing but `.bck` exists; write the journal back **only if** something was restored (F-07). `state=="confirmed"` or no paths → no-op, no write. Never raises. |
| `trial(core)` | `state != "trial"` → return `None`, no write. Else `attempt += 1`; if `attempt > OTA_TRIAL_BOOTS` → `restore_all(core)`, return `"rolled_back"`. Else `write_journal(core, attempt, paths)`, return `None`. Never raises. |
| `confirm(core)` | `state=="trial"` → `write_journal(core, "confirmed", paths)`, return `True`. `state=="confirmed"` or no journal → return `True` (idempotent). `state=="committing"` → return `False`. Never raises. |
| `state(core)` | `-> (label:str, attempt:int)`. `"trial"` → `("trial", attempt)`. `"confirmed"` / none → `("stable", 0)`. `"committing"` → `("trial", 0)` (defensive; not seen at runtime). Never raises. |

### New commands — **load-bearing**

| Request | Sender | Response | Effect |
| --- | --- | --- | --- |
| `CONFIRM` | Host / app | `CONFIRM_OK` / `CONFIRM_ERR` | `restore.confirm(core)`. `CONFIRM_ERR` only when a commit marker is present. |
| `UPDATE_STATE` | Host | `STATE_OK:<trial\|stable>:<attempt>` | Read-only. `<attempt>` is the current trial count, `0` when stable. |

### Config key

| Setting | Where | Default | Meaning |
| --- | --- | --- | --- |
| `OTA_TRIAL_BOOTS` | `configota.py` | `3` | Boots into an unconfirmed candidate before the device auto-restores the previous generation. Read via `_get_config` with the default, like every other key. |

Named constants: `restore._STATE_COMMITTING = "committing"`,
`restore._STATE_TRIAL = "trial"`, `restore._STATE_CONFIRMED = "confirmed"`,
`restore._DEFAULT_TRIAL_BOOTS = 3`, `restore._ROLLED_BACK = "rolled_back"`.
Command tokens live where `manager.py` already keeps its command strings
(inline `elif` chain).

### Host config

Reuse `update_ready_timeout_seconds` (default 10.0) for the post-commit
"wait for the candidate to answer `PING`" loop — it is the same
"device is rebooting, keep trying" situation as the existing `READY` wait. No
new host config key.

## Device cost

- **Hot-path allocation:** none. `trial()` and `repair()` run once per boot
  (cold). `confirm()` / `state()` run only on the matching command. On a
  normal (stable) boot, `trial()` is one `read_journal` (one `open`/`read`) and
  an early return — no write (F-07). `repair()` is likewise a single read plus
  early return once `state=="confirmed"`.
- **Blocking operations:** `restore_all()` is O(journal length, typically < 10)
  `stat`/`rename` calls, no I/O wait loop — sub-millisecond to low
  milliseconds, far under the ~8388 ms RP2040 WDT cap. No watchdog is armed
  this early in `boot.py`. `machine.reset()` on the rollback path is immediate.
- **Named constants:** as listed above, all module-level in `restore.py`.
- **Module release:** `restore.py` is imported lazily by `boot.py` (already),
  and now also by `manager.py` (per-command local import) and `ota.py`
  (`confirm()`, local import). `ota.OTA.boot()`'s existing teardown that deletes
  `device_otampy.restore` after `boot()` is unaffected — `manager`/`ota`
  re-import it in the `main.py` phase.

## Build steps

- [x] **1. `read_journal` returns a `state` string**
  - What changes: `restore.py` — replace the `in_progress` bool with a `state`
    string (`_STATE_*` constants); recognise `confirmed` on line 1; a
    missing/empty journal → `state="confirmed"`. Update every in-repo caller:
    `clear_journal`, `repair` (`in_progress` → `state == _STATE_COMMITTING`),
    and `boot._cleanup_orphaned_ota` (uses `read_journal(core)[2]` — index
    unchanged, but re-verify).
  - Test: `test_restore.py` — `read_journal` round-trips all three states;
    unknown line 1 → `"committing"`; missing → `(0, "confirmed", [])`. Existing
    `repair()` tests updated for the new tuple shape and still pass.
  - Done when: `uv run pytest src/otampy/device/tests/test_restore.py
    src/otampy/device/tests/test_ota_boot.py -q` passes; `uv run ruff check .`
    clean.

- [x] **2. `restore.restore_all()` + `repair()` delegates to it**
  - What changes: add `restore_all(core)` (whole-set rename-back, then remove
    the journal, return count). Refactor `repair()`'s `committing` branch to
    call it; the `trial`-state "restore missing only" branch stays inline and
    now writes the journal only when it restored something (F-07 partial).
  - Test: `test_restore.py` — (a) `committing` + 2 paths, both `.bck` present
    (one target half-written) → `restore_all` restores both and the journal
    file is gone, returns `2`; (b) `repair()` with `committing` produces the
    same end state; (c) `repair()` with line 1 `0` and all targets present →
    no journal write (assert mtime / a write-count spy).
  - Done when: those tests pass.

- [x] **3. `restore.confirm()` and `restore.state()`**
  - What changes: add both per their contract rows.
  - Test: `test_restore.py` — `confirm()` on a `trial` journal flips line 1 to
    `confirmed` and keeps the paths; second `confirm()` is a no-op returning
    `True`; `confirm()` with no journal → `True`; `confirm()` with `committing`
    → `False`. `state()` returns `("trial", n)` mid-trial, `("stable", 0)` when
    confirmed and when no journal.
  - Done when: those tests pass.

- [x] **4. `restore.trial()`**
  - What changes: add `trial(core)` per its contract row — `_DEFAULT_TRIAL_BOOTS`
    constant, `OTA_TRIAL_BOOTS` via `_get_config`, `_ROLLED_BACK` sentinel.
  - Test: `test_restore.py` — (a) `trial` journal at `0`, `OTA_TRIAL_BOOTS=3` →
    successive calls write `1`, `2`, `3`, returning `None`; the 4th call
    (`4 > 3`) runs `restore_all` (targets back from `.bck`, journal gone) and
    returns `"rolled_back"`; (b) `confirmed` journal → `None`, no write;
    (c) no journal → `None`.
  - Done when: those tests pass.

- [x] **5. Wire `trial()` into `boot.run()`**
  - What changes: in `boot.run()`, after `repair(core)`, add
    `from .restore import trial` and
    `if trial(core) == _ROLLED_BACK:` → `core.logger.warning(...)`,
    `import machine`, `machine.reset()`, **then `return`** (a mocked
    `machine.reset` in tests returns rather than resetting — without the
    `return`, `boot.run()` would fall through into the flag check). Keep
    `restore` in the `ota.OTA.boot()` teardown list (already there).
  - Test: `test_ota_boot.py` — (a) flag absent, `trial` journal at
    `OTA_TRIAL_BOOTS`, all `.bck` present → `boot.run(core)` restores the whole
    set and calls `machine.reset()` (assert on the mocked `machine`);
    (b) flag absent, `trial` journal at `0` → `boot.run(core)` leaves the
    journal at `1`, no reset; (c) flag absent, `confirmed` journal → untouched,
    no reset. Existing no-flag / orphan-sweep tests still pass.
  - Done when: full `test_ota_boot.py` passes.

- [ ] **6. `manager.poll` — `CONFIRM` and `UPDATE_STATE`**
  - What changes: two `elif` branches in `manager.poll`, each with a local
    `from .restore import …`. `CONFIRM` → reply `CONFIRM_OK`/`CONFIRM_ERR`;
    `UPDATE_STATE` → reply `STATE_OK:<label>:<attempt>`.
  - Test: `test_ota_manager.py` — `CONFIRM` on a trialling core replies
    `CONFIRM_OK` and the journal line 1 becomes `confirmed`; `CONFIRM` with a
    `committing` journal replies `CONFIRM_ERR`; `UPDATE_STATE` replies
    `STATE_OK:trial:2` and `STATE_OK:stable:0` for the respective journals.
    `test_ota_facade.py::test_package_import_does_not_eagerly_load_operating_modes`
    still passes (no new eager import).
  - Done when: `test_ota_manager.py` + `test_ota_facade.py` pass.

- [ ] **7. `ota.confirm()` facade**
  - What changes: `OTA.confirm(self)` in `ota.py` — local
    `from .restore import confirm`, `return confirm(self._core)`, with a
    docstring pointing at the application health-check use.
  - Test: `test_ota_facade.py::test_confirm_delegates_to_restore_confirm`.
  - Done when: it passes.

- [ ] **8. `otampy upd` auto-confirm**
  - What changes: after the `COMMIT_OK` branch in `update()` (and outside the
    transfer `try/finally` so the transfer session is closed first), unless a
    new `--no-confirm` flag is set: loop `PING` via `_query` until success or
    `update_ready_timeout_seconds`, then `_send_command(ctx, b"CONFIRM",
    b"CONFIRM_OK")` and print "Candidate confirmed." On `PING` timeout: print a
    warning (candidate did not come back healthy; NOT confirmed; auto-rollback
    after `OTA_TRIAL_BOOTS` reboots; investigate or re-deploy) and
    `raise click.ClickException`. With `--no-confirm`: print that the candidate
    is on trial and how to confirm it (`otampy confirm`) or that it will
    auto-roll-back.
  - Test: `tests/test_cli.py` — extend a full-session update test: after
    `COMMIT_OK` the mock device answers `PONG` then `CONFIRM_OK`, and
    `send.assert_any_call(b"CONFIRM")`; a `--no-confirm` run sends no `CONFIRM`
    and exits 0; a run where `PING` never answers exits non-zero with the
    warning text.
  - Done when: those tests pass; existing update tests still pass.

- [ ] **9. `otampy confirm` and `otampy state` commands**
  - What changes: two small `@cli.command`s. `confirm` → `_send_command(ctx,
    b"CONFIRM", b"CONFIRM_OK")` with `DeviceError` handling like `ping`.
    `state` → `_query(ctx, b"UPDATE_STATE", b"STATE_OK")`, parse
    `<label>:<attempt>`, print e.g. "Candidate on trial (boot 2 of 3)" /
    "Running a confirmed (stable) build".
  - Test: `tests/test_cli.py` — `confirm` prints success on `CONFIRM_OK`;
    `state` renders both `trial:2` and `stable:0` responses.
  - Done when: those tests pass.

- [ ] **10. `main.py` scaffolds — document `ota.confirm()`**
  - What changes: in both `src/otampy/device/examples/main.py` and
    `examples/shared-uart/main.py`, add a commented line near the `ota.recover()`
    call showing `# ota.confirm()  # call after your own health check if you
    do not rely on `otampy upd` to confirm`. No behavioural change to the
    scaffold (it relies on host `CONFIRM`).
  - Test: `tests/test_examples.py::test_main_scaffold_mentions_confirm` (both
    scaffolds contain the guidance line) — or fold into the existing
    `test_main_scaffold_calls_recover`.
  - Done when: it passes.

- [ ] **11. Docs + changelog**
  - What changes: `docs/protocol.md` — add `CONFIRM` and `UPDATE_STATE` to the
    §2.1 control-command table; a §2.4 paragraph on the trial-boot lifecycle
    (commit → trial → `CONFIRM`/auto-rollback), the `confirmed` journal state,
    and that `.bck` is retained past confirm until `UPDATE_START`; note the
    reboot-triggered limitation. `docs/architecture.md` — `OTA_TRIAL_BOOTS` in
    the `configota.py` block; a paragraph under the boot-time update section on
    trial boot + `confirm()` + reboot-triggered auto-restore; note the app is
    expected to supply the watchdog. `configota.example.py` — `OTA_TRIAL_BOOTS`
    commented with the default. `CHANGELOG.md` — an `Unreleased` entry under the
    existing retain-previous block.
  - Test: none — docs.
  - Done when: all four files reflect the new behaviour; no stale claim that a
    committed update is immediately permanent.

## Verification

- **Host:** `python3 .agents/scripts/pre_flight_check.py` (ruff + full pytest,
  mirrors CI). Per-step: `uv run pytest
  src/otampy/device/tests/test_restore.py
  src/otampy/device/tests/test_ota_boot.py
  src/otampy/device/tests/test_ota_manager.py tests/test_cli.py -q`.
- **Hardware** (Pico W, `otampy` deployed from the build branch):
  1. **Happy path.** `otampy upd main.py` with a trivial change. The CLI
     reconnects, prints "Candidate confirmed."; `otampy state` → stable;
     `otampy cat /otampy-update.journal` line 1 is `confirmed`; `main.py.bck`
     still present.
  2. **`--no-confirm` + manual confirm.** `otampy upd --no-confirm main.py`.
     `otampy state` → `trial` (boot 1). Power-cycle twice → `otampy state`
     shows the count climbing. `otampy confirm` → `CONFIRM_OK`; `otampy state`
     → stable.
  3. **Auto-rollback.** Deploy a `main.py` that raises on import **and** arms a
     short watchdog before the raise (or rely on the app's existing WDT).
     `otampy upd --no-confirm` it. The device now boot-loops; after
     `OTA_TRIAL_BOOTS` reboots `otampy ls /` shows `main.py.bck` gone (renamed
     back), the journal gone, and `otampy cat /main.py` is the previous good
     version. `otampy ping` → `PONG`.
  4. **Confirm survives, `.bck` retained.** After test 1, `otampy rollback`
     does not exist yet, but `otampy ls /` confirms `main.py.bck` is still
     there — the retained generation sub-task 3 will revert to.
- **Manual:** Simon runs tests 1–3 and confirms the journal line-1 value at
  each stage and that a confirmed candidate is never rolled back by a plain
  power cycle.

## Risks and open questions

- **A clean power cycle advances the trial counter.** If a candidate is left
  unconfirmed (e.g. `otampy upd` is Ctrl-C'd after `COMMIT_OK`, or run with
  `--no-confirm` and forgotten), `OTA_TRIAL_BOOTS` ordinary power cycles will
  roll back a candidate that was actually fine. Mitigations: `otampy upd`
  auto-confirms within seconds by default; the default of `3` gives slack;
  `otampy state` shows the trial count. Documented, not engineered away.
- **`CONFIRM` after `PING` is a shallow health check.** It proves the poll loop
  is reachable, nothing more. A candidate with a delayed fault is confirmed and
  needs sub-task 3. Called out in Out of scope; `--no-confirm` is the escape
  hatch for users who want to gate on their own checks.
- **Reboot-triggered only.** A candidate that hangs without resetting never
  rolls back automatically (sub-task 3/4). Signed off 2026-09-09.
- **F-07** is folded into steps 2 and 4 (write-on-change). Re-run the existing
  `repair()` tests after the refactor to be sure the "write only when changed"
  guard did not skip a needed flip.
- **F-08** (P2, open) — a power loss while `restore.py` itself is the
  mid-commit file strands the device. Unchanged by this sub-task (it adds more
  callers of `restore`, all lazy). Belongs to sub-task 4; noted here so the
  gate review sees it is a known, deferred P2 in the touched area.
- **`machine.reset()` from `boot.run()`.** New reset site. In tests `machine`
  is a `MagicMock`, so assert the call rather than the effect. On hardware the
  reset happens before `main.py`, so there is no application state to lose.
- **`ota.recover()` runs `repair()` but not `trial()`.** In the F-06 scenario
  (`boot.py` lost mid-commit, `main.py` heals it), the trial counter is not
  advanced that boot — but `repair()` in the `committing` state calls
  `restore_all()`, which abandons the trial and fully restores the previous
  generation anyway, so there is nothing left to count. Once `boot.py` is back,
  the next normal boot resumes `trial()`. No gap, but stated so a reviewer does
  not expect `recover()` to count.
- **A `.bck` rename failing inside `restore_all()`** leaves that one `.bck` on
  disk after the journal is removed — an orphan. The next boot's
  `_cleanup_orphaned_ota` sweeps it (not in any journal). Same best-effort
  convergence as sub-task 1's `repair()`; not engineered away.
- **Journal `state` return-shape change** ripples to any out-of-tree caller of
  `read_journal`. Only `restore.py` and `boot.py` call it in-repo; there is no
  documented public contract for it. Flag it load-bearing for sub-tasks 3–4.

## Notes for the build

- Device tests import `from device_otampy import restore` (see
  `src/otampy/device/tests/conftest.py`); `machine` is globally mocked there.
- `restore.py`'s "never raises" rule is absolute — every new function runs
  under `boot.run()` / `manager.poll` with no `try` around it in the shipped
  scaffolds.
- Keep `commit()` and `filecopy._commit` separate (sub-task 1 note) — this
  spec does not touch either.
- The flat `files` list shape in `_run_default_update_loop` is unchanged;
  `commit()` is not modified here.
- Sub-task 1 dev log: `docs/development/failsafe-update-retain-previous-log.md`
  (HIL findings F-04/F-05/F-06 and the `_canonical` path fix live there).
- `otampy upd`'s post-commit reconnect must tolerate the device being
  briefly absent — reuse the retry shape of the existing `READY` wait loop
  (`update()` around line 2273), not a single `_send_command`.
- `test_command_auth_contract.py` pins the HMAC primitives, not a command
  enumeration — the new commands need nothing there. Do check
  `test_manager_auth.py` for a fixed accepted-command list before assuming the
  same.
- **Do not HIL-deploy between steps 5 and 8.** After step 5 the device
  trial-counts, but no CLI path sends `CONFIRM` until step 8 — an update driven
  by a mid-build CLI would auto-roll-back after `OTA_TRIAL_BOOTS` power cycles.
  HIL verification is end-of-sub-task, as in sub-task 1.
