# Boot-time recovery listen window — spec

**TODO item:** `[ ] 4. Boot-time recovery listen window.` (sub-task 4 of **Fail-safe Updates**)
**Status:** approved
**Components:** `src/otampy/device/lib/otampy/` (`boot.py`, `restore.py`, `manager.py`, new `authgate.py`), `src/otampy/cli.py`, `src/otampy/device/examples/configota.example.py`, `docs/protocol.md`, `docs/architecture.md`, `CHANGELOG.md`
**Dev log:** `docs/development/failsafe-update-boot-listen-log.md` (created by `/sl-build`)

## Goal

After this ships, a device whose `main.py` never reaches `ota.poll()` — it
raises on import, hangs, or was replaced by a broken candidate that got
confirmed — is still recoverable over the radio with no USB. On every boot
where no update is already pending, `boot.py` listens silently for
`OTA_BOOT_LISTEN_MS` (default 1000) and accepts exactly two commands:
`UPDATE_REQUEST`, which sets the update flag and resets into the existing
host-driven update session, and `ROLLBACK`, which reverts to the retained
`.bck` generation and resets onto it. The host drives this with
`otampy upd --recover` and `otampy rollback --recover`, which prompt the
operator to power-cycle the device and retry the command until it lands in a
window. When `OTA_REQUIRE_AUTH` is set the window enforces the same auth
envelope the runtime command surface does, so it is not a bypass.

This closes the last gap in the Fail-safe Updates chain. Sub-task 2's
auto-restore needs a *reboot during the trial window*; sub-task 3's `ROLLBACK`
needs `main.py`'s poll loop. Neither helps a candidate that is confirmed and
then proves fatal, or one that strands the device before `poll()` is ever
called.

## In scope

- **`boot._run_boot_listen(core)`** — the window. Silent (no beacon, see
  Protocol decision), bounded by `OTA_BOOT_LISTEN_MS`, `0` disables it.
  Dispatches `UPDATE_REQUEST` and `ROLLBACK` only; every other packet gets
  `ERROR:Recovery window` and the window keeps listening.
- **`boot.run()` wiring** — the flag `stat` is hoisted above the window, and
  the window runs only when the flag is *absent*, after `repair()` and
  `trial()`, so it operates on a healed tree and never interferes with an
  update session already in progress.
- **`restore.rollback_result(core)`** — `-> (reply_bytes, restored_count)`.
  The reply/refusal mapping sub-task 3 put inline in `manager.poll`, lifted so
  the boot window and the poll loop share one implementation.
  `manager.poll`'s `ROLLBACK` branch is refactored onto it in the same step.
- **New `authgate.py`** — `_authenticate`, `_auth_blocks`, `_replay_guard`,
  `_replay_floor_path`, `persist_replay_floor` and the `AUTH:` envelope
  constants, extracted verbatim from `manager.py`. `manager.py` and `boot.py`
  both import it lazily and only when auth is actually configured, so the
  no-auth path costs nothing.
- **New device config key `OTA_BOOT_LISTEN_MS`** (default `1000`), documented
  in `docs/architecture.md` §1 and `configota.example.py`.
- **New host config key `recovery_wait_seconds`** (default `60.0`, env
  `OTAMPY_RECOVERY_WAIT`) — how long the CLI keeps retrying while the operator
  power-cycles.
- **Host `_recover_query(ctx, command, expected_prefix)`** — prompts for the
  power cycle, then wraps the existing `_query` in a retry-until-deadline loop.
  One implementation, used by both `--recover` flags.
- **`otampy upd --recover`** — skips the send-`UPDATE_REQUEST`-to-`main.py`
  step and lands it in the boot window instead. Everything from the `READY`
  wait onward is the existing, unchanged code path.
- **`otampy rollback --recover`** — same prompt/confirm shape as today's
  `rollback`, but the `ROLLBACK` goes into the window.
- **Docs** — `docs/protocol.md` §2.4 (the window, its two commands, its
  limits), `docs/architecture.md` (`OTA_BOOT_LISTEN_MS` and a paragraph under
  the trial-boot section), `CHANGELOG.md` `Unreleased`.
- **Tests** — `test_ota_boot.py`, `test_restore.py`, `test_ota_manager.py`,
  `test_manager_auth.py`, `tests/test_cli.py`.

## Out of scope

- **F-08** (P2, open — a power loss while `restore.py` itself is the mid-commit
  file). The window cannot fix it: `boot.run()`'s `from .restore import ...`
  raises before the window would open, and even with that import guarded, the
  flagged update loop's `from .restore import clear_journal, commit` comes from
  the same absent module. A real fix is freezing `restore.py` into the image or
  F-06's Option C (a frozen `_boot.py`). **Action for the build:** move F-08's
  "belongs with sub-task 4" note in `docs/development/findings.md` to a new
  `TODO.md` item, so it stops being parked on a sub-task that demonstrably
  cannot resolve it.
- **A `boot.py` that itself crashes before the window.** MicroPython then falls
  through to `main.py`; if that runs, sub-task 3's `ROLLBACK` covers it. If
  neither runs, recovery is USB. Needs frozen code — same boundary as F-08.
- **A device that hangs *inside* the window.** Nothing arms a watchdog this
  early; a hardware fault that wedges the UART is not recoverable in software.
- **Any new wire command verb.** See Protocol decision — the window reuses
  `UPDATE_REQUEST` and `ROLLBACK` exactly as they are on the wire today.
- **Answering `PING` in the window.** Deliberate: a device in the recovery
  window is *not* running its application, and a `PONG` would report it healthy.
  The absence of a `PONG` is the signal that recovery is needed.
- **Deleting or altering the trial/journal semantics.** `trial()` still runs
  before the window on every boot; a boot-looping candidate still auto-restores
  on the same schedule.
- **Filesystem-atomic transactions** — same boundary as sub-tasks 1–3.

## Protocol decision

- **Existing OTAmpy/URST command reusable?** Yes, both. `UPDATE_REQUEST` in the
  window replies `REBOOTING`, writes `UPDATE_REQUEST_FLAG_FILE` and
  `machine.reset()`s — byte-for-byte what `manager.poll` does — so the whole
  existing `READY` → `UPDATE_START` → `COMMIT_OK` session runs unchanged after
  the reset. `ROLLBACK` reuses `restore.rollback()` via the new shared
  `rollback_result()`.
- **Channel:** 0 (reliable). Same surface as every other OTAmpy command; in mux
  deployments the window reads `mux.ota_port`, so no mux or framing change.
- **Wire format change?** **None.** No new command verb, no new response token,
  `PROTOCOL_VERSION` does not move. The host changes are two flags and a retry
  loop; the device changes are a new dispatch site for two existing commands.
- **Signed off:** 2026-09-08 by Simon (the parent Fail-safe Updates decision:
  no URST change, channel 0 only). Sub-decisions D1–D5 confirmed 2026-09-09.

### D2 changed during the red-team — needs a nod

D2 as signed off had the device broadcast a new unsolicited `RECOVERY` beacon
at window open, giving the host a deterministic sync point. **That is not
viable and the spec drops it.** `Urst.send()` is stop-and-wait reliable: with
no host listening it calls `protocol.connect()` (4 attempts ×
`ACK_TIMEOUT_MS` 1000) and then `send_reliable()` (4 more attempts × 1000), so
an unacknowledged beacon costs **up to ~8 seconds on every boot**. The existing
`READY` broadcast never pays this because it only fires when a host is already
waiting. Sending the beacon unreliably would mean reaching into URST's frame
codec, which the sign-off rules out.

The spec therefore uses the alternative offered under D2: a **silent window**,
with the host blind-retrying. This is less of a change, not more — it removes
the only wire addition. It is also workable in practice: a host `_query`
attempt spans several seconds of URST retries, `_recover_query` repeats those
for `recovery_wait_seconds` (default 60), and the device ACKs at the link layer
as soon as its `read()` is running. The cost is that a window can be missed, in
which case the operator power-cycles again — the CLI says so explicitly.

**D2 is the one thing to re-confirm before `/sl-build` starts.** D1, D3, D4 and
D5 are unaffected.

**Re-confirmed 2026-09-09 by Simon:** silent window + host blind-retry, no
beacon. The build proceeds on that basis.

## Data and contracts

### The recovery window — **load-bearing**

| Packet in window | Reply | Effect |
| --- | --- | --- |
| `UPDATE_REQUEST` | `REBOOTING` | Write `UPDATE_REQUEST_FLAG_FILE`, persist the replay floor, `machine.reset()`. The next boot takes the existing flagged path (`READY` + update loop). |
| `ROLLBACK` (retained `.bck` present) | `ROLLBACK_OK` | `restore.restore_all()`, persist the replay floor, `machine.reset()` onto the previous generation. |
| `ROLLBACK` (nothing retained) | `ROLLBACK_ERR:Nothing to roll back` | Nothing touched, **no reset, window keeps listening.** |
| `ROLLBACK` (`committing` journal) | `ROLLBACK_ERR:Commit in flight` | Nothing touched, **no reset, window keeps listening.** |
| Bad/absent `AUTH:` envelope (auth on) | `ERROR:Unauthenticated` | Window keeps listening. |
| Replayed counter (auth on) | `ERROR:Replayed` | Window keeps listening. |
| Anything else, incl. `PING` | `ERROR:Recovery window` | Window keeps listening. |
| Empty, or non-UTF-8 | *(none)* | Ignored, as `manager.poll` does. |

A refusal does not consume the window: an operator who tries `ROLLBACK`, is
told there is nothing retained, and then wants `upd --recover` instead must
still power-cycle, but a second command arriving inside the *same* window is
served.

No application callback fires in the window — there is no application running
at boot time, so `manager`'s `_do_callback` has no meaning here.

### `restore.rollback_result(core)` — **load-bearing**

```python
def rollback_result(core):
    """-> (reply_bytes, restored_count). Never raises."""
```

| Journal state | Returns |
| --- | --- |
| `committing` | `(b"ROLLBACK_ERR:Commit in flight", 0)` |
| no journalled `.bck` survives | `(b"ROLLBACK_ERR:Nothing to roll back", 0)` |
| otherwise | `(b"ROLLBACK_OK", n)` where `n = restore_all()`'s count |

`restored_count > 0` is the caller's signal to reset; it is also the number the
caller logs. `_ROLLBACK_BUSY` stays private to `restore.py` — it is folded into
the reply here and no longer crosses a module boundary.

### `authgate.py` — **load-bearing** (pure move, no behaviour change)

Moved verbatim from `manager.py`: `_AUTH_PREFIX`, `_AUTH_FIELDS`,
`_REPLAY_FLOOR_FILE`, `_UNAUTHENTICATED`, `_REPLAYED`, `_replay_floor_path`,
`_auth_blocks`, `_replay_guard`, `_authenticate`, `_persist_replay_floor`
(renamed `persist_replay_floor`, public — it now has two callers).

Import discipline, so the no-auth path is unchanged:

- `manager.poll` imports `authenticate` lazily inside its existing
  `if _get_config(core.config, "OTA_REQUIRE_AUTH", False):` branch.
- `manager`'s reset paths (`RB`/`SR`/`UPDATE_REQUEST`/`ROLLBACK`) currently call
  `_persist_replay_floor`, which early-returns when `core._replay_guard` is
  `None`. That guard moves to the call site —
  `if getattr(core, "_replay_guard", None) is not None:` then import — so a
  no-auth device never imports `authgate` at all.
- `boot._run_boot_listen` does the same in both places.

### Config keys

| Setting | Where | Default | Meaning |
| --- | --- | --- | --- |
| `OTA_BOOT_LISTEN_MS` | `configota.py` | `1000` | How long `boot.py` listens for a recovery command on a boot with no update pending. `0` disables the window entirely. Read via `_get_config`; a non-integer falls back to the default, `<= 0` disables. |
| `recovery_wait_seconds` | host `_CONFIG_SPEC` | `60.0` | How long `--recover` keeps retrying while the operator power-cycles. Env `OTAMPY_RECOVERY_WAIT`, display name `recovery-wait`. |

Named constants: `boot._DEFAULT_BOOT_LISTEN_MS = 1000`,
`boot._BOOT_LISTEN_POLL_MS = 10` (matches `_run_default_update_loop`'s idle
sleep), `boot._RECOVERY_REFUSED = b"ERROR:Recovery window"`;
`restore._REPLY_ROLLBACK_OK` / `_REPLY_ROLLBACK_BUSY` / `_REPLY_ROLLBACK_NONE`.

## Device cost

- **Hot-path allocation:** none. The window runs once per boot, cold, before
  the application exists. Inside it, `read()` + `_sleep_ms(10)` for at most
  `OTA_BOOT_LISTEN_MS` — roughly 100 iterations at the default, the same loop
  shape `_run_default_update_loop` already uses while idle. No per-iteration
  allocation beyond whatever `Urst.read()` does on an empty port.
- **The real cost is wall-clock boot delay:** every boot with no update pending
  gets `OTA_BOOT_LISTEN_MS` longer, ~1 s at the default. It is paid on each
  iteration of a boot-loop too. This is the price of the recovery guarantee and
  is why the key is tunable and `0` disables it. **Step 3's HIL evidence must
  show ~1 s, not ~8 s** — an 8 s figure would mean something is doing a blocking
  reliable send with no listener (see the D2 note).
- **Loop granularity:** the window's real duration is `OTA_BOOT_LISTEN_MS`
  rounded up to one `Urst.read()` granule, since the `_ticks_diff` bound is
  only checked between reads. Bounded and small; not tuned further.
- **Watchdog:** nothing arms a WDT this early — `boot.run()` precedes `main.py`
  — and 1000 ms is far under the RP2040's ~8388 ms cap regardless. A custom
  `boot.py` that arms a watchdog *before* `OTA(...).boot()` must keep
  `OTA_BOOT_LISTEN_MS` under its period; documented in
  `docs/architecture.md`.
- **Module weight:** `authgate` is imported only when auth is configured, in
  both the boot and runtime phases. `boot`'s existing teardown in
  `ota.OTA.boot()` deletes `boot` and `restore`; add `authgate` to that list so
  the boot phase does not leave it resident for `main.py` to inherit a stale
  copy of.

## Build steps

- [x] **1. Extract the auth gate into `authgate.py` (refactor only)**
  - What changes: new `src/otampy/device/lib/otampy/authgate.py` holding the
    constants and five functions listed under *Data and contracts*, moved
    verbatim; `_persist_replay_floor` → `persist_replay_floor`. `manager.py`
    imports them lazily per the import discipline above, keeping the
    `getattr(core, "_replay_guard", None)` early-out at its call sites so a
    no-auth device never imports the module. No behaviour change.
  - Test: none new — `src/otampy/device/tests/test_manager_auth.py` and
    `test_command_auth_contract.py` are the guard, plus
    `test_ota_facade.py::test_package_import_does_not_eagerly_load_operating_modes`.
    Run them in full, not a subset.
  - Done when: `uv run pytest src/otampy/device/tests/ -q` passes unchanged,
    `uv run ruff check .` is clean, and `grep -n "_authenticate\|_auth_blocks"
    src/otampy/device/lib/otampy/manager.py` returns nothing.

- [x] **2. `restore.rollback_result()` + `manager.poll` refactored onto it**
  - What changes: `restore.py` — the three reply constants and
    `rollback_result(core)` per its contract, wrapping the existing
    `rollback()` (which is unchanged). `manager.py` — the `ROLLBACK` branch
    becomes `reply, restored = rollback_result(core)`, `core.transport.reply(
    reply)`, and on `restored` the existing log / callback / replay-floor /
    reset sequence.
  - Test: `src/otampy/device/tests/test_restore.py` — `rollback_result` returns
    each of the three rows (revertible → `(b"ROLLBACK_OK", 2)` with the targets
    holding the previous content and the journal gone; no `.bck` →
    `(b"ROLLBACK_ERR:Nothing to roll back", 0)` with the journal *content*
    unchanged; `committing` → `(b"ROLLBACK_ERR:Commit in flight", 0)`, nothing
    renamed). The existing `test_ota_manager.py` `ROLLBACK` tests are the
    refactor's guard and must pass untouched.
  - Done when: `uv run pytest src/otampy/device/tests/test_restore.py
    src/otampy/device/tests/test_ota_manager.py -q` passes, and the
    `ROLLBACK_ERR` strings appear exactly once in the tree (grep).

- [x] **3. `boot._run_boot_listen()` — the window, not yet wired in**
  - What changes: `boot.py` — the three new constants and
    `_run_boot_listen(core)` implementing the dispatch table above. Returns
    `True` when it handled a command that reset the board (so the caller
    returns — a mocked `machine.reset` in tests does not actually reset),
    `False` when the window simply expired. Config read and sanitised like
    `_run_default_update_loop` does `OTA_TIMEOUT_MS`, except `<= 0` disables and
    returns `False` immediately with no `read()` at all. Packet normalisation
    follows the update loop's bytes-oriented shape; `restore` and `authgate`
    are imported lazily inside their branches.
  - Test: `src/otampy/device/tests/test_ota_boot.py` — (a) no packet arrives →
    returns `False` after roughly the configured window, `machine.reset` not
    called; (b) `OTA_BOOT_LISTEN_MS=0` → returns `False` immediately and
    `core.transport.read` was never called; (c) `UPDATE_REQUEST` → reply is
    exactly `b"REBOOTING"`, the flag file exists on disk, `machine.reset`
    called, returns `True`; (d) `ROLLBACK` with a revertible journal → reply
    `b"ROLLBACK_OK"`, targets restored, journal gone, reset called; (e)
    `ROLLBACK` with nothing retained → reply
    `b"ROLLBACK_ERR:Nothing to roll back"`, **`machine.reset` not called**, and
    a subsequent `UPDATE_REQUEST` in the same window is still served (proves a
    refusal does not close the window); (f) `PING` → reply
    `b"ERROR:Recovery window"`, no reset; (g) with `OTA_REQUIRE_AUTH` set, an
    unwrapped `ROLLBACK` → reply `b"ERROR:Unauthenticated"`, nothing restored,
    no reset, and a correctly signed `ROLLBACK` in the same window succeeds.
  - Done when: those tests pass and `uv run ruff check .` is clean.

- [x] **4. Wire the window into `boot.run()`**
  - What changes: `boot.run()` — hoist the `UPDATE_REQUEST_FLAG_FILE` `stat`
    above the window, then after `repair()`/`trial()` and before the existing
    `if has_flag:` block, add `if not has_flag and _run_boot_listen(core):
    return`. Add `"authgate"` to `ota.OTA.boot()`'s teardown submodule list.
  - Test: `test_ota_boot.py` — (a) flag **present** → `_run_boot_listen` is
    never called (spy) and the existing `READY` + update-loop path runs
    unchanged; (b) flag absent, window expires → `_cleanup_orphaned_ota` still
    runs afterwards exactly as today; (c) flag absent, window handles
    `UPDATE_REQUEST` → `run()` returns immediately and `_cleanup_orphaned_ota`
    is **not** called; (d) a `trial` journal past `OTA_TRIAL_BOOTS` still
    auto-restores and resets *before* the window opens (spy: `_run_boot_listen`
    not called). Every existing `test_ota_boot.py` test still passes.
  - Done when: full `uv run pytest src/otampy/device/tests/ -q` passes.

- [x] **5. Host `recovery_wait_seconds` + `_recover_query()`**
  - What changes: `cli.py` — the `recovery_wait_seconds` entry in
    `_CONFIG_SPEC` (default `60.0`, env `OTAMPY_RECOVERY_WAIT`, display
    `recovery-wait`), and `_recover_query(ctx, command, expected_prefix)`:
    print the power-cycle instruction and that a missed window just means
    cycling again, then loop `_query(...)` — swallowing its timeout
    `ClickException` — until a reply arrives or the deadline passes, raising a
    `ClickException` naming `recovery-wait` on expiry. `DeviceError` propagates
    to the caller unchanged (it means the device *answered*).
  - Test: `tests/test_cli.py` — (a) `_recover_query` returns the payload when
    the mock device answers on the third attempt; (b) it raises
    `ClickException` with the recovery-wait message when nothing ever answers
    (patch the clock or set the key to a tiny value — do not sleep for 60 s in
    a test); (c) `otampy config` lists `recovery-wait` with its default.
  - Done when: those tests pass and no test takes materially longer than before.

- [x] **6. `otampy upd --recover` and `otampy rollback --recover`**
  - What changes: `cli.py` — `--recover` on both commands. In `update()`,
    `--recover` replaces the `_send_command(ctx, b"UPDATE_REQUEST",
    b"REBOOTING")` call with `_recover_query(ctx, b"UPDATE_REQUEST",
    b"REBOOTING")`; everything from `time.sleep(0.5)` / the `READY` loop onward
    is untouched. In `rollback()`, the red confirm prompt runs first (before
    any power-cycle instruction), then `--recover` routes the `ROLLBACK`
    through `_recover_query` instead of `_query`; reply handling, the
    `ROLLBACK_ERR` exit-1 path and `_wait_for_pong` are unchanged except for a
    recovery-specific timeout message noting the previous version may itself be
    unhealthy.
  - Test: `tests/test_cli.py` — (a) `upd --recover` against a mock device that
    only answers on the second attempt completes a full session and
    `send.assert_any_call(b"UPDATE_REQUEST")`, with **no** `REBOOTING` query
    sent before the recovery loop; (b) `upd` without `--recover` is byte-for-byte
    the existing behaviour (existing tests, unmodified); (c) `rollback
    --recover` with confirm-yes and `ROLLBACK_OK` then `PONG` → exit 0;
    (d) `rollback --recover` with confirm-**no** → exits 0 and **nothing is
    sent and no power-cycle prompt is printed**; (e) `rollback --recover` where
    nothing ever answers → non-zero with the recovery-wait message.
  - Done when: those tests pass and `python3 .agents/scripts/pre_flight_check.py`
    is clean.

- [x] **7. Docs, config example, changelog, findings**
  - What changes: `docs/protocol.md` §2.4 — a subsection on the recovery
    window: when it opens (every boot with no flag set, after `repair()`/
    `trial()`), the exact dispatch table, that it is silent and how the host
    lands a command in it, that it enforces auth, and its hard limits (needs
    `boot.py` to run; does not answer `PING`). `docs/architecture.md` —
    `OTA_BOOT_LISTEN_MS` in the `configota.py` block, a paragraph under "Trial
    boot, confirmation, and auto-restore" covering the window and the custom-
    `boot.py`-watchdog caveat, and correction of the existing sentence that
    says a device stranded before `main.py` "needs the boot-time recovery
    window" — it now has one. `configota.example.py` — `OTA_BOOT_LISTEN_MS`
    with a comment on the per-boot cost and `0` to disable. `CHANGELOG.md` —
    `Unreleased`. `docs/development/findings.md` — F-08's "belongs with
    sub-task 4" line corrected to say why it does not, and a matching `TODO.md`
    item proposed to Simon (do not edit `TODO.md` without approval).
  - Test: none — docs.
  - Done when: no doc still describes the boot-time recovery window as planned
    or missing, and `OTA_BOOT_LISTEN_MS`'s per-boot cost is stated wherever the
    key is documented.

- [x] **8. Repair F-09 — `OTA.boot()` teardown crashes on every no-auth boot**
  - What changes: `ota.py` `OTA.boot()` teardown — `except AttributeError` →
    `except (AttributeError, KeyError)` at the `delattr(package, submodule)`
    call. MicroPython raises `KeyError` (not `AttributeError`) for a missing
    module attribute, and `authgate` is absent on every boot that did not
    configure `OTA_REQUIRE_AUTH`, so boot.py crashed on every such boot and the
    device was stranded. Found on the rig during this sub-task's HIL.
  - Test: `test_boot_teardown_survives_micropython_delattr_keyerror`
    (`test_ota_facade.py`) — patches `builtins.delattr` to raise `KeyError` for
    a missing attribute, asserts `ota.boot()` does not propagate it. Red before
    the fix (`KeyError` escapes), green after.
  - Done when: that test passes, `pre_flight_check.py` is clean, and the rig
    boots to a working `main.py` (HIL test 0 below) after a clean redeploy.

- [x] **9. Repair F-10 — make the recovery window hittable**
  - What changes: `cli.py` — `_recover_query` wraps its blind-retry loop in a
    new `_fast_recovery_handshake()` context manager that shrinks
    `urst.constants.ACK_TIMEOUT_MS` (1000 → 120) and `MAX_RETRIES` (3 → 1) for
    the poll only, restoring them on exit; and calls `_query(..., fast=True)`,
    a new keyword-only flag that drops `_query`'s inner `query_retries` loop to
    a single attempt with no backoff. Together these take the host's
    CONNECT cadence from ~1 per 12 s to several per second, against a ~1 s
    window. `src/otampy/device/tests/conftest.py` — the fake `urst` module it
    installs during collection now carries the real `urst.constants` (a
    pure-data module) instead of a 2-field stub, since `tests/` now reads
    `ACK_TIMEOUT_MS` through it.
  - Test: `test_recover_query_polls_with_a_fail_fast_handshake_and_restores_it`,
    `test_recover_query_restores_handshake_timing_even_on_timeout`,
    `test_query_fast_mode_makes_one_attempt_with_no_backoff` (all
    `tests/test_cli.py`). Red before the change.
  - Done when: those tests pass, `pre_flight_check.py` is clean, and HIL tests
    1, 2, 5, 6 land a command in the window within a power-cycle or two.
  - **⚠ Ticked in error (corrected 2026-09-10).** The code and unit tests
    landed and are sound, but the "done when" was never met: the HIL tests
    still failed 0/N afterwards. The premise was also wrong — see step 10.
    Kept ticked because the change itself is committed and worth keeping
    (a ~12 s CONNECT cadence was genuinely bad); the *finding* it claimed to
    repair is still open.

- [ ] **10. Repair F-10 (real) — make the window overlap the radio's wake-up**
  - **Blocked on a spec decision.** Root-caused 2026-09-10 by on-device
    instrumentation: the window opens at t+2.05 s and closes at t+3.15 s, but
    a power-cycled XBee does not deliver its first frame until t+3.6 s–8.7 s.
    Cold radio vs warm radio is the whole effect (control: after a *software*
    reset, the first packet lands 80 ms into the window). Host retry cadence
    was never the binding constraint. Full evidence in
    `f10-window-evidence.md`, analysis in the dev log and F-10.
  - This falsifies signed-off **Protocol decision D2** ("silent window + host
    blind-retry"), so it is not mine to improvise. The trade to settle: a wide
    window delays `main.py` on *every* healthy boot; candidate shapes include
    widening unconditionally, delay-then-listen, opening a long window only
    when the journal shows an unconfirmed candidate, or reinstating the
    dropped beacon. Route through `/sl-spec` before any code.
  - Done when: a genuinely stranded device is recovered over the radio at the
    *shipped* default config, repeatably, across several power cycles — plus
    a decision recorded for the per-boot cost it imposes.

## Verification

- **Host:** `python3 .agents/scripts/pre_flight_check.py` (ruff + full pytest,
  mirrors CI). Per-step: `uv run pytest src/otampy/device/tests/ tests/test_cli.py -q`.
- **Hardware** (Pico W, `otampy` deployed from the build branch — end of
  sub-task, not between steps). Tests 1 and 2 deliberately strand the device;
  keep USB access available before starting.
  1. **Recover a device stranded by a fatal `main.py`.** From a healthy build,
     `otampy upd --no-confirm main.py` with a `main.py` that raises on import
     and arms **no** watchdog (so trial auto-restore cannot fire and mask the
     result). Evidence the device is genuinely stranded: `otampy ping` times
     out. Then `otampy rollback --recover`, power-cycle at the prompt.
     Evidence: `ROLLBACK_OK`, `otampy ping` → `PONG`, `otampy cat /main.py` is
     the previous good version, `otampy ls /` shows no `main.py.bck` and no
     `otampy-update.journal`.
  2. **Update a stranded device.** Strand it again as above, then
     `otampy upd --recover main.py` with a good `main.py`. Evidence: the CLI
     prints `Device is READY. Handshake complete.` (proving the window's
     `UPDATE_REQUEST` → flag → reset path fed the normal update session),
     then `COMMIT_OK`, then `Candidate confirmed.`; `otampy ping` → `PONG`.
  3. **Boot-delay cost.** Time power-on → first `PONG` with
     `OTA_BOOT_LISTEN_MS = 1000`, then with `0`, three runs each, power-cycling
     fully between runs. Evidence: the difference is ~1 s ±0.3 s. A difference
     near 8 s fails the step — it would mean a blocking reliable send with no
     listener (see the D2 note). Record all six figures in the dev log.
  4. **The window is not permanently open.** With the device healthy and
     running, `otampy rollback --recover` **without** power-cycling. Evidence:
     it times out with the recovery-wait message and `otampy ping` still
     answers `PONG` immediately — the device never reset and was never in a
     window.
  5. **The window is not an auth bypass.** Set `OTA_REQUIRE_AUTH = True` and
     `COMMAND_AUTH_KEY` on the device. With `OTAMPY_COMMAND_AUTH_KEY` **unset**
     on the host, `otampy rollback --recover` + power cycle. Evidence: the CLI
     reports the device's `Unauthenticated` error, and `otampy ls /` (with the
     key set) shows the `.bck` set still present — nothing was reverted. Repeat
     with the key set: it succeeds.
  6. **Refusal does not consume the window.** On a device with no retained
     generation, `otampy rollback --recover` + power cycle → `Nothing to roll
     back`, exit 1. Then, without a further power cycle being *required* by the
     design, confirm via test 2's flow that a window is still reachable.
- **Manual:** Simon runs tests 1, 2 and 3 and confirms by eye that a device he
  has deliberately bricked at the application level comes back over the radio
  with no USB, and that the per-boot cost he is paying for that is the ~1 s he
  agreed to.

## Risks and open questions

- **D2 changed (see the Protocol decision).** The signed-off `RECOVERY` beacon
  is dropped for a silent window plus host blind-retry, because an
  unacknowledged `Urst.send()` costs up to ~8 s per boot. Re-confirm before
  building; everything else in the spec is independent of it.
- **Blind retry can miss the window.** The window is ~1 s per boot and the host
  is retrying, not synchronised. Expected outcome is "it lands within a cycle
  or two"; the failure mode is benign (power-cycle again) but it is not a
  guarantee, and the CLI must say so rather than implying one attempt suffices.
  HIL test 1 is the honest measure — if it routinely needs several cycles, that
  is worth recording in the dev log and possibly revisiting the beacon question
  with an unreliable-send mechanism in URST.
- **Every boot costs ~1 s.** Paid by every deployment that upgrades, including
  each iteration of a boot-loop. `0` disables it, but a device with the window
  disabled has no recovery path — that is the trade being made, and it should
  be stated plainly in the docs rather than buried.
- **The window does not answer `PING`.** Anyone probing a device mid-window
  sees `ERROR:Recovery window`, which is a *new* response an existing script
  could hit during the first second after a reset. Low risk (scripts already
  tolerate a device being absent right after a reboot) but it is a real change
  in observable behaviour for `ping`.
- **The auth extraction touches the shipped runtime auth path.** Step 1 is a
  pure move with no new tests, guarded only by the existing suites — run
  `test_manager_auth.py` and `test_command_auth_contract.py` in full before
  moving on, and re-check the `_replay_guard` early-out really did move to the
  call sites (a device with auth off must not import `authgate`).
- **`reply()` can raise `RuntimeError`** when nothing has been read
  (`urst/core_handler.py:160`) — the same failure mode as the deferred TODO
  item about an interrupted handshake crashing `boot.py`. The window only calls
  `reply()` after a successful `read()`, so `last_request_id` is set; noted so
  the build does not introduce an unprompted `reply()` here.
- **F-08 is not fixed and cannot be by this sub-task.** Flagged so the gate
  review sees it as reasoned, not overlooked; step 7 re-files it.
- **The device is not running its application during the window.** For an
  integrator like `diff-drive-robot` that is ~1 s more with no watchdog and no
  motor control, this early in boot — safe, but worth stating in the docs for
  anyone whose hardware needs attention sooner than that.
- **A refusal reply mid-window keeps the window open**, which means a
  misconfigured host could in principle keep a device in the window with
  repeated bad commands. Bounded: the window's deadline is absolute and is not
  extended by activity, unlike `_run_default_update_loop`'s inactivity timeout.
  Verify that in step 3's test (a).

## Notes for the build

- Device tests import `from device_otampy import boot, restore` (see
  `src/otampy/device/tests/conftest.py`); `machine` is globally mocked, so
  assert `machine.reset` calls rather than effects.
- `restore.py`'s "never raises" rule is absolute and now extends to
  `rollback_result()`. `boot._run_boot_listen` likewise runs with no `try`
  around it in the shipped scaffolds.
- The window's dispatch deliberately does **not** import `manager` — that would
  pull the whole runtime command surface into the boot phase. `authgate` exists
  precisely so it does not have to.
- `_run_default_update_loop` uses an *inactivity* timeout; the window uses an
  *absolute* deadline. Do not copy the `last_activity` reset pattern into it.
- `manager.poll` and `_run_default_update_loop` normalise packets differently
  (str-decode vs bytes-strip). The window follows the bytes-oriented update-loop
  shape, since it lives in `boot.py`; do not import either one's helper.
- `commit()` and `filecopy._commit` stay separate (sub-task 1's note) — this
  spec touches neither.
- Sub-task 3's spec and log (`failsafe-update-rollback-{spec,log}.md`) carry the
  `ROLLBACK` contract and the HIL procedure tests 1 and 4 here extend.
- Findings ledger: `docs/development/findings.md` — F-04/F-05/F-06/F-07 closed,
  F-08 open P2 (out of scope, re-filed in step 7). No open P0/P1.
- HIL tests 1 and 2 leave the device deliberately bricked at the application
  level. Per `CLAUDE.md`, any USB/`mpremote` fallback must be followed by a
  genuine hard `mpremote connect PORT reset` and an undisturbed restart before
  the device is trusted again — and the recovery must then be verified over the
  radio, not over USB.
