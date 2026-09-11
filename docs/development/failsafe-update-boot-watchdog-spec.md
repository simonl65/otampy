# Feed a caller-supplied watchdog inside the boot-time recovery window — spec

**TODO item:** "Feed a caller-supplied watchdog inside the boot-time recovery
window." (follow-up to F-12, `docs/development/findings.md`)
**Status:** approved
**Components:** `src/otampy/device/lib/otampy/` (`boot.py`, `core.py`,
`ota.py`), `src/otampy/device/examples/`, `docs/protocol.md`,
`docs/architecture.md`, `CHANGELOG.md`
**Dev log:** `docs/development/failsafe-update-boot-watchdog-log.md` (created
by `/sl-build`)

## Goal

An integrator who arms a hardware watchdog before `OTA(...).boot()` and passes
a `heartbeat` callable to `boot()` no longer gets reset mid-window or
mid-update. Today nothing feeds a watchdog anywhere inside `boot()` — not in
the wide recovery window's idle read loop (F-12, confirmed span 8899–9570 ms
against an 8388 ms RP2040 WDT cap) and not in `_run_default_update_loop`'s
session loop either, which is unbounded and can legitimately run far longer.
After this ships, both loops call an optional `heartbeat` at a bounded cadence,
mirroring the contract `OTA.poll()` already has, so `configota.example.py`'s
existing "keep this under your watchdog period" guidance becomes true instead
of false.

## In scope

- `OTA.boot(callback=None, heartbeat=None)` — new optional parameter,
  threaded down to `boot.run()`.
- `boot.run()` passes `heartbeat` into `_run_boot_listen` and
  `_run_default_update_loop`.
- Both loops call `heartbeat` at a bounded cadence during their idle/waiting
  spans, never on every fast-path iteration where no waiting occurred.
- A shared `_call_heartbeat` helper moved from `manager.py` to `core.py`
  (never-raises wrapper), imported by both `manager.py` and `boot.py`. No
  behaviour change for the existing `manager.poll()` callers.
- `configota.example.py` gains a worked comment showing a `heartbeat=wdt.feed`
  example instead of the current "keep this under your watchdog period"
  guidance that has no matching mechanism.
- `docs/protocol.md` §2.4 and `docs/architecture.md`'s boot-window section
  updated to say the window and the update loop are watchdog-safe when fed,
  replacing the "nothing arms a watchdog this early" / "gives up compatibility
  entirely" language that this change makes obsolete.
- `CHANGELOG.md` entry.

## Out of scope

- Changing `OTA_BOOT_RECOVERY_LISTEN_MS`'s default or any window timing — the
  wide window's duration is untouched; only what happens *inside* it changes.
  F-10 already called `8000` the tightest number the spec can afford.
- Feeding a watchdog inside `restore.commit()` / `restore_all()` — bounded by
  file count, not by waiting on the wire; no observed or plausible overrun.
  A later finding can open this if evidence ever shows otherwise.
- Constructing or owning a `WDT` object on the library's behalf — the library
  never imports `machine.WDT`; the integrator arms it and owns its period,
  exactly as `manager.poll()`'s `heartbeat` already works.
- Any change to `OTA.poll()` / `manager.poll()`'s existing `heartbeat`
  contract — this reuses it verbatim, it does not revise it.
- `boot()`'s existing `callback` parameter — untouched, stays the one-shot
  pre-reset hook it already is.

## Protocol decision

N/A — no wire change. Nothing added to channel 0 or channel 1; this is a
device-local API addition. (Confirmed: this follows §"applies only to
projects with a physical device, and only for anything that moves data to or
from the device" — this touches neither.)

## Data and contracts

- **New public signature:** `OTA.boot(self, callback=None, heartbeat=None)`.
  `heartbeat` is a zero-argument callable, called zero or more times during
  `boot()`, semantically identical to `OTA.poll()`'s existing `heartbeat` —
  "must be safe to call that way (e.g. feeding a hardware watchdog), not
  'about to reset' cleanup" (`manager.poll`'s docstring, `manager.py:264-270`;
  note `manager.py:79-88` is `_call_heartbeat` itself, whose comment is about
  exception-swallowing, not the calling contract). This wording is copied
  verbatim into `boot()`'s docstring rather than reworded, so the two stay
  provably identical.
- **`boot.run(core, callback=None, heartbeat=None)`** — new parameter, passed
  straight through to `_run_boot_listen` and `_run_default_update_loop`.
- **`_run_boot_listen(core, window_ms, heartbeat=None)`** — new parameter.
- **`_run_default_update_loop(core, heartbeat=None)`** — new parameter.
- **`core._call_heartbeat(heartbeat)`** — moved verbatim from
  `manager.py:_call_heartbeat`  (try/except swallowing all exceptions, per its
  existing comment: "must never be able to abort an in-progress transfer").
  `manager.py` drops its own definition and imports it from `.core` instead
  (module-level, alongside the existing `from .core import _get_config`). Its
  **two** existing call sites — `manager.py:169` and `manager.py:196`, both
  inside `_send_response` — are unchanged in behaviour. This is the
  DRY-load-bearing move; later work must not reintroduce a second copy.
- **No new config keys.** `docs/configuration.md` equivalent (this repo keeps
  device settings in `configota.example.py` + `docs/protocol.md`/
  `docs/architecture.md`, not a separate `configuration.md`) needs no new
  entry — the cadence constants below are code constants, not integrator
  config, because the integrator's only lever is the `heartbeat` callable
  itself and the WDT period they already chose.
- **No new timing constant.** `heartbeat` is called once per loop iteration in
  both loops, so the feed cadence rides their existing iteration rate rather
  than introducing an independent knob that could drift out of sync with it —
  see Device cost. (The only constant this spec adds is a name for
  `_run_default_update_loop`'s currently-hardcoded `_sleep_ms(10)`, folded
  into Build Step 2 as a DRY tidy-up to match `_BOOT_LISTEN_POLL_MS`.)

## Device cost

- **Hot-path allocation:** none. `heartbeat` defaults to `None`; `_call_heartbeat`
  is a single `if heartbeat is None: return` check plus, when set, one
  zero-argument call wrapped in `try/except Exception: pass` — matching the
  existing `manager.py` helper exactly, so this is a lateral move, not new
  allocation.
- **Blocking operations and how the watchdog is fed through them:**
  - **The feed goes at the top of each `while` body, before `read()` — not in
    the idle branch.** This placement is load-bearing, not stylistic.
    `_run_boot_listen`'s idle path is `read()` →
    `_sleep_ms(_BOOT_LISTEN_POLL_MS)` → `continue` (`_BOOT_LISTEN_POLL_MS =
    10`), but that is only *one* of five ways round the loop. The other four
    — empty-after-strip (`boot.py:444`), non-UTF-8
    (`boot.py:457`), failed auth (`boot.py:468`), and the
    `reply(_RECOVERY_REFUSED)` fall-through (`boot.py:503`) — all skip the
    sleep entirely. Feeding only in the idle branch would therefore leave a
    peer that streams malformed or refused packets spinning the full window
    with **zero** feeds: exactly F-12's reset, just triggered by a chatty peer
    instead of an idle one. The window's own docstring already anticipates
    this peer ("A refusal does not consume the window... so a chatty peer
    cannot pin a device in here"), so it is a real path, not a theoretical
    one. Top-of-body placement covers all five uniformly with a single call
    site.
  - `_run_default_update_loop` takes the same top-of-body placement, for the
    same reason and with the same single call site. Its idle path is `read()`
    → (on empty) `_sleep_ms(10)` → `continue`; its packet paths do their own
    `continue`/`break` without sleeping.
  - **Cost of feeding every iteration:** on an idle window that is ~100
    calls/second for up to ~9.57 s (F-18's measured wide-window span) — one
    Python call, no allocation, per `_call_heartbeat`'s `None`-check-then-call
    body. Not a plausible source of a multi-hundred-ms overrun; F-12's concern
    was the *absence* of feeding, not its cost.
  - **Net:** worst-case gap between feeds is one loop iteration — ~10 ms on
    the idle path, and on the packet paths whatever that packet's handling
    costs, which is bounded except for the `reply()` case below.
  - **Residual unfed span the library cannot close.** A single `reply()` in
    either loop is a URST reliable send: `MAX_RETRIES = 3` at
    `ACK_TIMEOUT_MS = 1000`, so answering a peer that stops acknowledging
    mid-window can block **~3-4 s inside `urst`** with no opportunity to feed,
    since the retry loop is `urst`'s, not OTAmpy's. That fits inside an
    8388 ms period on its own, but stacked on the ~1.5 s pre-window boot cost
    it leaves little margin, and OTAmpy cannot fix it without a `urst` change
    — which the parent TODO item explicitly wants to avoid ("I'd prefer not
    make any changes to the underlying URST package if possible"). Out of
    scope here; recorded in Risks so it is a known limit rather than a
    surprise.
- **Named constants:** no new numeric constant needed per the analysis above
  — the feed cadence rides the existing `_BOOT_LISTEN_POLL_MS` /
  hardcoded-`10`-ms idle sleeps rather than introducing a second, independent
  timing knob that could itself drift out of sync with them. (Naming the
  hardcoded `10` in `_run_default_update_loop`'s idle sleep as a constant, to
  match `_BOOT_LISTEN_POLL_MS`'s existing pattern, is a one-line DRY tidy-up
  folded into Build Step 2 rather than a separate step.)

## Build steps

- [x] **1. Move `_call_heartbeat` to `core.py`; feed it inside `_run_boot_listen`.**
  - What changes: `core.py` gains `_call_heartbeat(heartbeat)` (moved from
    `manager.py`, same body). `manager.py` drops its own definition and
    imports it from `.core`; its two call sites (`:169`, `:196`) are
    unchanged in behaviour. `boot.py`'s `_run_boot_listen` gains a
    `heartbeat=None` parameter and calls `_call_heartbeat(heartbeat)` as the
    **first statement inside the `while` body, before `read()`** — see Device
    cost for why the idle branch is the wrong place (four of the loop's five
    paths round skip the sleep entirely).
  - Test: `test_ota_manager.py`'s four existing `heartbeat`/`_call_heartbeat`
    tests (`test_manager_calls_heartbeat_once_per_fragment_during_a_large_cat`,
    `test_manager_calls_heartbeat_during_a_large_ls`,
    `test_manager_heartbeat_exceptions_do_not_abort_the_transfer`,
    `test_manager_heartbeat_is_optional`) must still pass unmodified — proves
    the move is behaviour-preserving. New tests in `test_ota_boot.py`:
    `test_boot_listen_calls_heartbeat_on_each_idle_tick` (a `FakeUART`/core
    with no incoming packets, `window_ms` short enough for the test to
    complete, asserts `heartbeat` call count roughly matches
    `window_ms / _BOOT_LISTEN_POLL_MS`);
    `test_boot_listen_feeds_heartbeat_while_refusing_a_chatty_peer` (queue a
    stream of packets the window refuses — a plain `PING` drawing
    `ERROR:Recovery window`, plus one non-UTF-8 packet — and assert
    `heartbeat` was still called on those iterations; **this is the test that
    would fail under the idle-branch placement** and is the reason the
    placement is specified);
    `test_boot_listen_heartbeat_exceptions_do_not_abort_the_window` (a
    `heartbeat` that raises; window still runs to completion and returns
    `False` as normal).
  - Done when: the three new tests pass, the four existing manager heartbeat
    tests still pass unmodified, and `grep -n "_call_heartbeat" src/otampy/device/lib/otampy/manager.py`
    shows the import plus the two call sites, with no `def _call_heartbeat`
    left in the file.

- [ ] **2. Feed inside `_run_default_update_loop`; thread `heartbeat` through `boot.run()` and `OTA.boot()`.**
  - What changes: `_run_default_update_loop` gains a `heartbeat=None`
    parameter, calls `_call_heartbeat(heartbeat)` once per loop iteration
    (idle-sleep branch and post-packet-handled branch both covered by placing
    the call at the top of the `while True:` body, before `read()`).
    `boot.run(core, callback=None, heartbeat=None)` passes it to both
    `_run_boot_listen(...)` and `_run_default_update_loop(core, heartbeat)`.
    `OTA.boot(self, callback=None, heartbeat=None)` passes it to `run(...)`.
    Fold in the one-line tidy-up naming `_run_default_update_loop`'s
    hardcoded idle-sleep `10` as a constant alongside `_BOOT_LISTEN_POLL_MS`,
    per the Device cost note above.
  - Test: `test_ota_boot.py` gains
    `test_default_update_loop_calls_heartbeat_while_idle` (loop with no
    incoming packets until timeout, asserts `heartbeat` was called) and
    `test_boot_passes_heartbeat_through_to_both_loops` (drives `run()` with a
    recording `heartbeat`, once through the recovery-window path and once
    through the update-flag path, asserting it reached both).
    `test_ota_facade.py` gains
    `test_ota_boot_accepts_and_forwards_heartbeat` (mocks `boot.run`, calls
    `OTA(...).boot(heartbeat=fn)`, asserts `run` was called with
    `heartbeat=fn`) and `test_ota_boot_heartbeat_defaults_to_none` (calls
    `.boot()` with no `heartbeat`, asserts `run` was called with
    `heartbeat=None` — proves the parameter is fully optional and backward
    compatible with every existing call site in `examples/`).
  - Done when: all four new tests pass, and the full existing
    `test_ota_boot.py` + `test_ota_facade.py` suites still pass unmodified —
    proving every current caller of `OTA(...).boot()` (`examples/boot.py`,
    `examples/shared-uart/boot.py`, `footprint_boot.py`, `README.md`,
    `docs/deployment.md`) keeps working with zero changes since `heartbeat`
    defaults to `None`.

- [ ] **3. Update the example, `configota.example.py` comment, and docs.**
  - What changes: `docs/protocol.md` §2.4 replaces "Nothing arms a watchdog
    this early... gives up pre-`boot()` RP2040 watchdog compatibility
    entirely" with a description of the `heartbeat` parameter and a note that
    `OTA_BOOT_RECOVERY_LISTEN_MS` above 8388 ms is now safe *if* a `heartbeat`
    is supplied (still worth a shorter window when none is, for the same
    reason as before — a watchdog-free device still can't recover from a
    truly wedged UART). `docs/architecture.md`'s matching paragraph gets the
    same correction. `configota.example.py`'s comment above
    `OTA_BOOT_RECOVERY_LISTEN_MS` is rewritten to point at the `heartbeat`
    parameter instead of asserting an untrue timing guarantee.
    `examples/boot.py` **and** `examples/shared-uart/boot.py` both get the
    same commented-out worked example
    (`# OTA(uart, config=config, logger=logger).boot(heartbeat=wdt.feed)`,
    with `mux.ota_port` in place of `uart` in the shared-uart variant)
    directly under each file's existing `OTA(...).boot()` call, matching each
    file's existing style of commented-out optional lines — `test_examples.py`
    already treats both scaffolds as a matched pair (`ALL_FILES`), so leaving
    one updated and the other stale would be the drift that test exists to
    catch on the next unrelated change. `CHANGELOG.md` gets an entry under
    the next unreleased heading.
  - Test: `tests/test_examples.py`'s existing `test_example_file_parses`
    parametrized test picks up `examples/boot.py` automatically — no new test
    needed, since the change is a comment addition, but confirm the test
    still passes (a bad comment could still break `ast.parse` if malformed).
  - Done when: `uv run pytest tests/test_examples.py` passes, and
    `grep -n "gives up.*entirely\|Nothing arms a watchdog this early" docs/protocol.md docs/architecture.md`
    returns nothing (the obsolete claim is fully replaced, not left
    alongside the new text).

## Verification

- **Host:** `python3 .agents/scripts/pre_flight_check.py`. In *this* repo that
  is the Python path only — `ruff check --fix`, `ruff format`, then
  `uv run pytest -q` — since there are no Node packages here. Note there is
  **no** `mpy-cross` device-syntax test in this repo (`pre_flight_check.py:152`
  says "pytest covers mpy-cross device syntax too, *where that test exists*",
  and it does not); device modules are only exercised as ordinary imports by
  `src/otampy/device/tests`, and the shipped scaffolds by
  `tests/test_examples.py`'s `ast.parse` check. So nothing here grammar-checks
  `boot.py`/`core.py`/`manager.py` against a real MicroPython parser — keep
  the edits to plain syntax already used elsewhere in those files. Run
  `uv run pytest src/otampy/device/tests/test_ota_boot.py src/otampy/device/tests/test_ota_manager.py src/otampy/device/tests/test_ota_facade.py tests/test_examples.py -v`
  after each step for faster feedback than the full suite.
- **Hardware:** none required. This step adds an optional callback with no
  effect unless a caller supplies one, so it cannot regress the boot-listen
  window behaviour already HIL-proven under sub-task 5 (F-10/F-15) — the two
  new `heartbeat`-recording tests are sufficient proof the call sites are
  reached; the timing itself (the wide window's actual duration) is
  unchanged and already has HIL evidence from that sub-task. No new
  `/sl-robot-check` line or telemetry field applies.
- **Manual:** Simon can wire a real `WDT(8388)` plus
  `heartbeat=wdt.feed` into a test `boot.py` on the bench rig and confirm the
  device survives a full wide-window boot without a WDT reset — this is
  optional confidence-building, not a gate, since it exercises hardware the
  library never touches directly (`machine.WDT` stays entirely
  integrator-owned).

## Risks and open questions

- **Sequencing with sub-task 5's outstanding HIL verification.** Fail-safe
  Updates sub-task 5 ("Land a `--recover` command in the boot-time recovery
  window") has an outstanding HIL step 7 against the *same* `_run_boot_listen`
  function this spec edits (`TODO.md`: "HIL verification outstanding — this
  sub-task's step 7, Opus only"). Recommend `/sl-build` on this spec waits
  until that HIL step closes, so a HIL failure there is not confused with a
  regression from this change, and so this change's diff against
  `_run_boot_listen` doesn't have to be rebased across whatever step 7 might
  still touch. Not a blocker on writing or reviewing this spec, only on
  building it.
- **A blocking `reply()` is still unfed, and this spec cannot fix it.** URST's
  reliable send retries `MAX_RETRIES = 3` times at `ACK_TIMEOUT_MS = 1000`, so
  one `reply()` to a peer that stops acknowledging blocks ~3-4 s inside
  `urst` with no feed possible from OTAmpy's side. Under an 8388 ms WDT that
  survives in isolation but not comfortably alongside the ~1.5 s pre-window
  boot cost. Closing it needs a heartbeat hook in `urst`'s retry loop, which
  the parent TODO item explicitly wants to avoid. Worth Simon's view on
  whether this should be filed as its own finding now rather than left as a
  spec footnote — it is a narrower version of exactly the F-12 dynamic.
- **`_run_default_update_loop`'s per-packet cost is unmeasured.** The
  "one call per loop iteration is enough" cadence claim in Device cost is
  reasoned from the loop's known idle-sleep granularity, not from a device
  measurement of the per-packet (hash + disk write) branch's own duration. If
  a future finding shows a single manifest-line write can itself exceed a
  fraction of a typical WDT period, this may need a second `_call_heartbeat`
  call inside the packet-handling branch — flagged here rather than guessed
  at now, since no evidence currently suggests it.
- **Whether to keep `OTA_BOOT_RECOVERY_LISTEN_MS`'s watchdog caveat at all
  once `heartbeat` exists.** Build Step 3 keeps a shortened caveat ("no
  `heartbeat` supplied still caps effective safety at the WDT period") rather
  than deleting the guidance outright, since a wedged UART with a
  `heartbeat` that itself never gets a chance to run (blocked host in
  `read()`, say) is not actually possible given `_run_boot_listen`'s
  non-blocking `read()` — worth Simon's confirmation the caveat's new wording
  is still the right level of caution rather than stale over-caution.

## Notes for the build

- `manager.py`'s `_call_heartbeat` and its three call-site comments
  (`manager.py:78-89`, `:119-123`, `:269`) are the existing pattern this spec
  extends verbatim — read them before writing `core.py`'s copy, don't
  reinvent the wording.
- `_run_boot_listen`'s docstring ("Never raises... A refusal does not consume
  the window: the deadline is absolute") must gain one line noting `heartbeat`
  is called once per loop iteration (every path round, not just the idle
  one) and is itself never allowed to raise out of
  the window — consistent with the rest of the docstring's "never raises"
  framing.
- Related findings: [F-12](../development/findings.md) (the finding this spec
  closes), [F-10](../development/findings.md) /
  [F-15](../development/findings.md) (the sub-task 5 HIL work sharing
  `_run_boot_listen` — see Risks above). Related dev logs:
  `failsafe-update-window-reachability-log.md` (F-12's original measurement),
  `failsafe-update-recovery-handshake-spec.md` (sub-task 5, still open).
