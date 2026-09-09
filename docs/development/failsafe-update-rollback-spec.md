# ROLLBACK command + `otampy rollback` CLI — spec

**TODO item:** `[ ] 3. `ROLLBACK` command + `otampy rollback` CLI.` (sub-task 3 of **Fail-safe Updates**)
**Status:** approve
**Components:** `src/otampy/device/lib/otampy/` (`restore.py`, `manager.py`), `src/otampy/cli.py`, `docs/protocol.md`, `docs/architecture.md`, `CHANGELOG.md`
**Dev log:** `docs/development/failsafe-update-rollback-log.md` (created by `/sl-build`)

## Goal

After this ships, a user who has taken an update that **booted, answered
`PING`, and was confirmed** — but turns out to be wrong — can revert it over
the radio with one command. `otampy rollback` sends a new channel-0 `ROLLBACK`
command; the device renames the whole retained `.bck` generation back over its
targets, removes the journal, replies, and resets onto the previous version.
The CLI then waits for the reverted build to answer `PING` and reports that it
is running and stable. When there is nothing to revert (no retained
generation) or a commit is mid-flight, the device refuses without resetting and
the CLI says why and exits non-zero.

This closes the gap sub-task 2 deliberately left: auto-rollback only fires on a
*reboot during the trial window*, so a candidate that runs, passes a shallow
`PING` health check, gets confirmed, and only then proves faulty had no revert
path. It does **not** cover a device that never reaches its poll loop — that is
sub-task 4.

## In scope

- **`restore.rollback(core)`** — the user-initiated revert primitive. Reads the
  journal; refuses while a `committing` marker is present; returns `0` without
  touching anything when no retained `.bck` survives; otherwise delegates to
  the existing `restore_all()` and returns its count.
- **`manager.poll` — `ROLLBACK` branch.** Restores, replies
  `ROLLBACK_OK` / `ROLLBACK_ERR:<reason>`, and on success runs the application
  callback, persists the replay floor, and `machine.reset()`s. `restore` is
  imported lazily per command, as `CONFIRM`/`UPDATE_STATE` already are.
- **Host `otampy rollback`** — red confirmation prompt (like `rb`/`sr`), sends
  `ROLLBACK`, prints the device's reason and exits 1 on `ROLLBACK_ERR`, and on
  `ROLLBACK_OK` waits for the reverted build to answer `PING` then reports
  success.
- **`_wait_for_pong()` host helper** — extracted from `_post_commit_confirm`'s
  existing reconnect loop and reused by `rollback`, so there is one
  "device is rebooting, keep trying" implementation, not two.
- **Docs** — `docs/protocol.md` §2.1/§2.4 (`ROLLBACK`, and the lifecycle
  paragraph's "run `otampy rollback` (planned)" corrected to shipped),
  `docs/architecture.md` (the revert path alongside trial boot),
  `CHANGELOG.md` `Unreleased`.
- **Tests** — `test_restore.py`, `test_ota_manager.py`, `tests/test_cli.py`.

## Out of scope

- **Boot-time recovery listen window** — sub-task 4. `ROLLBACK` here is served
  only by `manager.poll`, i.e. only while `main.py`'s poll loop runs. A device
  stranded before that point still needs sub-task 4.
- **F-08** (P2, open — a power loss while `restore.py` itself is the mid-commit
  file). Unchanged by this sub-task, which only adds another lazy `restore`
  caller. Owned by sub-task 4.
- **Rolling back more than one generation.** Only one previous generation is
  ever retained (`UPDATE_START` clears the prior one), so `ROLLBACK` is
  one-shot: after it there is no `.bck` left and a second `ROLLBACK` correctly
  reports nothing to revert. Deeper history needs a dual-slot layout.
- **`ota.rollback()` application facade.** `confirm()` got one because an app
  can usefully self-confirm; a self-rollback would additionally have to reset
  the board, which is the application's decision to make, not a one-liner.
  Trivially addable later with no contract change.
- **RTC staging before the rollback reset.** Signed off 2026-09-09: rollback is
  the recovery path for a possibly-broken device, so it makes the minimum
  number of flash writes. `otampy rb` sets the clock afterwards if wanted.
- **A `--yes` flag to skip the prompt.** `rb`, `sr` and `rm` all prompt
  unconditionally; `rollback` matches them. See Risks.
- **Filesystem-atomic transactions** — same boundary as sub-tasks 1 and 2.

## Protocol decision

- **Existing OTAmpy/URST command reusable?** No. `CONFIRM` takes a candidate
  *off* trial and `UPDATE_STATE` is read-only; neither can revert. `RB` reboots
  onto whatever is on disk. `ROLLBACK` is genuinely new.
- **Channel:** 0 (reliable). Dispatched by `manager.poll` alongside
  `PING`/`RB`/`CONFIRM`, and wrapped by the auth envelope automatically when
  `OTA_REQUIRE_AUTH` is set. Because it resets the board it takes the same
  pre-reset path as `RB`: application callback, then `_persist_replay_floor`,
  then `machine.reset()`.
- **Wire format change?** No URST change. One new application-layer command;
  `PROTOCOL_VERSION` does not move. Host `cli.py` and device `manager.py`
  change together. No mux/gateway involvement (channel 0 only).
- **Signed off:** 2026-09-08 by Simon (the Fail-safe Updates protocol decision
  names `ROLLBACK` as a planned channel-0 command). Four sub-decisions
  confirmed 2026-09-09: `ROLLBACK_ERR:<reason>` grammar; restore *before*
  replying; no RTC staging; the CLI waits for `PONG` after the reset.

## Data and contracts

### `ROLLBACK` — **load-bearing**

| Request | Sender | Response | Effect |
| --- | --- | --- | --- |
| `ROLLBACK` | Host | `ROLLBACK_OK` | The retained generation was renamed back and the journal removed. The device then resets onto the previous version. |
| `ROLLBACK` | Host | `ROLLBACK_ERR:Nothing to roll back` | No journal, or no journalled `.bck` survives. **Nothing is touched and the device does not reset.** |
| `ROLLBACK` | Host | `ROLLBACK_ERR:Commit in flight` | Journal line 1 is `committing` — `repair()` owns that state. Nothing is touched, no reset. |

Ordering on the success path is fixed and load-bearing: **restore → reply →
application callback → `_persist_replay_floor` → `machine.reset()`.** The
restore comes first so the reply can state what actually happened; everything
after the reply mirrors `RB` exactly.

The generation the device lands on has **no journal and no `.bck`**, i.e.
`UPDATE_STATE` → `STATE_OK:stable:0`. It is not itself on trial and cannot be
rolled back again.

### `restore.rollback(core)` — **load-bearing**

| Return | Meaning |
| --- | --- |
| `_ROLLBACK_BUSY` (`-1`) | Journal state is `committing`. Caller must not reset. |
| `0` | No journal, or no journalled `<path>.bck` exists. **The journal is left untouched.** Caller must not reset. |
| `n > 0` | `restore_all()` restored `n` files and removed the journal. Caller resets. |

```python
_ROLLBACK_BUSY = -1

def rollback(core):
    _, st, paths = read_journal(core)
    if st == _STATE_COMMITTING:
        return _ROLLBACK_BUSY
    for target in paths:
        if _exists(target + _BACKUP_SUFFIX):
            return restore_all(core)
    return 0
```

The pre-scan for a surviving `.bck` is not redundant: `restore_all()`
unconditionally removes the journal, so calling it with nothing to restore
would silently take a trialling candidate off trial (stopping the boot counter)
while telling the host the rollback failed. Never raises, like every other
function in `restore.py`.

### Host

No new config keys. The reconnect wait reuses `update_ready_timeout_seconds`
(default 10.0) and `query_retry_backoff_seconds`, exactly as
`_post_commit_confirm` does today.

`_query(ctx, b"ROLLBACK", b"ROLLBACK_")` returns `b"OK"` or
`b"ERR:<reason>"` as the payload (the prefix is followed by `E`/`O`, not `:`,
so `_query`'s colon-stripping does not apply). No change to `_query`,
`DeviceError`, or `_friendly_error`.

Named constants: `restore._ROLLBACK_BUSY`. The command token and the two error
strings live inline in `manager.poll`'s `elif` chain, where every other command
string already lives.

## Device cost

- **Hot-path allocation:** none. `rollback()` runs only on the matching
  command — one `read_journal` (a single `open`/`read`), up to *n* `stat` calls
  for the pre-scan (*n* = journal length, typically < 10), then `restore_all()`.
  No change to `poll()`'s per-call cost: the new `elif` sits after the existing
  chain and `restore` is imported lazily inside the branch, so `manager`'s
  import weight is unchanged (the lazy-load facade test still applies).
- **Blocking operations:** unlike sub-task 2's boot-time `restore_all()`, this
  one runs from `main.py` with the **application's watchdog armed**. It is
  bounded to *n* `stat`/`remove`/`rename` pairs with no I/O wait loop —
  sub-millisecond to low milliseconds, far under the ~8388 ms RP2040 WDT cap —
  and the path ends in `machine.reset()` regardless. The `poll(heartbeat=...)`
  hook is not needed here (it exists for multi-fragment CAT/LS responses).
- **Named constants:** `_ROLLBACK_BUSY` module-level in `restore.py`.

## Build steps

- [x] **1. `restore.rollback()`**
  - What changes: `src/otampy/device/lib/otampy/restore.py` — add
    `_ROLLBACK_BUSY` and `rollback(core)` per the contract above, with a
    docstring covering all three returns and why the `.bck` pre-scan exists.
  - Test: `src/otampy/device/tests/test_restore.py` — (a) `trial` journal with
    two paths, both `.bck` present → returns `2`, both targets are the previous
    content, journal file gone; (b) `confirmed` journal, `.bck` present →
    same result (a confirmed candidate is still revertible — this is the whole
    point of the sub-task); (c) journal with paths but **no** `.bck` on disk →
    returns `0` **and the journal file is unchanged** (assert its content, not
    just its existence); (d) `committing` journal → returns `_ROLLBACK_BUSY`,
    nothing renamed, journal unchanged; (e) no journal at all → `0`.
  - Done when: `uv run pytest src/otampy/device/tests/test_restore.py -q`
    passes and `uv run ruff check .` is clean.

- [x] **2. `manager.poll` — `ROLLBACK` branch**
  - What changes: `manager.py` — one `elif cmd == "ROLLBACK"` branch with a
    local `from .restore import _ROLLBACK_BUSY, rollback`. Restore first, then
    reply `ROLLBACK_OK` or the matching `ROLLBACK_ERR:<reason>`; on success
    only, log, `_do_callback(core, callback)`, `_persist_replay_floor(core)`,
    `machine.reset()`.
  - Test: `src/otampy/device/tests/test_ota_manager.py` — (a) revertible
    journal → reply is exactly `b"ROLLBACK_OK"`, the targets hold the previous
    content, and the mocked `machine.reset` was called; (b) nothing to revert →
    reply `b"ROLLBACK_ERR:Nothing to roll back"` and **`machine.reset` was not
    called**; (c) `committing` journal → `b"ROLLBACK_ERR:Commit in flight"`, no
    reset; (d) the success path calls the application callback and
    `_persist_replay_floor` before the reset (spy on the callback; assert the
    replay-floor file exists after a run with auth configured).
    `test_ota_facade.py::test_package_import_does_not_eagerly_load_operating_modes`
    must still pass.
  - Done when: `uv run pytest src/otampy/device/tests/ -q` passes.

- [x] **3. Extract the host `PONG` wait loop (refactor only)**
  - What changes: `src/otampy/cli.py` — lift `_post_commit_confirm`'s
    `while True: _query(PING)` loop into `_wait_for_pong(ctx, timeout_message)`
    (raising `click.ClickException(timeout_message)` on expiry) and call it
    from `_post_commit_confirm`. No behaviour change; the existing message text
    is passed in verbatim.
  - Test: none new — the existing `tests/test_cli.py` update tests (including
    the "`PING` never answers → non-zero + warning text" case) are the proof.
  - Done when: `uv run pytest tests/test_cli.py -q` passes unchanged, and the
    `PING`-retry loop appears exactly once in `cli.py` (grep).

- [x] **4. `otampy rollback` command**
  - What changes: `src/otampy/cli.py` — a new `@cli.command(name="rollback")`.
    Red `click.confirm` prompt naming what will happen ("revert the device to
    the previously retained version and reboot it"); on decline print
    `Aborted.` and return without sending anything. Then
    `_query(ctx, b"ROLLBACK", b"ROLLBACK_")`; on an `ERR` payload print the
    device's reason in red and `raise SystemExit(1)`; on `OK` print that the
    device is reverting, call `_wait_for_pong` with a rollback-specific timeout
    message, then print success and that the device is now running the previous
    (stable) version. `DeviceError` handled via `_handle_device_error` like
    `ping`.
  - Test: `tests/test_cli.py` — (a) confirm-yes + `ROLLBACK_OK` then `PONG` →
    exit 0, `send.assert_any_call(b"ROLLBACK")`, success text present;
    (b) `ROLLBACK_ERR:Nothing to roll back` → exit 1 with that reason in the
    output and **no** `PING` sent afterwards; (c) confirm-no → exit 0 and
    nothing sent at all; (d) `ROLLBACK_OK` but `PING` never answers → non-zero
    with the rollback timeout message.
  - Done when: those tests pass and
    `python3 .agents/scripts/pre_flight_check.py` is clean.

- [x] **5. Docs + changelog**
  - What changes: `docs/protocol.md` — `ROLLBACK` row in the §2.1 control
    table and the §2.4 update-sequence table (all three responses); in the
    trial-boot lifecycle paragraph, replace "run `otampy rollback` (planned)"
    with the shipped behaviour and state that `ROLLBACK` needs the poll loop
    (so a device that never reaches `main.py` is still sub-task 4's problem),
    and that the reverted-to generation is `stable` with no retained `.bck`.
    `docs/architecture.md` — a short paragraph under "Trial boot, confirmation,
    and auto-restore" covering the user-initiated revert and its one-shot
    nature. `CHANGELOG.md` — an `Unreleased` entry under the existing
    retain-previous/trial-boot block.
  - Test: none — docs.
  - Done when: no doc still describes `otampy rollback` as planned, and the
    one-generation limit is stated wherever the revert is described.

## Verification

- **Host:** `python3 .agents/scripts/pre_flight_check.py` (ruff + full pytest,
  mirrors CI). Per-step: `uv run pytest src/otampy/device/tests/test_restore.py
  src/otampy/device/tests/test_ota_manager.py tests/test_cli.py -q`.
- **Hardware** (Pico W, `otampy` deployed from the build branch — end of
  sub-task, not between steps):
  1. **Revert a confirmed candidate.** From a known `main.py` v1, run
     `otampy upd main.py` with a visible v2 change; let it auto-confirm.
     `otampy state` → stable, `otampy ls /` shows `main.py.bck`. Then
     `otampy rollback` → prompt, `ROLLBACK_OK`, the CLI reports the device
     back. Evidence: `otampy cat /main.py` is **v1**; `otampy ls /` shows **no**
     `main.py.bck` and **no** `otampy-update.journal`; `otampy state` →
     `Running a confirmed (stable) build.`
  2. **Second rollback refuses without rebooting.** Immediately run
     `otampy rollback` again. Evidence: output contains
     `Nothing to roll back`, exit status is 1, and `otampy ping` answers
     `PONG` **immediately** (no reboot delay) — the device never reset.
  3. **Revert an unconfirmed candidate.** `otampy upd --no-confirm main.py`
     (v2). `otampy state` → `trial`. `otampy rollback`. Evidence: v1 is back,
     journal gone, `otampy state` → stable — the trial is abandoned, not
     merely paused.
  4. **Replay floor survives the rollback reset.** With `OTA_REQUIRE_AUTH` set
     and a `COMMAND_AUTH_KEY` configured, repeat test 1. Evidence: the first
     `otampy ping` after the rollback reset returns `PONG`, not
     `ERROR:Replayed` — `_persist_replay_floor` ran before the reset.
- **Manual:** Simon runs tests 1–3 and confirms by eye that a confirmed,
  healthy-looking-but-wrong update can be undone over the radio with no USB,
  and that the refusal case leaves the device untouched.

## Risks and open questions

- **`ROLLBACK` needs the poll loop.** It only works while `main.py` runs. The
  exact failure it cannot fix — a candidate that crashes or hangs before
  `poll()` — is sub-task 4's boot listen window. Stated in the docs so the
  command is not mistaken for a universal recovery path.
- **One-shot by design.** After a rollback there is no `.bck`, so the revert
  cannot itself be undone. If the previous generation turns out to be the
  broken one, recovery is a fresh `otampy upd` (or USB). Inherent to retaining
  exactly one generation; not engineered away.
- **The prompt blocks scripting.** `otampy rollback` in a non-interactive
  context needs `yes | otampy rollback`. Consistent with `rb`/`sr`/`rm`; a
  `--yes` flag for all four is a separate, larger consistency change.
- **Reply-then-reset is not delivery-guaranteed.** If `ROLLBACK_OK` is lost on
  the link, the device still reverts and resets while the host reports a
  timeout. Identical to `RB` today, and the CLI's `PONG` wait recovers the
  truth on the next command. Accepted.
- **The application callback runs after the files have moved.** Unlike `RB`,
  the filesystem has already changed by the time the safe-shutdown callback
  fires. Considered and accepted: the callback's job is to make *hardware*
  safe, both happen within milliseconds, and the reset is last either way.
  Running the callback first would mean disturbing the application before
  knowing whether the rollback is even possible.
- **`_wait_for_pong` extraction touches the shipped `upd` path.** Step 3 is a
  pure refactor with no new tests, so the existing `upd` tests are the only
  guard — re-run the full `tests/test_cli.py`, not a subset, before moving on.
- **A `.bck` rename failing inside `restore_all()`** leaves that `.bck` orphaned
  after the journal is removed; the next boot's `_cleanup_orphaned_ota` sweeps
  it. Same best-effort convergence as sub-tasks 1 and 2.
- **F-08 (P2, open)** is in the touched area (`restore.py`) and is deliberately
  not addressed here — flagged so the gate review sees it as known and deferred
  to sub-task 4, not overlooked.

## Notes for the build

- Device tests import `from device_otampy import restore` (see
  `src/otampy/device/tests/conftest.py`); `machine` is globally mocked there,
  so assert `machine.reset` calls rather than effects.
- `restore.py`'s "never raises" rule is absolute — `rollback()` runs under
  `manager.poll` with no `try` around it in the shipped scaffolds.
- Reuse `restore_all()` unchanged. Do **not** add a second whole-set restore
  implementation, and do not touch `commit()` or `filecopy._commit`.
- `manager.poll` already imports `machine` at module scope (used by `RB`/`SR`)
  — no new import needed for the reset.
- `test_manager_auth.py` parametrises a few specific commands rather than
  enumerating an accepted list, so `ROLLBACK` needs nothing there;
  `test_command_auth_contract.py` pins the HMAC primitives only. Re-check both
  before assuming so.
- Sub-task 2 spec and log (`failsafe-update-trial-boot-{spec,log}.md`) carry the
  journal grammar and the HIL procedure this sub-task's hardware tests extend.
- Findings ledger: `docs/development/findings.md` (F-04/F-05/F-06 closed,
  F-07 closed, F-08 open P2).
