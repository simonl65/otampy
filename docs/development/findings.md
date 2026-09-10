# Findings ledger

Durable record of code-review findings. IDs are permanent and never reused.
See `~/.claude/skills/sl-findings` for the process.

Gate rule: an **open** or **fixed** P0/P1 blocks a merge. P2/P3 do not.

---

## Open / fixed

### F-13 — `test_rollback_recover_times_out_with_recovery_wait_message` passes on a validation error and never reaches the path it names

- **Severity:** P2
- **Status:** open
- **Area:** `tests/test_cli.py`
- **Found:** 2026-09-10, while writing the F-11 tests — the same `"0"` trick
  failed for me with `post-commit-ready-timeout must be greater than 0.`,
  which prompted a check of the existing test using it.
- **Evidence:** the test sets `OTAMPY_RECOVERY_WAIT=0`, but
  `_coerce_config_value` (`cli.py:369-372`) rejects any non-`query_retries`,
  non-`transfer_chunk_size` value `<= 0`. Reproduced directly: the command
  exits 1 with output `Error: recovery-wait must be greater than 0.` and
  nothing else. The test's two assertions — `result.exit_code != 0` and
  `"recovery-wait" in result.output` — are both satisfied by that error
  message, so it passes without the `--recover` retry loop ever running.
- **Impact:** `rollback --recover`'s recovery-wait expiry path has no test
  coverage while appearing to have some, which is worse than none. That path
  is in F-10's blast radius: the operator-facing message on a failed radio
  recovery is exactly what a stranded-device session depends on. A regression
  there would ship green.
- **Resolution:** _(not yet fixed — needs a positive-but-tiny wait, e.g.
  `0.001`, as the F-11 tests now use, plus an assertion on the actual
  timeout wording rather than the bare key name. Check the sibling
  `--recover` tests for the same pattern while there.)_
- **Closed:** _(pending)_

---

### F-12 — the 8000 ms wide recovery window overruns an 8388 ms watchdog armed before `OTA(...).boot()`, and nothing feeds it

- **Severity:** P2 — **upgrade to P1 if any integrator actually arms a
  watchdog before `OTA(...).boot()`.** Filed P2 because the affected
  configuration is optional and was not exercised on the rig: no watchdog was
  armed, so the reset was never observed. The measurement and the code path
  are confirmed; the resulting reset loop is inference from them.
  The margin is worse than first filed — see the logging-overhead correction
  under **Evidence**: the 8899 ms span is clean as measured, not inflated, so
  the configured `8000` really does overrun 8388 on its own.
- **Status:** open
- **Area:** `src/otampy/device/lib/otampy/boot.py` (`_run_boot_listen`, and the
  window selection in `run()`); `src/otampy/device/examples/configota.example.py`
  (the `OTA_BOOT_RECOVERY_LISTEN_MS` guidance)
- **Found:** 2026-09-10, during step 5 HIL instrumentation of
  `failsafe-update-window-reachability-spec.md`. Not the thing being tested —
  surfaced by Simon asking how the F-11 fix would interact with a watchdog.
- **Evidence:** `configota.example.py:29` tells the integrator to "keep this
  under your watchdog period if a custom `boot.py` arms one before
  `OTA(...).boot()`: 8000 is just under the RP2040's ~8388 ms cap", and the
  spec's risk section chose `8000` for exactly that reason. Device-side ticks
  measurement contradicts it. In `boot.py:614-652` the log lines `Checking for
  update flag-file...` and `update_requested.flag not found` bracket
  `state(core)` plus `_run_boot_listen()`; on a wide-window boot they were
  **1454 ms** and **10353 ms**, a blocking span of **8899 ms** for a configured
  `8000` — already past 8388 on its own, before adding the 1454 ms taken to
  reach the window. Nothing feeds a watchdog anywhere in that span: the device
  library has no WDT awareness at all, and `manager.py:85`/`manager.py:119`
  deliberately place watchdog feeding on the caller, once per `poll()` —
  which `boot()` never calls.
  Raw log in `docs/development/failsafe-update-window-reachability-log.md`
  (2026-09-10, step 5 run 1).
  **On logging overhead (corrected 2026-09-10, after first filing):** the
  figures were taken at `LOG_LEVEL = "DEBUG"`, and this entry initially
  discounted them as inflated by flash writes, with "a clean figure at
  `LOG_LEVEL = \"ERROR\"`" listed as owed. That was wrong twice over, and the
  correction strengthens the finding rather than weakening it.
  First, `_run_boot_listen`'s idle path (`boot.py:432-435`) is
  `read()` → `_sleep_ms(_BOOT_LISTEN_POLL_MS)` → `continue`, with **no
  `logger` call at all**; the only logging in the body is on anomalies (a
  non-UTF-8 packet, a matched command). On an idle window — which is every
  window that is not being actively recovered, including the one measured —
  the interior of the 8899 ms span contains **zero** DEBUG writes. The span is
  therefore essentially clean as measured: the ~899 ms of excess over the
  configured `8000` is `state(core)`'s journal read, loop granularity, and the
  flush of the bracketing log line, not logging inside the window.
  Second, a figure at `LOG_LEVEL = "ERROR"` is not obtainable anyway — both
  bracketing lines are `logger.debug`, so at `ERROR` the measurement
  disappears entirely. Any re-measurement needs a different technique
  (temporary `print()` instrumentation, as the 2026-09-10 root-cause run
  used), and is no longer needed to establish this finding.
- **Impact:** An integrator arming `WDT(8388)` before `OTA(...).boot()` is
  reset part-way through every wide-window boot. The device that qualifies for
  the wide window is by definition the stranded one, so the inferred dynamic is
  a loop: boot → marker/`trial` → wide window → WDT reset at 8388 ms → boot →
  … never reaching `main.py`. Recovery may still succeed by luck, since a WDT
  reset does not power-cycle the XBee and the radio is warm on the second pass
  (F-10's control measurement: first packet 80 ms into the window after a
  software reset). Untested either way. The confirmed part is narrower and
  still real: shipped configuration guidance makes a promise the shipped
  default cannot keep.
- **Resolution:** _(not yet fixed — design work, not a repair. Candidate
  shapes: lower the default wide window to fit 8388 including pre-window boot,
  which spends recovery margin that F-10 already called the tightest number in
  the spec; document a pre-`boot()` watchdog as incompatible with the wide
  window; or let `OTA` take a caller-supplied watchdog and feed it inside
  `_run_boot_listen`'s read loop. The third keeps both the wide window and
  boot-path WDT cover and has a natural feed point, but it changes the `OTA`
  constructor signature, so it needs a spec.)_
- **Closed:** _(pending)_

---

### F-11 — the wide recovery window pushes the post-commit boot past `upd`'s 10 s health check, so every successful update reports failure

- **Severity:** P1
- **Status:** fixed (awaiting re-review) — 2026-09-10, step 6 of
  `failsafe-update-window-reachability-spec.md`
- **Area:** `src/otampy/cli.py` (`_post_commit_confirm`, `_wait_for_pong`,
  `update_ready_timeout_seconds` at `cli.py:61`); consequence of the window
  selection in `src/otampy/device/lib/otampy/boot.py` `run()`
- **Found:** 2026-09-10, step 5 HIL verification of
  `failsafe-update-window-reachability-spec.md`. Hit on the first `otampy upd`
  of the session — a routine config push, not a test.
- **Evidence:** A post-commit boot has journal `trial`, so `boot.py:646-651`
  selects the **wide** window by design. Device-side ticks on that boot put
  `Loading MAIN...` at **10661 ms** and `Application main loop started` at
  **11044 ms**. `_post_commit_confirm` (`cli.py:2704`) waits
  `update_ready_timeout_seconds`, default **10.0** (`cli.py:61`), timed from
  the commit reply. The device cannot win that race. Observed:
  `Update completed successfully! Device is rebooting.` →
  `Error: Update committed but the device did not come back healthy (no PONG
  within 10s).` — followed immediately by a successful `otampy ping`, an
  `otampy state` of `Candidate on trial (boot 1)`, and a normal
  `otampy confirm`. The device was never unhealthy.
  Raw log in `docs/development/failsafe-update-window-reachability-log.md`
  (2026-09-10, step 5 run 1).
  **Not a radio-flake observation**, despite being seen once over the link: the
  corroborating measurement is device-side `ticks_ms` from `/ota.log`,
  independent of the radio, and the arithmetic is structural — 8 s of window
  plus ~1.4 s of pre-window boot plus ~0.7 s of startup against a 10 s budget.
  Any device at the shipped default loses.
- **Impact:** Every successful default `otampy upd` reports failure and leaves
  the candidate unconfirmed. It self-heals if the operator runs
  `otampy confirm`, but the primary update path tells the operator their update
  failed when it did not — and an operator who believes the error and
  re-deploys does so against a device already on trial boot 2 of 3.
  `_wait_for_pong` is shared with `otampy rollback` (`cli.py:2663`), whose
  post-restore boot has also not polled and so also carries the marker and
  selects the wide window; the same arithmetic applies there, untested.
  This also blocks step 5 of the active spec outright: HIL test 2's required
  evidence is literally `COMMIT_OK`, then `Candidate confirmed.`, which cannot
  currently occur.
- **Resolution:** 2026-09-10 — added the `post_commit_ready_timeout_seconds`
  config key (display `post-commit-ready-timeout`, env
  `OTAMPY_POST_COMMIT_READY_TIMEOUT`, default `30.0`) at `cli.py:68`.
  `_wait_for_pong` and both of its callers — `rollback` (`cli.py:1401`) and
  `_post_commit_confirm` (`cli.py:2721`) — now read it instead of
  `update_ready_timeout_seconds`. The READY-broadcast wait keeps the old key:
  that boot has the update flag set, so `run()` opens no window at all.
  Five tests in `tests/test_cli.py` (default/env override, `config --show`
  display, retries past the old timeout, gives up on the new one, and the
  rollback message quoting the new value), all red beforehand.
  **Hardware evidence:** a real `otampy upd` over the XBee gateway printed
  `Update completed successfully! Device is rebooting.` →
  `Waiting for the updated device to answer...` → `Candidate confirmed.`
  with no manual `otampy confirm`. Same command failed at the same point
  before the change.
  _(Original agreed approach 2026-09-10, unchanged in implementation. Rejected: raising
  `update_ready_timeout_seconds` globally, which is used in four places and
  would triple the time every unrelated failure takes to report; and narrowing
  the `trial -> wide` selection rule, which would re-open F-10 — that boot is
  precisely the one that needs radio recovery if the candidate bricks the
  application.)_
- **Closed:** _(pending)_

---

### F-10 — the boot-time recovery window is unhittable in practice: it opens at t+2.05 s, before the power-cycled XBee is awake

- **Severity:** P1
- **Status:** open — **root-caused 2026-09-10, fix not yet designed.** The
  original title/diagnosis (host blind-retry cadence) was wrong; the cadence
  fix was necessary housekeeping but never the binding constraint. See
  "Root cause established 2026-09-10" below. The fix is a spec-level decision
  (it falsifies Protocol decision D2), not a patch.
- **Area:** `src/otampy/cli.py` (`_recover_query`, and the `_query` /
  URST-handshake path it drives); interacts with
  `src/otampy/device/lib/otampy/boot.py` `_run_boot_listen` (`OTA_BOOT_LISTEN_MS`,
  default 1000)
- **Found:** 2026-09-09, HIL verification of sub-task 4. `otampy rollback
  --recover` against a genuinely stranded device (fatal `main.py`, no watchdog),
  operator power-cycling on the prompt: **0 hits in 2 attempts**, each a full
  60 s `recovery-wait` expiry. The device was then recovered by trial-boot
  auto-restore, not by the window.
- **Evidence:** `urst.constants` — `MAX_RETRIES = 3`, `ACK_TIMEOUT_MS = 1000`.
  A CONNECT handshake against an **absent** peer runs `MAX_RETRIES + 1 = 4`
  attempts × 1000 ms ≈ **4 s**. `_query` retries that `query_retries = 3`
  times ≈ **12 s per call**. `_recover_query` loops `_query` with only a
  0.05–0.25 s backoff between calls, so the host puts a fresh CONNECT on the
  wire roughly **once every 12 s**. `_run_boot_listen`'s window is **1 s per
  boot** (`OTA_BOOT_LISTEN_MS` default 1000, 10 ms poll). Per-power-cycle hit
  probability ≈ 1 s / 12 s ≈ **8 %**; expected power cycles to recover ≈ 12.
  Observed 0/2 is consistent with that, not with variance.
- **Impact:** The headline capability of sub-task 4 — recover a device stranded
  before `ota.poll()` over the radio with no USB — does not work in practice.
  An operator following the CLI's own instructions ("power-cycle when
  prompted") would give up long before landing a command. HIL tests 1, 2, 5
  and 6 all depend on a command reaching the window and cannot pass until this
  is fixed. The window code itself (`_run_boot_listen`) is correct: it polls
  every 10 ms and would answer any CONNECT inside the second — the fault is
  that the host never sends one fast enough.
- **Suggested fix (host-side):** `_recover_query` should drive `_query` (or a
  dedicated fast path) with a **fail-fast transport** — 1 handshake attempt,
  short ACK timeout (~100–150 ms), no inner `query_retries` — so it emits many
  CONNECTs per second and reliably catches a 1 s window. The retry loop, not
  the per-attempt timeout, is what should span `recovery_wait_seconds`. A
  device-side-only mitigation (larger `OTA_BOOT_LISTEN_MS`) trades directly
  against the per-boot cost the spec set out to minimise and is not the right
  lever. The signed-off Protocol decision that dropped the `RECOVERY` beacon
  in favour of "silent window + host blind-retry" (spec §"Protocol decision" /
  D2) should be revisited in light of this: blind retry is viable, but only if
  the host retries an order of magnitude faster than it does today.
- **Fix applied (2026-09-09, step 9 + follow-on):** `_recover_query` now runs
  its poll under `_fast_recovery_handshake()` (`urst.constants.ACK_TIMEOUT_MS`
  1000 → 500, `MAX_RETRIES` 3 → 0, restored on exit) and calls
  `_query(fast=True)` — single attempt, no `query_retries` loop, no backoff,
  and a small serial read timeout (`_RECOVERY_SERIAL_TIMEOUT = 0.1`) threaded
  through `_open_transport` so an absent port returns in ~ms not the default
  2 s. Host CONNECT cadence measured in HIL went from ~1 per 12 s to ~1.2 per
  second. Verified by unit tests.
- **HIL re-test 2026-09-09 — still fails.** Three runs against a stranded
  device (`ACK_TIMEOUT` 120/500, various serial timeouts), operator
  power-cycling: **0 `CONNECT_ACK` in 48–108 host attempts per run**, every
  run a full recovery-wait timeout. A `connect()` against the *healthy* device
  measures ~81 ms, so the link is fast and 500 ms is not too tight — yet the
  boot-time window never answers a single CONNECT. So the host cadence was
  necessary but is **not sufficient**; there is a second cause, on the device
  side or in how the retry pattern hits the XBee:
  - Simon (hardware): XBees dislike back-to-back sends — they need a gap of
    ~30 ms between frames or they buffer/drop. The current loop reopens the
    serial port every cycle (toggling DTR/RTS on an FTDI→XBee) and re-sends
    CONNECT ~1.2×/s; that open/close churn, not just the CONNECT spacing, may
    be upsetting the module right when the freshly-booted device needs it
    quietest.
  - Device side unverified: `_run_boot_listen` calls `core.transport.read()`,
    which blocks up to the *device's* `ACK_TIMEOUT_MS` (1000) per call, so the
    ~1 s window may execute only one or two `read()` calls. Whether a CONNECT
    that lands mid-window actually gets its `CONNECT_ACK` out before the
    deadline needs on-device instrumentation to confirm.
- **Next (fresh session):** ~~(1) add temporary logging...~~ **Done — see
  below. Steps (2)/(3) are moot: the host retry pattern is not the fault.**
- **Root cause established 2026-09-10 (HIL, on-device instrumentation).** The
  window opens at a strikingly consistent **`ticks_ms` ≈ 2050–2170** after
  power-on and listens for its full second (`elapsed ≈ 1017`), i.e. it is open
  from about **t+2.05 s to t+3.15 s**. After a *power cycle* the XBee loses
  power too, and the first frame it delivers to the device UART arrives at
  **t+3.6 s to t+8.7 s** — always after the window has shut. Measured with a
  15 s window: first packet at `ts=5704` on one boot, `ts=10885` (a `ROLLBACK`,
  which matched and successfully recovered the device) on another.
  **Control:** on a boot following a *software* `machine.reset()`, where the
  XBee never lost power, the first packet arrives at `ts=2275` — **80 ms**
  after the window opens. Cold radio vs warm radio is the entire effect.
- **Why the cadence theory was wrong:** the failure was always **100 %**, never
  probabilistic — 0/48, 0/93, 0/108, and 0/3 on a clean instrumented run. A
  race against a 1 s window at ~1.2 CONNECT/s would have landed something well
  inside 100 attempts. Total systematic exclusion means the window and the
  radio's readiness never overlap, which is why making the host retry 10×
  faster changed nothing measurable.
- **Retired lead:** "the ~1 s window may execute only one or two `read()` calls
  and miss a mid-window CONNECT" is **false**. `read()` blocks for the device's
  `ACK_TIMEOUT_MS` (1000 ms), so one call *is* a continuous full-window listen
  (`iters=15` over a 15 s window). The window code is correct as written.
- **Implication for the fix — spec-level, not a patch.** The prior "suggested
  fix (host-side)" and the dismissal of a larger `OTA_BOOT_LISTEN_MS` as "not
  the right lever" are both **backwards**: overlapping the radio's wake-up is
  the only lever that matters. This falsifies the premise of signed-off
  **Protocol decision D2** ("silent window + host blind-retry"): against a cold
  radio a short silent window cannot work however fast the host retries. The
  trade to settle is per-boot cost (a wide window delays `main.py` on *every*
  healthy boot) against recovery reliability — e.g. widen unconditionally,
  delay-then-listen, open a long window only when the journal shows an
  unconfirmed candidate, or revisit the dropped beacon. Needs `/sl-spec`.
- **First successful recovery:** with the window at 15 s, a genuinely stranded
  device (fatal `main.py`) was recovered over the radio by an in-window
  `ROLLBACK`, no USB — **HIL test 2 PASS**, the first in this saga. Confirmed
  healthy afterwards with `otampy ping` over the gateway.
- **Methodology traps found (both had been corrupting earlier evidence):**
  (a) `rollback --recover` against a *healthy* device proves nothing — the
  running `manager.poll` serves `ROLLBACK` and returns an identical reply, so
  the test must use a genuinely stranded device; (b) **every `mpremote`
  invocation soft-reboots the device on exit**, including `fs ls`/`fs cat`/
  `fs rm`, appending phantom window entries (recognisable by a large `ts`,
  since a soft reset does not clear `ticks_ms()`). Batch all device
  interaction into one `mpremote ... + ...` session and touch USB not at all
  between a run's power cycles.
- **Also noted:** `log_to_file` is not installed on the HIL device, so
  `core.logger` is a `NullLogger` — every `logger.*` call inside the window
  (and elsewhere in `boot.py`) currently goes nowhere on that rig.
- **Edge noted, not fixed:** if the in-window ROLLBACK lands and the device
  resets but its reply is lost, the CLI retries and then reports "Nothing to
  roll back" (exit 1) though the rollback actually succeeded. Pre-existing to
  the blind-retry design. `_wait_for_pong` still confirms real health.

### F-09 — `OTA.boot()` teardown crashes on every no-auth boot: MicroPython `delattr` raises `KeyError`, not `AttributeError`

- **Severity:** P0
- **Status:** fixed (awaiting re-review)
- **Area:** `src/otampy/device/lib/otampy/ota.py` (`OTA.boot()` `finally` teardown)
- **Found:** 2026-09-09, HIL verification of the boot-time recovery window
  (sub-task 4). Device was unreachable over the radio after a clean deploy of
  the branch; USB REPL showed `KeyError: authgate` from `ota.py` on every boot.
- **Evidence:** commit `b07b4e9` added `"authgate"` to the
  `for submodule in ("boot", "restore", "authgate")` teardown loop. `authgate`
  is imported by the recovery window **only when `OTA_REQUIRE_AUTH` is set**, so
  on a normal boot `device_otampy.authgate` is never an attribute of the
  package. CPython's `delattr(package, "authgate")` then raises
  `AttributeError` (caught); **MicroPython raises `KeyError`** (not caught by
  `except AttributeError`). The exception propagates out of `boot()`, through
  `boot.py`, so `main.py` never runs. Confirmed on device:
  `delattr(otampy, 'authgate')` → `KeyError('authgate',)`.
- **Impact:** Every device that deploys this branch **without** `OTA_REQUIRE_AUTH`
  is stranded on the next boot — boot.py crashes, `main.py`'s poll loop never
  starts, and the boot-time recovery window itself never opens (boot.py raises
  after it). USB-only recovery. This is the exact failure class the Fail-safe
  Updates epic exists to remove, reintroduced by its last sub-task. Host tests
  passed because they run on CPython.
- **Fix applied:** `except AttributeError` → `except (AttributeError, KeyError)`
  at the `delattr` call site (mirrors the `del sys.modules[...]` guard two
  lines up, which already catches `KeyError`). Regression test
  `test_boot_teardown_survives_micropython_delattr_keyerror` in
  `test_ota_facade.py` simulates MicroPython's `delattr` semantics.
- **Follow-up noted (not this finding):** `test_ota_facade.py`'s existing
  `test_boot_releases_boot_module_and_can_run_again` deletes
  `device_otampy.boot` from `sys.modules` without restoring it; under a
  `pytest-randomly` seed that orders it before `test_ota_boot.py` tests, those
  tests then patch a stale module and fail. Pre-existing, masked by
  alphabetical collection order. Worth a `TODO.md` item.

### F-08 — a power loss while updating `restore.py` itself strands the device with no radio recovery

- **Severity:** P2
- **Status:** open
- **Area:** `src/otampy/device/lib/otampy/` (`boot.run` and `ota.recover` both
  `from .restore import repair`)
- **Found:** 2026-09-08, `/sl-findings review` of the F-06 fix
- **Evidence:** F-06's fix (Option A) routes recovery through `main.py` so a
  lost `boot.py` self-heals. But the recovery *logic* is `restore.py`, imported
  lazily by both `boot.run()` (`boot.py`, local `from .restore import repair`)
  and `ota.recover()` (`ota.py`). `commit()` renames one file at a time, so an
  interrupt while `restore.py` is the current pair leaves
  `/lib/otampy/restore.py` absent with `restore.py.bck` present. On the next
  boot `boot.py`'s import raises `ImportError` (boot.py crashes, MicroPython
  proceeds to `main.py`); `main.py`'s `recover()` hits the same `ImportError`
  and crashes too. Device drops to the REPL — the `.bck` holds the code but
  nothing can rename it back.
- **Impact:** USB-only recovery if power is lost in the commit window *and* the
  update set includes `restore.py` — i.e. a library update (`otampy upd
  lib/otampy/...` or a full re-deploy), never a normal app update, so the
  trigger is narrow. Strictly smaller than the pre-retain-previous exposure,
  where any interrupted commit could brick the device and no `.bck` existed.
- **Suggested fix:** freeze `restore.py` into the deployed image, or F-06
  Option C (a frozen `_boot.py` that runs `repair()` before `boot.py`).
- **Not sub-task 4 (boot-time recovery window):** re-checked when that
  sub-task was built (2026-09-09). The window cannot fix F-08 —
  `boot.run()`'s `from .restore import ...` raises before the window would
  open, and the flagged update loop's `from .restore import clear_journal,
  commit` needs the same absent module. A real fix needs frozen code, so this
  is now tracked as its own `TODO.md` item ("Freeze `restore.py` / a recovery
  `_boot.py` into the deployed image") rather than parked on a sub-task that
  demonstrably cannot resolve it.

## Closed

### F-07 — `repair()` rewrites the journal on every call, now twice per boot

- **Severity:** P3
- **Status:** closed
- **Area:** `src/otampy/device/lib/otampy/restore.py` (`repair`)
- **Found:** 2026-09-08, `/sl-findings review` of the F-06 fix
- **Evidence:** `restore.repair()` ended with an unconditional
  `write_journal(core, ..., paths)` whenever the journal had any entries, even
  when it restored nothing and the marker did not change. After a successful
  update the journal persisted as `0\n/main.py\n...` until the next
  `UPDATE_START`, so it was rewritten on every boot — twice, since the F-06
  fix added `main.py`'s `recover()` → `repair()` as a second caller.
- **Impact:** Two small flash writes per boot indefinitely after any update.
  No behavioural effect.
- **Resolution:** `failsafe-update-trial-boot` steps 2 and 4.
  `repair.py:230` guards the trial-branch write behind a `restored` flag (only
  writes when a `.bck` was renamed back over a missing target);
  `repair.py:215-217` routes the `committing` branch through `restore_all()`,
  which *removes* the journal instead of rewriting it; and the new `trial()`
  returns early (`restore.py:262`) in every non-`trial` state, so a confirmed
  candidate does zero journal writes per boot. An unconfirmed candidate still
  gets a write per boot as `trial()` counts — but that is intentional,
  bounded to `OTA_TRIAL_BOOTS`, and self-terminating (rollback removes the
  journal); `otampy upd` confirms within seconds by default.
- **Closed:** 2026-09-09 by `/sl-findings review` — independent re-read of
  `restore.py` as it stands: no unconditional `write_journal` remains on any
  `repair()`/`trial()` path. Guard tests `test_repair_trial_all_targets_present_does_not_write`
  (write-count spy) and `test_trial_is_a_noop_when_confirmed` pass; no new
  defect introduced by the guard.

### F-06 — an interrupted `boot.py` commit strands the device: `repair()` lives in the file that got deleted

- **Severity:** P0
- **Status:** closed
- **Area:** `src/otampy/device/lib/otampy/` (`boot.run` / `restore` design;
  the shipped `main.py` scaffold)
- **Found:** 2026-09-08, HIL fault-injection of
  `feature/failsafe-update-retain-previous` (doctored `restore.py` with a 25 s
  wait loop on the last commit pair; Simon pulled power in the window).
- **Evidence:** `otampy upd main.py boot.py` was interrupted mid-commit, after
  `main.py` had fully committed and `boot.py` had been renamed to
  `boot.py.bck` but its `.ota` was not yet renamed into place. On the next
  boot, `otampy -p /dev/ttyUSB0 ls /` showed: **`boot.py` absent**,
  `boot.py.bck` + `boot.py.ota` present, `otampy-update.journal` =
  `committing` / `/main.py` / `/boot.py`, `update_requested.flag` still set.
  `otampy ping` returned `PONG` (the newly-committed `main.py` runs), but the
  `committing` state persisted across reboots — no self-repair.
- **Root cause:** `restore.repair()` is only ever invoked from `boot.run()`,
  i.e. from `boot.py`. `commit()` renames each target out to `<target>.bck`
  before renaming the staged copy in, so an interrupt while `boot.py` is the
  current pair leaves `boot.py` absent. MicroPython then boots straight to
  `main.py`, `boot.run()` never executes, and the journal/flag/`.bck` state is
  never resolved. The device is stuck on a mixed tree (new `main.py`, no
  `boot.py`) with no remote recovery path — exactly the "never destroy the only
  remote recovery path" invariant the Fail-safe Updates task exists to enforce.
- **Impact:** A normal-path power loss during any update whose set includes
  `boot.py` (every `otampy upd` with no args sends `boot.py`, `main.py`,
  `configota.py`) can strand a field device. Runtime commands still work while
  `main.py` runs, so recovery is possible over the radio via `otampy cp` — but
  only by luck (if `main.py` committed or was untouched); if the interrupt
  caught `main.py` instead, or `main.py` also fails, the device needs USB.
- **Blocks:** merge (P0). HIL cannot proceed past this.
- **Suggested fix (needs a design decision — see dev log 1-3-1):**
  - **A (recommended):** the shipped `main.py` scaffold also runs
    `restore.repair()` once at startup (or a new `OTA(...).recover()`). Since
    `commit()` touches one file at a time, at any interrupt point at most one of
    `boot.py`/`main.py` is absent, so the survivor heals the set. Smallest
    change; scaffold contract gains one line; a custom `main.py` must include it.
  - **B:** special-case `boot.py` in `commit()` to copy-into-place (never leave
    `boot.py` absent). Keeps recovery in `boot.py`; risks a truncated `boot.py`
    on a crash mid-write.
  - **C:** freeze a minimal recovery `_boot.py` (runs before `boot.py`) into the
    deployed image that calls `repair()` and chains on. Heaviest; needs a
    manifest/freeze change at deploy time.
- **Resolution:** 2026-09-08, `feature/failsafe-update-retain-previous` step 11
  (Option A). New `OTA.recover()` (`ota.py`) — a local-import
  `restore.repair(self._core)` plus removal of the stale update flag. Both
  `main.py` scaffolds call `ota.recover()` once after `ota = OTA(...)`, before
  the poll loop. `commit()` renames one file at a time, so at any interrupt at
  most one of `boot.py`/`main.py` is absent — the survivor heals the set; a lost
  `boot.py` is restored from `boot.py.bck` by `main.py`'s call. Tests:
  `test_ota_facade.py::test_recover_delegates_to_restore_repair`,
  `::test_recover_clears_the_stale_update_flag`,
  `tests/test_examples.py::test_main_scaffold_calls_recover`.
- **HIL confirmed:** 2026-09-08. Doctored `restore.py` (30 s window),
  `otampy upd main.py boot.py`, power pulled while committing `boot.py`. On
  power-up (no USB): device state was `boot.py` **present** (restored from
  `.bck`), `otampy-update.journal` line 1 `0`, no `.bck` files — `main.py`'s
  `recover()` had run `repair()`. (First HIL attempt was an operator error —
  the `recover()` line was deleted while adding a test marker; re-run with it
  intact self-healed.) Stale-flag removal added after observing
  `update_requested.flag` + `boot.py.ota` survive the first successful heal.
- **Closed:** 2026-09-08, `/sl-findings review`. Re-read `ota.py` `recover()` and
  `boot.run()`: `repair()` runs from both entry points, and `commit()` is
  strictly one pair at a time, so at most one of `boot.py`/`main.py` is ever
  absent. The flag removal is safe — a set flag while `main.py` runs means
  `boot.run()` did not execute. HIL trace (dev log) shows a real power loss
  self-healing over the radio, no USB. Two lesser wrinkles filed separately:
  F-07 (P3, redundant journal write the fix doubled) and F-08 (P2, `restore.py`
  itself as the interrupted file).

### F-04 — the orphan sweep deletes freshly-committed `.bck` files on the next boot

- **Severity:** P1
- **Status:** closed
- **Area:** `src/otampy/device/lib/otampy/boot.py` (`_cleanup_orphaned_ota`)
- **Found:** 2026-09-08 during HIL of `feature/failsafe-update-retain-previous` (Simon, Phase 2)
- **Evidence:** After `otampy upd main.py` and the device's post-commit reboot,
  `otampy ls /` showed the journal (`0` / `/main.py` / `/_otampy_set_rtc.py`)
  but **no `main.py.bck`**. `ota.log` on the device:
  `Cleanup started... / Removing orphaned file: /./main.py.bck / Cleanup complete`.
  `commit()` creates `/main.py.bck` correctly; on the next boot
  `boot.run()` → `_cleanup_orphaned_ota(core, path=".")` builds the candidate as
  `_resolve_path("./main.py.bck")`, which on MicroPython is `"/" + "./main.py.bck"`
  = `"/./main.py.bck"`. The journal's kept-set is `{"/main.py.bck"}`, so
  `"/./main.py.bck" not in kept_backups` is true and the backup is removed.
  littlefs resolves `/./` transparently, so the delete succeeds.
- **Impact:** Retain-previous's core guarantee — the previous version physically
  survives an update — is **void on hardware**. Every committed `.bck` is
  deleted on the first reboot after the commit. `repair()` after a real power
  loss then finds no `.bck` to restore from. The unit test
  `test_boot_removes_orphan_bck_but_keeps_journalled_one` passed because it
  patches `_resolve_path` with a mock and CPython's `pathlib`/string handling
  collapses the `./` that bare concatenation on the device does not.
- **Suggested fix:** start the `_cleanup_orphaned_ota` traversal from `"/"`
  instead of `"."`, so every `item_path` is built in the same `/dir/file` form
  the journal stores (`_resolve_path("/x")` is identity on both host and
  device). Add a regression test that uses the real `core._resolve_path` (not a
  mock) so the `.`-vs-`/` mismatch is actually exercised.
- **Resolution:** 2026-09-08, `feature/failsafe-update-retain-previous` step 9.
  Traversal root left at `"."` (flipping to `"/"` made the no-flag boot tests
  that don't mock `_os.listdir` walk the real filesystem — one hung). Instead,
  new `boot._canonical(path)` collapses `/./`, strips a leading `./`, and forces
  a leading `/`; it is applied to both the journal-derived `kept_backups` set
  and each `.bck` candidate before the membership test. `resolved_item` is still
  passed unchanged to `_os.remove`. Test:
  `test_ota_boot.py::test_cleanup_keeps_journalled_bck_with_real_resolve_path`
  (no `_resolve_path` mock — exercises the real `.`-vs-`/` mismatch).
- **Closed:** 2026-09-08, `/sl-findings review`. `_canonical()` is a pure
  function applied to both the journal-derived `kept_backups` and each `.bck`
  candidate; `.ota` removal (suffix match) and the path handed to `_os.remove`
  are unchanged. Regression test uses the real `_resolve_path`. HIL trace shows
  the `.bck` files surviving for `repair()` to consume. No new defect. (The raw
  `/./` path still appears in the sweep's debug log — cosmetic, tracked in
  Risks.)

### F-05 — `commit()` retains the transient RTC helper; `repair()` then resurrects it

- **Severity:** P2
- **Status:** closed
- **Area:** `src/otampy/device/lib/otampy/boot.py` (`_run_default_update_loop` /
  `restore.commit`)
- **Found:** 2026-09-08 during HIL of `feature/failsafe-update-retain-previous`
  (journal on device listed `/_otampy_set_rtc.py`)
- **Evidence:** `otampy upd` appends the one-shot RTC helper
  `_otampy_set_rtc.py` to the transfer manifest unless `--no-rtc`
  (`src/otampy/cli.py:2235`). It arrives via `FILE_START`/`CHUNK`/`FILE_END`
  like any file, so `commit()` backs it up to `_otampy_set_rtc.py.bck` and adds
  `/_otampy_set_rtc.py` to the journal. The helper self-deletes on the next
  boot (`deploy.rtc_helper_content()` ends `finally: os.remove(...)`). Once F-04
  is fixed and the `.bck` survives, `repair()` on the boot after that sees
  `/_otampy_set_rtc.py` missing but `/_otampy_set_rtc.py.bck` present and
  renames the `.bck` back into place — so the stale-dated helper runs a second
  time (setting the RTC to the *update's* wall-clock time, not now) before
  self-deleting again. The journal permanently lists a path that normally does
  not exist.
- **Impact:** One spurious, stale `machine.RTC().datetime(...)` call on the
  boot after every `otampy upd` (without `--no-rtc`). RTC feeds log timestamps
  and seeds the command-auth replay counter, so a backwards jump is not purely
  cosmetic. Currently *masked* by F-04 (the `.bck` is deleted before `repair()`
  can use it) — fixing F-04 unmasks it, so both must land together.
- **Suggested fix:** in `_run_default_update_loop`'s `UPDATE_COMMIT` branch,
  split `_otampy_set_rtc.py` out of `files` before calling `commit()` and place
  it with a plain `rename(staging, target)` — never backed up, never journalled.
  Named constant in `boot.py` (it already knows the module name in
  `_apply_staged_rtc_update`).
- **Resolution:** 2026-09-08, `feature/failsafe-update-retain-previous` step 10.
  New `boot._RTC_HELPER_FILE` constant. The `UPDATE_COMMIT` branch now walks
  `files`, places any pair whose target basename is `_RTC_HELPER_FILE` with a
  plain `remove`+`rename`, and passes only the `retained` pairs to
  `commit()`. `_apply_staged_rtc_update` derives its import name from the same
  constant (DRY). Test:
  `test_ota_boot.py::test_commit_does_not_retain_the_transient_rtc_helper` —
  full session with the helper in the manifest; asserts it is placed but has no
  `.bck` and is absent from the journal, while `main.py` is backed up normally.
- **Closed:** 2026-09-08, `/sl-findings review`. The `UPDATE_COMMIT` branch
  filters `_RTC_HELPER_FILE` by basename before `commit()`, places it with a
  plain `remove`+`rename`, and never journals it; a failed rename just leaves
  it unplaced (harmless — it self-deletes / is re-sent next update). HIL: the
  post-recovery journal listed only `/main.py` and `/boot.py`. No new defect.

### F-01 — `ChannelSerial.in_waiting` and `_pump` block on an empty serial port

- **Severity:** P2
- **Status:** closed
- **Area:** `src/otampy/` (channel.py; activated by the mux CLI wiring)
- **Found:** 2026-09-08 by /code-review (feature/channel-mux-cli-mode)
- **Evidence:** `src/otampy/channel.py:153` — `_pump` does
  `pending = getattr(self._ser, "in_waiting", 0) or 1` then
  `self._ser.read(pending)`. When the raw port's buffer is momentarily empty,
  `pending` is `1` and `serial.Serial.read(1)` blocks up to
  `serial_timeout_seconds` (default 2.0). `ChannelSerial.in_waiting`
  (`channel.py:174`) calls `_pump` first, so it blocks too — but a real
  `serial.Serial.in_waiting` never blocks. URST's `read_frame`
  (`urst/codec_layer.py`) does `bytes_to_read = max(1, self.ser.in_waiting)`
  then `self.ser.read(bytes_to_read)` — two `_pump` calls per loop iteration, so
  in mux mode one iteration can stall ~2×`serial_timeout` (~4 s) against a
  silent peer. Reproduced: with a raw port whose `read` sleeps 500 ms,
  `ChannelSerial(raw).in_waiting` took 500 ms and `.read(10)` a further 500 ms.
- **Impact:** Against a responsive device the exchange still completes (the
  end-to-end `test_mux_ping_roundtrip_returns_pong` passes), but on a slow or
  lossy link mux mode is ~2× slower to retry/give up than direct mode, and
  `read_frame`/`send_reliable` overshoot their millisecond timeout budgets.
  Direct mode is unaffected (`serial.in_waiting` is non-blocking there).
- **Suggested fix:** in `_pump`, read only `self._ser.in_waiting` bytes and
  return early when that is 0 (never fall back to a blocking `read(1)`).
- **Resolution:** 2026-09-08, `feature/channel-mux-cli-mode`. `_pump`
  (`src/otampy/channel.py:152`) now reads `getattr(self._ser, "in_waiting", 0)`
  and only calls `self._ser.read(pending)` when `pending` is non-zero — no
  `or 1` fallback. `ChannelSerial.read` returns `b""` promptly and URST's
  `read_frame` poll loop does the waiting. Tests:
  `tests/test_channel.py::TestChannelSerial::test_pump_does_not_read_when_port_is_empty`
  (fake serial whose `read` raises) and `test_pump_reads_only_what_is_pending`.
- **Closed:** 2026-09-08, /sl-findings review. Re-read `channel.py:152-167` as it
  now stands: `pending = getattr(self._ser, "in_waiting", 0)` with no `or 1`,
  `read()` only called when `pending` is truthy, `read()`/`in_waiting` return
  promptly. Blocking path gone. Full suite green (513). New Risk noted below
  (`.any()`-only ports). Re-review was same-session/same-agent as the fix; the
  producing `/code-review` was independent.

### F-02 — Mux CLI eagerly imports `urst` at `otampy.cli` import time

- **Severity:** P3
- **Status:** closed
- **Area:** `src/otampy/cli.py`
- **Found:** 2026-09-08 by /code-review (feature/channel-mux-cli-mode)
- **Evidence:** `src/otampy/cli.py:21` adds `from .channel import ChannelSerial`
  at module scope; `channel.py` does `from urst.codec_layer import cobs_decode,
  cobs_encode` at *its* module scope. Confirmed: `import otampy.cli` now leaves
  `urst` and `urst.codec_layer` in `sys.modules` (they were not before — the
  rest of cli.py keeps `import serial` / `from urst import Urst` function-local,
  and even guards the type-only imports under `TYPE_CHECKING`). `serial` is
  still lazy.
- **Impact:** `otampy --help`, shell completion and every non-device subcommand
  now pay the `urst` import (small — a pure-Python module plus a 256-entry CRC
  table build). Minor, but it breaks the deliberate lazy-import pattern this
  diff otherwise preserves.
- **Suggested fix:** move `from otampy.channel import ChannelSerial` inside
  `_open_transport`, alongside the existing `import serial` / `from urst import
  Urst`.
- **Resolution:** 2026-09-08, `feature/channel-mux-cli-mode`. Moved
  `from .channel import ChannelSerial` from `cli.py` module scope into
  `_open_transport`. Verified: `import otampy.cli` leaves neither `urst` nor
  `serial` in `sys.modules`. Test:
  `tests/test_mux_cli.py::TestLazyImport::test_importing_cli_does_not_pull_in_urst_or_serial`
  (subprocess).
- **Closed:** 2026-09-08, /sl-findings review. `ChannelSerial` now appears in
  `cli.py` only at `_open_transport`'s local import and its one use site
  (grep-verified); no module-scope reference. Subprocess test confirms `import
  otampy.cli` leaves `urst`/`serial` out of `sys.modules`.

### F-03 — A malformed `OTAMPY_MUX` fails every command, including the ones to fix it

- **Severity:** P2
- **Status:** closed
- **Area:** `src/otampy/cli.py`
- **Found:** 2026-09-08 by /code-review (feature/channel-mux-cli-mode)
- **Evidence:** `src/otampy/cli.py:831` — the `cli` group callback runs
  `ctx.obj["mux"] = mux if mux is not None else get_mux_enabled()` for **every**
  subcommand, and `get_mux_enabled()` (`cli.py:518`) raises `ClickException` on
  an unrecognised `OTAMPY_MUX` token. Reproduced: with `OTAMPY_MUX=maybe`,
  `otampy mux --show`, `otampy mux --clear` and `otampy ports --show` all exit 1
  with `Error: OTAMPY_MUX must be one of …` — the user cannot use the `mux`
  command to inspect or clear the setting while the bad env var is present.
- **Impact:** Self-inflicted lockout from a typo in an env var. Recovery is
  `unset OTAMPY_MUX` (the error message names the var), so impact is limited,
  but a config-inspection/repair command should not be blocked by the config it
  inspects.
- **Suggested fix:** in the `cli` callback, treat an unparseable `OTAMPY_MUX` as
  "unset" with a warning (fall through to the saved setting), or defer the
  strict parse to the point of use so `otampy mux` still runs.
- **Resolution:** 2026-09-08, `feature/channel-mux-cli-mode`. `get_mux_enabled`
  (`src/otampy/cli.py`) no longer raises on an unrecognised token — it prints
  `Warning: ignoring OTAMPY_MUX=… ` to stderr and falls through to the config
  chain (new `_parse_mux_token` / `_mux_from_config` helpers). `_mux_state`
  appends `(env OTAMPY_MUX=… invalid, ignored)` to the source so `otampy mux
  --show` still reports it. Verified: `OTAMPY_MUX=maybe otampy ping` and
  `otampy mux --clear` now exit 0 with a warning. Tests:
  `test_invalid_env_token_is_ignored_with_warning`,
  `test_invalid_env_falls_through_to_default`,
  `TestMuxCommand::test_show_still_works_with_a_malformed_env_var`.
- **Closed:** 2026-09-08, /sl-findings review. `get_mux_enabled` (`cli.py:532`)
  has no `raise` path — unrecognised token → stderr warning → `_mux_from_config`.
  Its only caller is the `cli` group callback (`cli.py:848`); `_mux_state` uses
  `_parse_mux_token` directly. Re-verified live: `OTAMPY_MUX=maybe otampy ping`
  and `otampy mux --clear` both exit 0. The empty-string-is-disable behaviour is
  unchanged (tracked as a Risk).

---

## Risks

Concerns worth keeping but not confirmed defects. No ID, block nothing.

- **`_cleanup_orphaned_ota` logs/removes the raw `/./x` path.** After the F-04
  fix, `_canonical()` is applied only to the *comparison* against `kept_backups`;
  `resolved_item` itself is still `_resolve_path("./x")` = `/./x` on MicroPython,
  so the debug log reads `Removing orphaned file: /./boot.py.ota` and
  `_os.remove` is called with `/./boot.py.ota`. littlefs resolves it fine and
  `.ota` removal is a suffix match, so it is purely cosmetic — but a future
  path-equality check elsewhere in that function would hit the same class of
  bug. Cheap to canonicalise `resolved_item` at the top of the loop; deferred
  as out of scope for the retain-previous sub-task.

- **`ChannelSerial` decoded-buffer overflow drops the oldest bytes.**
  `channel.py:161` caps the decoded channel-0 buffer at `OTA_BUFFER_BYTES`
  (2048) and drops from the front on overflow, which would truncate an in-flight
  URST frame. Not filed as a finding because URST is stop-and-wait — the host
  reads each frame (and each fragment) before the next arrives, so >2 KB of
  unread decoded data has no known path. Mirrors the shipped device
  `_VirtualPort._feed` behaviour. Revisit if a large unsolicited burst path
  appears.
- **`OTAMPY_MUX=` (set but empty) is treated as an explicit "disable".**
  `_MUX_FALSE_TOKENS` (`cli.py:94`) includes `""`, so an empty `OTAMPY_MUX`
  overrides a saved `mux = true` and silently selects direct mode. Deliberate in
  the current design and asserted by `test_env_token_parsing`, but many CLIs
  treat an empty env var as unset. `otampy mux --show` does report the source as
  `env OTAMPY_MUX`, so it is discoverable. Reconsider if it bites.
- **`ChannelSerial` only reads via `in_waiting`, not `any()`.** After the F-01
  fix, `_pump` (`channel.py:156`) does `getattr(self._ser, "in_waiting", 0)` and
  reads nothing if that attribute is absent — so a MicroPython-style port
  exposing only `.any()` would receive nothing. Not a defect today: `cli.py`'s
  `_open_transport` always wraps a real `serial.Serial`, and every test double
  provides `in_waiting`. If `ChannelSerial` is reused with a non-pyserial port,
  add an `elif hasattr(self._ser, "any")` branch like `urst.codec_layer` has.
