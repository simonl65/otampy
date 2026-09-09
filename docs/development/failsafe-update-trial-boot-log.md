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
