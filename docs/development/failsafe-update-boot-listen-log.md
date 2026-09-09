# Boot-time recovery listen window — dev log

Spec: `docs/development/failsafe-update-boot-listen-spec.md`
Branch: `feature/failsafe-update-boot-listen`

## 2026-09-09 — D2 re-confirmed before any code

The spec's red-team overturned signed-off decision D2 (a `RECOVERY` beacon
broadcast at window open). `Urst.send()` is stop-and-wait reliable, so with no
host listening it costs up to ~8 s per boot: `protocol.connect()` at 4 attempts
× `ACK_TIMEOUT_MS` 1000, then `send_reliable()` for 4 more. Sending it
unreliably would mean reaching into URST's frame codec, which the parent
sign-off excluded.

Simon re-confirmed the replacement: **silent window + host blind-retry**, no
beacon, no wire-format change. Recorded in the spec's Protocol decision.

## Step 1 — extract the auth gate into `authgate.py`

Pure move, no behaviour change. `_AUTH_PREFIX`, `_AUTH_FIELDS`,
`_REPLAY_FLOOR_FILE`, `_UNAUTHENTICATED`, `_REPLAYED`, `_replay_floor_path`,
`_auth_blocks`, `_replay_guard`, `_authenticate` (→ `authenticate`) and
`_persist_replay_floor` (→ `persist_replay_floor`) moved out of `manager.py`.

`manager.py` keeps a thin `_persist_replay_floor` wrapper that holds the
`core._replay_guard is None` early-out **at the call site**, so the reset paths
(`RB`/`SR`/`UPDATE_REQUEST`/`ROLLBACK`) can keep calling it unconditionally
while a no-auth device never imports `authgate`.

Evidence the no-auth path stays clean (the spec's stated risk for this step) —
ad-hoc probe with `OTA_REQUIRE_AUTH` absent:

| Command | Reply | `authgate` in `sys.modules` |
| --- | --- | --- |
| `PING` | `b'PONG'` | `False` |
| `RB` | `b'RB_OK'` | `False` |
| `SR` | `b'SR_OK'` | `False` |

Guard suites: `test_manager_auth.py`, `test_command_auth_contract.py`,
`test_ota_facade.py` — 109 passed. Full device suite 315 passed, identical to
the pre-change baseline. `ruff check .` clean.

## Step 2 — `restore.rollback_result()`, `manager.poll` refactored onto it

Four tests written first, all failing on `AttributeError: module
'device_otampy.restore' has no attribute 'rollback_result'` before the
implementation existed.

`rollback_result(core) -> (reply_bytes, restored_count)` wraps the unchanged
`rollback()`. `_ROLLBACK_BUSY` now stays private to `restore.py` — it is folded
into a reply rather than crossing a module boundary, which is the point: the
boot window would otherwise have to import and interpret it too.

`manager.poll`'s `ROLLBACK` branch drops from 12 lines to 8 and no longer
carries the reply strings. The `ROLLBACK_ERR` strings now appear exactly once
each in code (`restore.py:56-57`); the remaining tree hits are `docs/protocol.md`
and `CHANGELOG.md`, which are documentation.

`test_ota_manager.py`'s existing `ROLLBACK` tests passed untouched — the guard
that the refactor changed no behaviour. Device suite 319 passed (315 + 4 new).

Note: `uv run pyright` reports one pre-existing error in `restore.py` (`trial()`,
`attempt > limit`, because `_get_config` is typed `Any | None`). Confirmed
present on `develop` before this branch — line number moved 294 → 317 only.
Pyright does not gate CI.

## Step 3 — `boot._run_boot_listen()`, the window itself

12 tests written first, all red on `AttributeError: module
'device_otampy.boot' has no attribute '_run_boot_listen'`.

Tests use a fake monotonic clock (`itertools.count` patched over
`boot._ticks_ms`, with `_sleep_ms` a no-op) so no test ever really sleeps a
window. The whole device suite still runs in ~4 s.

Two design points worth remembering:

- **The deadline is absolute, not inactivity-based.**
  `_run_default_update_loop` resets `last_activity` on every packet; the
  window must not, or a chatty peer could pin a device inside it. Covered by
  `test_boot_listen_deadline_is_absolute_not_inactivity`, which queues 500
  refused `PING`s and asserts fewer than 200 are served before the window
  closes on schedule.
- **A refusal keeps the window open.** `ROLLBACK` with nothing retained
  replies and *keeps listening*, so an operator who guesses wrong can still
  land `UPDATE_REQUEST` in the same window without another power cycle.
  Covered by `test_boot_listen_refusal_does_not_consume_the_window`.

Non-UTF-8 packets are dropped in silence (per the spec's dispatch table),
not answered with `ERROR:Invalid UTF-8` as the update loop does. The
high-bit scan from the update loop is reused so pure-ASCII packets never pay
for a decode.

`boot.py` still contains no import of `manager` (grep, no hits) — the reason
`authgate` was extracted in step 1. `boot._persist_replay_floor` duplicates
`manager`'s four-line guard on purpose; sharing it would mean importing
`manager` into the boot phase, which is the exact cost being avoided. Noted
in both docstrings.

Device suite 331 passed (319 + 12). `ruff check .` clean; ruff format
reformatted the new test file.

## Step 4 — wiring the window into `boot.run()`

One line of wiring (`if not has_flag and _run_boot_listen(core): return`,
placed after the flag `stat` and before the `if has_flag:` block) plus
`"authgate"` added to `ota.OTA.boot()`'s teardown list. Four spy-based tests
guard the ordering.

**Two consequences the spec did not anticipate**, both surfaced by an existing
test going red rather than by inspection:

1. **A no-flag boot now instantiates the transport.** `test_boot_no_flag_file`
   asserted `core._transport is None` — the lazy-transport guarantee. The
   window cannot listen without a transport, so on the default path that
   guarantee is gone. It still holds exactly when `OTA_BOOT_LISTEN_MS = 0`,
   which is how the test now expresses it, and
   `test_boot_no_flag_opens_the_transport_for_the_window` pins the enabled-path
   cost so it is a recorded decision rather than a surprise. Worth a line in
   the docs at step 7: the per-boot cost is ~1 s **and** one `Urst`
   instantiation.

2. **Six existing tests began really sleeping the full 1000 ms window**, taking
   the device suite from 4.81 s to 10.69 s. They exercise the rest of a no-flag
   boot, not the window, so they now set `OTA_BOOT_LISTEN_MS = 0` explicitly.
   Suite back to 4.78 s; the three slowest tests are pre-existing
   `test_ota_manager.py` CAT-fragment tests.

This is the argument for the window being tunable and disable-able landing in
the docs plainly rather than buried — an integrator who disables it gets the
old boot behaviour back exactly, transport included.

Device suite 336 passed. `ruff check .` clean, pre-flight exit 0.

## Step 5 — host `recovery_wait_seconds` + `_recover_query()`

Four tests written first; all red on `ImportError: cannot import name
'_recover_query'` (and the config test on a missing `recovery-wait` row).

`_recover_query` is deliberately thin: print the power-cycle instruction, then
loop `_query` until it returns or `recovery_wait_seconds` (default 60, env
`OTAMPY_RECOVERY_WAIT`) expires, sleeping `query_retry_backoff_seconds`
between attempts. Same shape as the existing `_wait_for_pong`, which is the
precedent for "retry a `_query` while the device reboots".

The one judgement call: **`DeviceError` is not caught.** A `ClickException`
from `_query` means silence — no window was open, retry. A `DeviceError` means
the device *answered* (`Unauthenticated`, `ROLLBACK_ERR:...`), so retrying
would re-send a command the device has already refused, and with auth on would
burn replay counters. `test_recover_query_lets_a_device_error_through` pins it.

Tests patch `time.sleep` and set `OTAMPY_RECOVERY_WAIT=0`, so nothing sleeps —
`tests/test_cli.py` runtime is unchanged.

Pre-flight exit 0.

## Step 6 — `otampy upd --recover` / `otampy rollback --recover`

Five tests first, red on the missing `--recover` flag / `NameError`.

`--recover` on `upd` swaps the single `_send_command(ctx, b"UPDATE_REQUEST",
b"REBOOTING")` in `_update_files` for `_recover_query(...)`; everything from the
READY wait onward is the unchanged code path. `--recover` on `rollback` routes
the `ROLLBACK` through `_recover_query` instead of `_query`, after the existing
red confirm prompt (so confirm-**no** still sends nothing and prints no
power-cycle instruction), and swaps in a recovery-specific `_wait_for_pong`
message noting the reverted-to version may itself be unhealthy.

`recover` had to be threaded through `_update_files` (the nested transfer
helper), not just `update()` — the `UPDATE_REQUEST` send lives there. Both
`_update_files` call sites (bytecode and plain) pass `recover=recover`.

**Three existing tests updated**: `test_update_passes_no_progress_through_to_the_transfer`
and two bytecode-cleanup tests assert `_update_files`'s exact call kwargs; each
gained `recover=False`. These guard internal plumbing, not user behaviour — the
no-`--recover` user path is unchanged (`test_upd_without_recover_prints_no_power_cycle_prompt`,
plus every untouched handshake test).

Pre-flight exit 0 (627 tests).

## Step 7 — docs, config example, changelog, findings

Docs only, no code.

- `docs/protocol.md` §2.4 — new "Boot-time recovery window" subsection: when
  it opens, the full dispatch table, silent + host-blind-retry, channel 0, no
  wire change, auth enforced, and the hard limits (needs `boot.py` to run,
  no watchdog this early, `PING` deliberately unanswered). The `ROLLBACK`
  command row and the trial-boot prose corrected from "served only by the
  `main.py` poll loop" to "and the boot-time recovery window".
- `docs/architecture.md` — `OTA_BOOT_LISTEN_MS` in the `configota.py` block
  with its per-boot cost (~1 s + one `Urst` instantiation, `0` disables and
  removes the recovery path); a paragraph under "Trial boot, confirmation,
  and auto-restore" covering the window and the custom-`boot.py`-watchdog
  caveat; the "device stranded before `main.py` needs the boot-time recovery
  window" sentence corrected — it now has one.
- `configota.example.py` — `OTA_BOOT_LISTEN_MS = 1000` with a comment on the
  per-boot cost and `0` to disable.
- `CHANGELOG.md` `[Unreleased]` — an "Added" bullet for the window + the two
  `--recover` flags + `recovery-wait`, and the existing `ROLLBACK` "Changed"
  bullet corrected.
- `docs/development/findings.md` — F-08's "Belongs with sub-task 4" line
  replaced with a paragraph explaining why the window cannot fix it (its own
  `from .restore import` raises first) and that it is now a standalone
  `TODO.md` item.
- `TODO.md` — sub-task 4 ticked `[x]`. **The F-08 follow-up item
  ("Freeze `restore.py` / a recovery `_boot.py` into the deployed image") is
  proposed, not yet added — needs Simon's approval per the spec.**

Pre-flight exit 0 (docs don't gate; ran to confirm nothing else moved).

## HIL verification — 2026-09-09

### Step 8 — F-09, found on the rig before any HIL test could run

Deployed the branch to the Pico W: `otampy deploy -p /dev/ttyACM0 --device-dir
src/otampy/device/examples` → "Deployment completed successfully", exit 0.
Filesystem after deploy (over USB): `boot.py configota.py lib main.py`,
`lib/otampy/` has `authgate.py`, no journal, no `.bck`. Clean.

`otampy --port /dev/ttyUSB0 ping` then timed out on every attempt — full URST
handshake failure, 4 attempts, no `PONG`. Pre-deploy the same command answered
first try, so the deploy broke it.

Isolated it over USB (one disciplined mpremote session, hard reset after):
- The gateway link is fine — a hand-run `ota.poll()` loop on the device
  answered a host `ping` with `PONG` immediately.
- `configota.py` pins/port/baud on device match the wiring (1 / 4 / 5 / 57600).
- Calling `OTA(uart, ...).boot()` directly on the device raised
  `KeyError: authgate` from `ota.py` line 45.

Root cause: MicroPython's `delattr(module, name)` raises `KeyError` for a
missing attribute; CPython raises `AttributeError`. `OTA.boot()`'s teardown
catches only `AttributeError`. `authgate` is imported by the recovery window
only when `OTA_REQUIRE_AUTH` is set, so on a normal boot the `delattr` for it
throws `KeyError`, which escapes `boot()` → `boot.py` crashes → `main.py` never
runs → device dead over the radio. Every no-auth boot. Filed F-09 (P0).

Verified the divergence directly on device:
`delattr(otampy, 'authgate')` → `KeyError('authgate',)`;
`del otampy.nonexistent` → `KeyError` too.

Host tests never caught it (CPython). Added
`test_boot_teardown_survives_micropython_delattr_keyerror` which simulates the
MicroPython semantics by patching `builtins.delattr`; red before the fix.

Fix: `except AttributeError` → `except (AttributeError, KeyError)` at that one
call site. Pre-flight exit 0 (337 device tests, full CLI suite).

Also noticed while here: `test_ota_facade.py`'s existing
`test_boot_releases_boot_module_and_can_run_again` leaves `device_otampy.boot`
deleted from `sys.modules`; a `pytest-randomly` seed that runs it before the
`test_ota_boot.py` boot tests makes 5 of them fail (they patch a stale module).
Pre-existing, masked by alphabetical file order. Noted in F-09 as a follow-up
for `TODO.md`; not fixed here.

Two stray stub files (`main.py`, `_otampy_set_rtc.py`, ~20 B each) were sitting
untracked in the repo root from some earlier session — they made
`test_cli_update_default` fail (it scans cwd). Moved them to the scratchpad;
not ours.

**HIL tests 0–6 not yet run** — blocked on redeploying the F-09 fix and
confirming the rig boots.

### HIL test 0 — provision + baseline (after F-09 fix) — PASS

Redeployed the branch with the F-09 fix: `otampy deploy` exit 0.
`otampy --port /dev/ttyUSB0 ping` → `PONG` on 3/3 attempts.
`otampy ls /` → `boot.py  configota.py  lib/  main.py` (no journal, no `.bck`).
`otampy state` → "Running a confirmed (stable) build."

The device now boots cleanly to `main.py` over the radio with no USB. F-09 is
repaired on the rig.

**HIL tests 1–6 need an operator at the rig** (power-cycle on the CLI prompt,
six full power cycles for test 3). Paused here for Simon.

### HIL test 4 — window is not permanently open — PASS (with a spec-wording note)

Device healthy, freshly deployed, no `.bck`, state "confirmed (stable)".
`yes | otampy -p /dev/ttyUSB0 rollback --recover`, **no power cycle**.

Observed: the retry loop's first attempt was answered by the *running app's*
poll loop (sub-task 3 put `ROLLBACK` in `manager.poll`), which replied
`ROLLBACK_ERR:Nothing to roll back`. CLI printed "Rollback refused: Nothing to
roll back", exit 1, in ~3 s — it did **not** spin for the full 60 s
`recovery-wait`.

Safety property under test — "an un-power-cycled device is never in a window
and never resets" — holds: immediately afterwards `otampy ping` → `PONG` and
`state` → "Running a confirmed (stable) build" (unchanged, no reset).

Spec wording note: test 4's stated evidence ("times out with the recovery-wait
message") predates `ROLLBACK` being served by the running poll loop. On a
healthy device the command is now answered, not timed out. The 60 s timeout
path is still exercised — it is what happens against a *stranded* device that
is not power-cycled (window never re-opens); captured incidentally in test 1.
Recommend correcting the spec's test-4 evidence line rather than treating this
as a device defect.

### HIL test 1 — recover a stranded device via the window's ROLLBACK — FAIL (F-10)

Setup: `otampy -p /dev/ttyUSB0 upd --no-confirm hil-scratch/main_broken.py:main.py`
where `main_broken.py` is a single `raise RuntimeError(...)` at import, no
watchdog. Commit OK, "on trial". Device rebooted → `otampy ping` timed out on
every attempt: **stranded, as intended**, with `main.py.bck` retained.

`otampy rollback --recover` (auto-confirm), operator power-cycled once on the
prompt. **Attempt 1: 60 s recovery-wait expired, window never answered.**
Re-ran with `OTAMPY_QUERY_RETRY_BACKOFF=0.05`, power-cycled again.
**Attempt 2: 60 s expired again, window never answered.**

Both attempts missed the ~1 s boot window. Then the device **self-recovered**
via trial-boot auto-restore (the accumulated power cycles pushed the trial
counter past `OTA_TRIAL_BOOTS = 3`; `trial()` ran `restore_all()` and reset
onto the previous generation). `otampy ping` → `PONG`, `state` → "confirmed
(stable)", `/main.py` is the example again, no `.bck`/journal.

Diagnosis (from the URST source, not guesswork):
`urst.constants` — `MAX_RETRIES = 3`, `ACK_TIMEOUT_MS = 1000`. One CONNECT
handshake against an **absent** device = `MAX_RETRIES + 1 = 4` attempts x
1000 ms = **~4 s**. `_query` wraps that in `query_retries = 3` -> **~12 s per
`_query` call**. `_recover_query` loops `_query` with a 0.05-0.25 s backoff, so
the host emits a fresh CONNECT roughly **every 12 s**. The device's recovery
window is **1 s per boot**. Hit probability per power cycle ~= 1/12 ~= **8 %**;
an operator would average ~12 power cycles to recover via the window. 0/2 here
is the expected outcome of that maths, not bad luck.

The window itself (`_run_boot_listen`, 10 ms poll) is not at fault — it would
answer any CONNECT that arrived inside the second. The gap is host-side: the
blind-retry cadence is ~12x too slow for the window it is trying to hit.

Filed **F-10 (P1)**. Blocks tests 2, 5, 6 (all need a command to land in the
window). Test 3 (boot-cost timing) and test 4 (already PASS) do not.

### HIL bonus — trial-boot auto-restore (sub-task 2) on real hardware — PASS

Not a planned test here, but observed cleanly: a device stranded by a fatal
`main.py` with `main.py.bck` retained, power-cycled past `OTA_TRIAL_BOOTS`,
auto-restored the previous generation and came back healthy over the radio with
no operator action beyond the power cycles. The backstop works.

### HIL run paused

- Tests 0, 4: PASS. Bonus trial-restore: PASS.
- Tests 1, 2, 5, 6: blocked on F-10 (host retry cadence vs 1 s window).
- Test 3: not run (operator-heavy, and worth doing in the same pass as 1/2/5/6
  once F-10 is fixed).
- Device left healthy: example `main.py`, confirmed/stable, no `.bck`/journal,
  `OTA_BOOT_LISTEN_MS` at default, no auth. `hil-scratch/` removed.
- Note: `/dev/ttyACM0` threw `OSError: [Errno 5]` during a diagnostic mpremote
  call (after many power cycles) — the gateway `/dev/ttyUSB0` was unaffected and
  all verification above is over it.

### Step 9 — F-10 fix (host-side, no rig)

`urst.constants` has no per-instance override for handshake timing, and the
house rule is to not fork URST — so `_recover_query` temporarily rebinds two
module constants for its poll and restores them in a `finally`:

- `_fast_recovery_handshake()` context manager: `ACK_TIMEOUT_MS` 1000 → 120,
  `MAX_RETRIES` 3 → 1. A failed CONNECT drops from ~4 s to ~240 ms.
- `_query(..., fast=True)`: new keyword-only flag, sets the inner
  `query_retries` to 1 and takes no backoff. One `_query` call against an
  absent device drops from ~12 s to ~0.25 s.

Net: the host emits a fresh CONNECT several times a second instead of once
every ~12 s. Against a 1 s window a power-cycle should land within a cycle or
two. `MAX_RETRIES = 1` (not 0) keeps 2 ACK attempts for the in-window
ROLLBACK/REBOOTING reply.

`conftest.py` for the device suite installs a fake `urst` at collection time
that pytest also exposes to `tests/` — its 2-field `fake_constants` stub was
replaced with the real `urst.constants` (pure data, no I/O) so
`_fast_recovery_handshake` finds `ACK_TIMEOUT_MS`.

Tests (red first): `test_recover_query_polls_with_a_fail_fast_handshake_and_restores_it`,
`test_recover_query_restores_handshake_timing_even_on_timeout`,
`test_query_fast_mode_makes_one_attempt_with_no_backoff`.

Pre-flight exit 0 (ruff + 631 tests). **Not yet HIL-verified** — needs a rig
session to re-run tests 1, 2, 3, 5, 6.

### Step 9 follow-on + HIL re-test — F-10 not yet closed

Re-tuned the fail-fast profile (`ACK_TIMEOUT_MS` 120 → tried, then 500;
`MAX_RETRIES` → 0; new `_RECOVERY_SERIAL_TIMEOUT = 0.1` threaded through
`_open_transport`). Cadence went from ~1 CONNECT / 12 s to ~1.2 / s in HIL.

Three stranded-device runs, operator power-cycling on the prompt:

| run | ACK_TIMEOUT | serial | host cycles / 60–120 s | CONNECT_ACK | result |
|-----|-------------|--------|------------------------|-------------|--------|
| v3  | 120         | 2.0    | 14                     | 0           | timeout |
| v4  | 120         | 0.05   | 108                    | 0           | timeout |
| v5  | 500         | 0.1    | 93+                    | 0           | timeout |

`connect()` against the **healthy** device: ~81 ms, four for four. So the link
is fast and 500 ms is ample — the boot window itself is not answering a single
CONNECT across a power cycle.

Cadence was necessary but not sufficient. Two open leads (in F-10):
- Simon: XBee needs ~30 ms between sends; the loop also reopens the serial
  port every cycle (DTR/RTS toggle on the FTDI→XBee), which may disturb the
  module.
- `_run_boot_listen` blocks up to the device-side 1000 ms `ACK_TIMEOUT_MS` per
  `read()`, so the 1 s window runs only ~1 read; needs on-device logging to
  see what it receives.

Stopped here. F-10 stays open. Device recovered via trial auto-restore (its
backstop fired again, cleanly, three times tonight). `hil-scratch/` removed.

Verified tonight overall: tests 0, 4 PASS; sub-task 2 trial auto-restore PASS
(observed 3×). Tests 1, 2, 5, 6 blocked on F-10; test 3 not run.
