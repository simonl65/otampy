# Trial boot, health confirmation, auto-restore — dev log

Narrative record for `docs/development/failsafe-update-trial-boot-spec.md`
(sub-task 2 of **Fail-safe Updates**). Sub-task 1's log, including the HIL
findings F-04/F-05/F-06 and the `_canonical` path fix, is in
`failsafe-update-retain-previous-log.md`.

Branch: `feature/failsafe-update-trial-boot`.

---

## Step 1 — `read_journal` returns a `state` string (2026-09-09)

Replaced the `in_progress` bool with a three-valued `state` string so the
journal can distinguish "a commit is partway through" from "a committed
candidate is on trial" from "the candidate was confirmed". Sub-task 1 only
needed the first two, and encoded them as a bool; the trial-boot work needs
the third, and a bool cannot carry it.

**Choice worth recording:** a missing or empty journal now reads as
`state="confirmed"`, not `"trial"`. "Confirmed" is the state that makes every
downstream caller no-op — `trial()` will not count a device that has never
been updated, and `state()` reports it as stable. Reading absence as `"trial"`
would have made a factory-fresh device start counting boots against a
candidate that does not exist.

The fail-safe direction is unchanged from sub-task 1: an unrecognised line 1
still reads as `committing`, i.e. "restore everything". `confirmed` had to be
matched explicitly *before* the `int()` attempt, otherwise it would fall
through the `ValueError` branch and be misread as an interrupted commit —
which would restore the previous generation over a perfectly good confirmed
build on the next boot. That ordering is the one genuinely dangerous detail in
this step.

`boot._cleanup_orphaned_ota` reads `read_journal(core)[2]`; index 2 is still
the path list, so the F-04 orphan-sweep fix is unaffected. Re-verified rather
than assumed, as the spec asked.

**Evidence:** `uv run pytest src/otampy/device/tests/test_restore.py
src/otampy/device/tests/test_ota_boot.py -q` → 32 passed. `uv run ruff check .`
clean. `python3 .agents/scripts/pre_flight_check.py` → exit 0.

No hardware involved in this step — journal parsing is pure host-testable
logic. Per the spec's build note, HIL verification is end-of-sub-task and must
not happen between steps 5 and 8.

---

## Step 2 — `restore_all()` + `repair()` delegates to it (2026-09-09)

New `restore_all(core)` is the whole-set restore primitive: rename every
journalled `.bck` back over its target and then **remove the journal**. This is
a real behaviour change from sub-task 1, where the `committing` branch of
`repair()` flipped line 1 to `0` and kept the journal. The old behaviour left
a spurious `trial`-state journal behind after a reversal, which would then have
started trial-counting a candidate that had just been rolled back. Removing the
journal is correct: once the previous generation is fully back there is nothing
on trial. Sub-task 3's `ROLLBACK` will reuse `restore_all()` directly.

`repair()` is now a three-way branch on `state`:

- `committing` → `restore_all()`, done.
- `trial` → restore only targets that vanished (a finished commit whose target
  was later lost), and rewrite the journal **only if** at least one file was
  restored. This is the F-07 fix, partial: a clean boot after a good update
  hits this branch, restores nothing, and does not touch flash.
- `confirmed` / empty → no-op.

F-07 is not closed yet — its other half (the `trial()` counter also writing
on-change only) lands in step 4. Left `open` in the ledger until then.

Two `test_ota_boot.py` assertions moved: an interrupted-commit boot now leaves
**no** journal (`state` reads back as `confirmed`), where before it left a
`trial` journal.

**Evidence:** `test_restore.py` + `test_ota_boot.py` → 34 passed. `ruff check`
clean. Pre-flight → exit 0.

---

## Step 3 — `restore.confirm()` and `restore.state()` (2026-09-09)

Both are thin reads over `read_journal` plus at most one `write_journal`.

`confirm()` returns `False` **only** when a `committing` marker is present — a
commit is mid-flight and confirming would strand it. Every other state
(`trial`, `confirmed`, no journal) returns `True`; only `trial` actually
writes. This keeps the host/app `CONFIRM` command idempotent and safe to
retry.

`state()` collapses to two labels for the wire: `("trial", n)` or
`("stable", 0)`. A stray `committing` maps to `("trial", 0)` defensively — it
should never be observed at runtime because `boot.run()` calls `repair()`
(which clears it) before anything answers `UPDATE_STATE`.

Added `_LABEL_STABLE = "stable"`; the trial label reuses `_STATE_TRIAL` since
the strings are identical.

**Evidence:** `test_restore.py` → 26 passed. `ruff` clean. Pre-flight → exit 0.

---

## Step 4 — `restore.trial()` (2026-09-09)

The per-boot counter. Reads the journal; if a candidate is on trial,
`attempt += 1`. Once `attempt` **exceeds** `OTA_TRIAL_BOOTS` (default 3, via
`_get_config`), it calls `restore_all()` and returns `_ROLLED_BACK` so
`boot.run()` (step 5) knows to `machine.reset()` onto the restored generation.
Otherwise it persists the new count and returns `None`.

Boundary chosen per the contract: `> limit`, not `>= limit`. With
`OTA_TRIAL_BOOTS=3` the candidate gets boots 1, 2, 3 to prove itself, and the
4th boot into it triggers the rollback. The warning logs `attempt - 1` (the
number of *completed* failed boots).

`_get_config` is left uncast (matches `boot.py:101`'s `OTA_TIMEOUT_MS` read) —
`configota.py` is Python so the value is already an int; pyright flags a
theoretical `None` but that only happens if a user explicitly sets the key to
`None`, same exposure as every other numeric config key.

**F-07 fixed** (steps 2 + 4): with `trial()` also writing on-change only, a
normal stable boot now touches flash zero times for the journal. Marked
`fixed` in the ledger — re-review at `/sl-findings review` before it closes.

**Evidence:** `test_restore.py` → 29 passed. `ruff` clean. Pre-flight → exit 0.

---

## Step 5 — wire `trial()` into `boot.run()` (2026-09-09)

One block added straight after `repair(core)`: `trial(core)`, and on
`_ROLLED_BACK` log a warning, `import machine`, `machine.reset()`, `return`.

The `return` matters in tests only — `machine` is a module-global `MagicMock`
(`conftest.py`), so `machine.reset()` does nothing and execution would fall
through into the flag-file check without it. On hardware the reset never
returns. Pyright now marks the post-`reset()` line unreachable, which is
correct for the hardware path; left as-is.

`_ROLLED_BACK` is imported alongside `repair`/`trial` in the existing local
`from .restore import ...` so `restore` stays GC-eligible with `boot`.

New boot tests use `import machine` + `machine.reset.reset_mock()` at the top
of each (the mock is process-global, like `test_manager_auth.py` already
does).

**Do not HIL-deploy now** — per the spec, the device trial-counts after this
step but nothing sends `CONFIRM` until step 8, so a mid-build CLI update would
auto-roll-back after `OTA_TRIAL_BOOTS` power cycles.

**Evidence:** `test_ota_boot.py` → 17 passed. `ruff` clean. Pre-flight → exit 0.

---

## Step 6 — `manager.poll` — `CONFIRM` and `UPDATE_STATE` (2026-09-09)

Two `elif` branches after `UPDATE_REQUEST`, each with a per-command
`from .restore import ...` so `manager` import stays light — the lazy-load
facade test (`test_package_import_does_not_eagerly_load_operating_modes`)
still passes.

`CONFIRM` → `CONFIRM_OK` / `CONFIRM_ERR` (ERR only when `restore.confirm()`
returns `False`, i.e. a commit marker is present). `UPDATE_STATE` →
`STATE_OK:<label>:<attempt>`, formatted from `restore.state()`.

Checked `test_manager_auth.py` per the spec note: auth is envelope-based and
command-agnostic — there is no fixed accepted-command list, so the two new
commands need nothing there. `PROTOCOL_VERSION` unchanged (channel 0 only,
no wire-format change).

Neither command resets the board, so neither calls `_persist_replay_floor`.

**Evidence:** `test_ota_manager.py` + `test_ota_facade.py` → 46 passed.
`ruff` clean. Pre-flight → exit 0.

---

## Step 7 — `ota.confirm()` facade (2026-09-09)

Three lines: local `from .restore import confirm`, `return confirm(self._core)`,
docstring pointing at the "call after your own health check" use. Mirrors
`ota.recover()`'s shape exactly.

**Evidence:** `test_ota_facade.py` → 9 passed. Pre-flight → exit 0.

---

## Step 8 — `otampy upd` auto-confirm (2026-09-09)

New `--no-confirm` flag on `upd`, and a `_post_commit_confirm(ctx, no_confirm)`
call after the transfer `try/finally` closes its serial session (so the
confirm phase opens a fresh link, as `_query` does for every other command).

The confirm phase is threaded through `_update_files(..., no_confirm=...)` —
the `try/finally` lives in `_update_files`, not `update()`, so `no_confirm`
has to be passed down. Both `_update_files` call sites and the three
`update_files.assert_called_once_with(...)` tests updated for the new kwarg.

Default path: print "Waiting for the updated device to answer...", loop
`_query(PING, PONG)` until it succeeds or `update_ready_timeout_seconds`
wall-clock elapses, then `_send_command(CONFIRM, CONFIRM_OK)` and
"Candidate confirmed." On timeout: `raise click.ClickException` with a
message naming the auto-rollback consequence — non-zero exit. `_query`'s own
internal 3-attempt retry means each PING poll already spans several seconds
of real reconnect time on hardware; the outer wall-clock check bounds the
total wait.

`--no-confirm`: one yellow line explaining the candidate is on trial and how
to confirm it, then return.

Five existing full-session `upd` tests grew `b"PONG", b"CONFIRM_OK"` on the
end of their `read.side_effect`. Two new tests: `--no-confirm` sends no
`CONFIRM` and exits 0; a candidate that never PONGs exits non-zero with
"NOT confirmed" (uses a fake `time.time` clock so the timeout branch is hit
without real waiting).

**Do not HIL yet** — steps 9–11 still pending; HIL is end-of-sub-task.

**Evidence:** `tests/test_cli.py` + `src/otampy/device/tests/` → 425 passed.
`ruff` clean. Pre-flight → exit 0.

---

## Step 9 — `otampy confirm` and `otampy state` commands (2026-09-09)

Two small `@cli.command`s modelled on `ping` / `rtc`:

- `confirm` → `_send_command(CONFIRM, CONFIRM_OK)`, `DeviceError` via
  `_handle_device_error`.
- `state` → `_query(UPDATE_STATE, STATE_OK)`, split the `<label>:<attempt>`
  payload, print "Candidate on trial (boot N) ..." or "Running a confirmed
  (stable) build."

**Evidence:** `test_cli.py -k "confirm or state"` → 4 passed. Pre-flight → exit 0.

---

## Step 10 — `main.py` scaffolds document `ota.confirm()` (2026-09-09)

A commented block after `ota.recover()` in both `examples/main.py` and
`examples/shared-uart/main.py`, explaining the trial window and showing
`# ota.confirm()`. No behavioural change — the scaffold still relies on host
`CONFIRM`. New `test_main_scaffold_mentions_confirm` guards both.

**Evidence:** `test_examples.py` → 16 passed. Pre-flight → exit 0.
