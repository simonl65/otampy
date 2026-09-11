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

## 2026-09-11 — build complete

All three build steps done, each committed separately on the branch.

**Step 1** (`e075496`) — `_call_heartbeat` moved `manager.py` -> `core.py`;
`_run_boot_listen` feeds it. The placement claim was not taken on trust: I
moved the call into the idle branch, re-ran, and confirmed
`test_boot_listen_feeds_heartbeat_while_refusing_a_chatty_peer` fails there and
passes at top-of-body. The spec predicted exactly that, and it held.

**Step 2** (`2a3b514`) — `_run_default_update_loop` fed; `heartbeat` threaded
through `boot.run()` and `OTA.boot()`; `_UPDATE_LOOP_POLL_MS` names the
previously hardcoded idle sleep.

**Step 3** — `configota.example.py`, both `examples/boot.py` scaffolds,
`docs/protocol.md` §2.4, `docs/architecture.md`, `CHANGELOG.md`.

### Two things worth remembering

**A wrong-arity heartbeat fails completely silently.** My first draft of the
step 1 tests passed `feeds.append` as the heartbeat. The contract is a
*zero-argument* callable, so every call raised `TypeError` — and
`_call_heartbeat` swallows all exceptions by design. Result: zero feeds, no
log line, no symptom, while the test's other assertions still passed. That is
exactly what a real integrator gets if they pass a callable with the wrong
signature: the watchdog is never fed, the device resets mid-window, and
nothing anywhere says why. The swallow is correct — a heartbeat must never
abort a transfer — but it is undetectable when the *caller* is the thing that
is wrong. Worth considering as a finding in its own right; the reasoning is
pinned in the `_Feeds` docstring in `test_ota_boot.py` so the next person does
not rediscover it the same way.

**The spec's "suites still pass unmodified" could not be satisfied.** Three
existing tests assert the mock call signature (two
`mock_boot_run.assert_called_once_with(ota._core, None)`, plus `_window_spy`'s
two-parameter `spy()`). `OTA.poll()`'s precedent is to pass the keyword
always, and step 2's own `test_ota_boot_heartbeat_defaults_to_none` asserts
`heartbeat=None` *is* passed — so the two requirements were mutually
exclusive. Followed the `poll()` precedent and corrected the spec's Done-when
in place. No test's meaning was weakened; only call-signature assertions moved.

### Not done, deliberately

No HIL run. The spec calls hardware verification unnecessary here and the
reasoning holds: `heartbeat` defaults to `None`, so with no caller supplying
one, every code path is byte-for-byte the behaviour already HIL-proven under
sub-task 5. The window's duration is untouched. Simon's optional bench check
(a real `WDT(8388)` plus `heartbeat=wdt.feed` surviving a full wide window)
remains available as confidence-building, not as a gate.
