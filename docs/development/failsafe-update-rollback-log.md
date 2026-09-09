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

## 2026-09-09 — step 3

- Extracted `_post_commit_confirm`'s `while True: _query(PING)` loop into
  `_wait_for_pong(ctx, timeout_message)`. Same behaviour; the timeout text is
  built by the caller (keeps the `{timeout:.0f}s` value) and passed in.
- `uv run pytest tests/test_cli.py -q` → 123 passed (unchanged). The retry loop
  now appears once in cli.py. ruff clean.

## 2026-09-09 — step 4

- `otampy rollback`: red `click.confirm` prompt; on decline prints `Aborted.`
  and sends nothing. Else `_query(ctx, b"ROLLBACK", b"ROLLBACK_")` -> on an
  `ERR` payload prints the device's reason in red and `SystemExit(1)`; on `OK`
  calls the shared `_wait_for_pong` with a rollback-specific timeout message,
  then reports the device is on the previous (stable) version.
- 4 tests in tests/test_cli.py: revert+PONG, nothing-to-revert (exit 1, no
  PING after), decline (nothing sent), never-answers (non-zero + message).
- `python3 .agents/scripts/pre_flight_check.py` -> READY FOR COMMIT (ruff +
  full pytest, mirrors CI). ruff format folded one over-long assert in the
  step-2 manager test.

## 2026-09-09 — step 5 (docs)

- `docs/protocol.md`: `ROLLBACK` row in §2.1 and §2.4 (all three responses);
  the trial-boot lifecycle paragraph now describes the shipped `otampy
  rollback`, that it needs the poll loop, and the one-generation / one-shot
  limit. "(planned)" removed.
- `docs/architecture.md`: paragraph under "Trial boot, confirmation, and
  auto-restore" covering the user-initiated revert and its one-shot nature.
- `CHANGELOG.md`: `Unreleased` bullet under the trial-boot block.
- `TODO.md`: sub-task 3 ticked.
- `python3 .agents/scripts/pre_flight_check.py` -> READY FOR COMMIT.

All 5 build steps done. Ledger: F-08 (P2, open) untouched and out of scope
(sub-task 4) — no P0/P1 open. Hardware HIL tests 1–4 pending (Simon, end of
sub-task).

## HIL — 2026-09-09

Rig: Pico W on `/dev/ttyACM0` (raw provisioning), XBee gateway on
`/dev/ttyUSB0` (OTA, default port). diff-drive-robot services stopped.
Simon deployed the branch (`otampy deploy -p /dev/ttyACM0`); `otampy` is an
editable install so `lib/otampy` carried the branch's `restore.py` /
`manager.py`. Device config `OTA_TRIAL_BOOTS = 3`, no auth.

Baseline after deploy: `ping` -> PONG; `state` -> "Running a confirmed
(stable) build"; `ls /` -> `boot.py configota.py lib/ logs/ main.py` (no
`.bck`, no journal). Candidate v2 = `examples/main.py` + a `# [HIL-ROLLBACK-V2]`
marker line 1, sent as `<scratch>:main.py`.

| Test | What it proves | Result |
| --- | --- | --- |
| 1. Revert a confirmed candidate | a confirmed, `.bck`-retained update reverts over the radio | **PASS** — `otampy upd v2` auto-confirmed (`state` -> stable, journal `confirmed`+`/main.py`, `main.py.bck` present, `/main.py` has the marker). `otampy rollback` -> prompt, "Rollback complete. The device is running the previous (stable) version." Then: `/main.py` marker **gone**, `ls /` **no `main.py.bck`, no `otampy-update.journal`**, `state` -> stable, `cat /otampy-update.journal` -> "No such file or directory". |
| 2. Second rollback refuses without rebooting | nothing-to-revert is a clean no-op | **PASS** — immediate second `otampy rollback` -> `Rollback refused: Nothing to roll back`, process **exit 1** (verified without a masking pipe); `otampy ping` answered PONG in ~2.3 s (XBee handshake only, no reboot delay). |
| 3. Revert an unconfirmed candidate | a trialling candidate is abandoned, not paused | **PASS** — `otampy upd --no-confirm v2` -> `state` "Candidate on trial (boot 1)", journal line 1 `1` + `/main.py`, marker present. `otampy rollback` -> marker gone, `state` -> stable, `ls /` no `.bck`/journal. |
| 4. Replay floor survives the rollback reset | `_persist_replay_floor` runs before `machine.reset()` | **NOT RUN** — device `configota.py` has no `OTA_REQUIRE_AUTH`/`COMMAND_AUTH_KEY`; covered by `test_manager_auth.py::test_a_signed_rollback_persists_the_floor_before_resetting` (floor written at counter 4242 before the mocked reset). Deferred pending an auth-configured device.

### Outcome

HIL tests 1–3 (Simon's signed-off manual bar) pass. `ROLLBACK`'s
`machine.reset()` fired as designed on both the confirmed and the trial path:
the device came back on the restored generation with journal + `.bck` gone,
no REPL, no manual recovery, reachable over the gateway. Device left clean:
`/main.py` byte-identical to `examples/main.py` (= `develop` HEAD, no `main.py`
change on this branch), no journal, no `.bck`, `state` -> stable. Test 4
carried by the host unit test until an auth-configured rig is available.
