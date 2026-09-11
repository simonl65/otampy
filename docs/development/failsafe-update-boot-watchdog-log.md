# Feed a caller-supplied watchdog inside the boot-time recovery window — dev log

Spec: `docs/development/failsafe-update-boot-watchdog-spec.md`
Branch: `feature/failsafe-update-boot-listen`
Closes: F-12 (P2)

## 2026-09-11 — build start

**Branch decision.** Built on `feature/failsafe-update-boot-listen` rather than
a fresh `git flow feature start`. Sub-task 5's work (F-10/F-13/F-14/F-15/F-18)
is complete but not yet merged into `develop`, and this change edits the same
`_run_boot_listen`. Branching off `develop` would have built against a version
of that function which no longer exists. Simon chose this at the branch gate.

**Sequencing risk cleared.** The spec's first listed risk asked that the build
wait until sub-task 5's HIL step 7 closed, so a HIL failure there could not be
confused with a regression from this change. Checked before starting: step 7 is
ticked in `failsafe-update-recovery-handshake-spec.md`, and F-10, F-13, F-14,
F-15 and F-18 are all `closed` as of 2026-09-11. The risk has resolved on its
own; no wait needed.

**Ledger state at build start.** Open findings: F-12 (P2 — the one this spec
closes) and F-08 (P2, frozen-`restore.py`, unrelated area). No open or fixed
P0/P1, so nothing blocks the merge ahead of this work.

**Noted divergence between TODO.md and the spec.** `TODO.md`'s "Decided
direction (2026-09-11)" says "let `OTA` take a caller-supplied watchdog
object... Changes `OTA`'s constructor signature". The approved spec instead adds
an optional `heartbeat` callable to `OTA.boot()`, reusing `OTA.poll()`'s
existing contract verbatim and leaving the constructor untouched. The spec is
the later and reviewed artefact and is what is being built; the TODO line is
stale and is corrected at hand-off. Recorded here because the difference is
material — the spec's version is backward compatible with every existing
`OTA(...)` call site, the TODO's version would not have been.
