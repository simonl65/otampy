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
