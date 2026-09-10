# Boot-time recovery window reachability (F-10) — spec

**TODO item:** **Fail-safe Updates** → sub-task 4 (**4. Boot-time recovery
listen window**) — its headline capability does not work in practice. Tracked
as **F-10** (P1, open) in `docs/development/findings.md`.
**Status:** approved
**Components:** `src/otampy/device/lib/otampy/` (device library), `src/otampy/`
(host CLI), `docs/`
**Dev log:** `docs/development/failsafe-update-window-reachability-log.md`
(created by `/sl-build`)

## Goal

A device stranded before `ota.poll()` — a fatal `main.py`, a hang in
application setup, a confirmed candidate that proved fatal — is recoverable
over the radio with **one operator power cycle** and no USB. Today the
boot-time recovery window opens at t+2.05 s and shuts at t+3.15 s, while a
power-cycled XBee delivers its first frame to the device UART somewhere
between t+3.6 s and t+8.7 s: the two never overlap, so recovery fails 100 % of
the time (0 hits in ~250 host attempts across five HIL runs). After this ships,
a boot that follows a boot which never reached the application opens a **wide**
window (default 8 s, open to t≈10.05 s) that spans the cold radio's wake-up,
while a healthy
device keeps paying only the existing ~1 s.

## In scope

- A **boot marker** on the device filesystem recording "this boot started",
  written by `boot.run()` and removed by the application's first `OTA.poll()`
  call. Its presence at boot means the *previous* boot never reached the
  application.
- `boot.run()` selecting the window duration from that marker **or** an
  unproven (`trial`/`committing`) journal: wide when either holds, the existing
  short window otherwise.
- New device settings `OTA_BOOT_RECOVERY_LISTEN_MS` (default `8000`) and
  `OTA_BOOT_MARK_FILE` (default `otampy-boot.mark`).
- Documentation of the new two-tier behaviour and its watchdog constraint in
  `docs/architecture.md`, `docs/protocol.md` §2.4 and `CHANGELOG.md`.
- HIL re-run of the sub-task 4 verification suite, and closing F-10.

## Out of scope

- **F-08 (freeze `restore.py` / a recovery `_boot.py`).** Separate `TODO.md`
  item. This spec adds no new module to the boot import chain, so it does not
  widen F-08's exposure — `boot.run()` already imports `restore` for
  `repair()`/`trial()`.
- **Host retry cadence.** Already fixed under F-10 (`_fast_recovery_handshake`,
  `_query(fast=True)`, `_RECOVERY_SERIAL_TIMEOUT`); measured at ~1.2 CONNECT/s.
  Necessary housekeeping, retained, not revisited here.
- **The lost-reply edge.** An in-window `ROLLBACK` that lands and resets the
  device but whose reply is lost makes the CLI report "Nothing to roll back"
  (exit 1) though the rollback succeeded. Pre-existing to the blind-retry
  design, recorded under F-10, unchanged here.
- **Any new wire command verb.** See the Protocol decision.
- **Making a *first* power cycle sufficient when the application crashed only
  after it had already polled.** That boot cleared the marker, so it costs one
  extra power cycle. Documented, not engineered around.

## Protocol decision

- **Existing OTAmpy/URST command reusable?** Yes — unchanged. The window still
  serves exactly `UPDATE_REQUEST` and `ROLLBACK` with the dispatch table
  sub-task 4 already shipped. Nothing about *what* is spoken changes; only
  *how long the device listens*.
- **Channel:** 0 (reliable). Unchanged.
- **Wire format change?** **None.** No new verb, no new response token,
  `PROTOCOL_VERSION` does not move. All changes are device-local plus doc text.
- **Signed off:** parent decision 2026-09-08 by Simon (no URST change, channel
  0 only). **This spec's replacement for D2 signed off 2026-09-10 by Simon:**
  Option C, *conditional wide window*.

### What this replaces

Signed-off **D2** ("silent window + host blind-retry") assumed the host could
race into a 1 s window. The HIL root-cause of 2026-09-10 falsifies the timing
premise, not the shape: blind retry is still correct, and the beacon is still
dead (an unacknowledged `Urst.send()` is stop-and-wait and costs up to ~8 s per
boot; an unreliable one needs URST's frame codec, which the parent sign-off
rules out). What changes is that **overlapping the cold radio's wake-up is the
only lever that matters** — and it is paid conditionally, so a healthy fleet
does not carry it.

Options considered and rejected: widening `OTA_BOOT_LISTEN_MS`
unconditionally (~9 s on every boot of every device, boot-loops included);
delay-then-listen (identical wall-clock, saves only `read()` calls);
reinstating the beacon (dead, above).

## Data and contracts

### The boot marker — **load-bearing**

| Property | Value |
| --- | --- |
| Path | `OTA_BOOT_MARK_FILE`, default `otampy-boot.mark`, resolved by `core._resolve_path` exactly as the journal is |
| Content | Irrelevant and never read. Written as a single byte `1`; only existence is meaningful |
| Written by | `boot.run()`, once per boot, **only when absent** |
| Removed by | `OTA.poll()`, on its first call in a process |
| Meaning at boot | Present → the previous boot never reached `OTA.poll()` |

**The off-switch lives in the path resolver, not at the call sites.**
`core._boot_mark_path(config)` returns `None` when
`OTA_BOOT_RECOVERY_LISTEN_MS <= 0`, so both `boot.py` and `ota.py` read
`path = _boot_mark_path(core.config)` / `if path:` and neither repeats the
guard. `0` therefore remains a true off-switch with zero filesystem cost, and
the feature has exactly one place that decides it is off.

**`core._boot_recovery_window_ms(config)` is the single parse of that key**
(amended 2026-09-10, signed off by Simon). It returns the parsed integer,
falling back to `_DEFAULT_BOOT_RECOVERY_LISTEN_MS` on a non-integer value.
`_boot_mark_path` returns `None` iff this returns `<= 0`; `boot.run()` calls it
for the duration in step 3. Without it the key is parsed in two places and the
two can disagree — which the pre-amendment draft already did, step 1 requiring
a non-integer to disable the marker while step 3 required it to mean the
default.

**A non-integer value is a typo, not an off-switch, and must fail open.**
`int("8000")` and `int(8000.5)` both succeed, so only genuine garbage (`None`,
`"8s"`, `""`) reaches the fall-back. Fail-closed there would let one typo
silently remove the only radio recovery path — F-10 reintroduced through a
config mistake. This matches the house rule already set by
`_run_boot_listen`'s `OTA_BOOT_LISTEN_MS` (garbage → default, `<= 0` → off),
`_run_default_update_loop`'s `OTA_TIMEOUT_MS` (garbage → default) and
`restore.read_journal` (an unparseable first line is "fail safe, meaning
restore everything"): **only an explicit, in-range sentinel turns something
off.**

Never raises: every access is wrapped, and a failed write or remove degrades to
the pre-existing short-window behaviour rather than stranding a boot.

**Where in `boot.run()`:** immediately after the `trial()` block and before the
`UPDATE_REQUEST_FLAG_FILE` lookup. After `trial()`, so a boot that exhausts the
trial limit and resets onto the previous generation does not leave a stale
marker behind; before the flag lookup, so the marker is written on the flagged
update path too.

**`ota.recover()` deliberately does not clear the marker.** It runs at the top
of `main.py`, before the application has proved anything; only reaching
`OTA.poll()` is evidence that the runtime OTA surface is alive.

**An update-session boot leaves the marker set** — it runs the update loop and
resets without ever polling. The boot that follows is wide regardless, because
its journal reports `trial`, so the two rules agree and there is no false
positive to engineer around.

### Window duration selection — **load-bearing**

Evaluated in `boot.run()` **after** `repair()` and `trial()` (so the tree is
healed and an exhausted trial has already reset), and only on the branch where
`UPDATE_REQUEST_FLAG_FILE` is absent:

| Condition at boot | Window |
| --- | --- |
| Marker present | `OTA_BOOT_RECOVERY_LISTEN_MS` (wide) |
| `restore.state(core)[0] != _LABEL_STABLE` (candidate on trial, or a stray `committing`) | `OTA_BOOT_RECOVERY_LISTEN_MS` (wide) |
| Neither | `OTA_BOOT_LISTEN_MS` (short, existing behaviour) |

Both conditions are needed and neither subsumes the other: the journal test
catches an unconfirmed candidate that strands the device on its very first
boot (free — the journal is already read), the marker catches a **confirmed**
generation that later proves fatal, which is precisely the
`otampy rollback --recover` case and the one a journal-only test would miss.

`_run_boot_listen(core, window_ms)` takes the resolved duration as an argument.
The existing parse-and-fall-back logic (non-integer → default, `<= 0` →
return `False`) moves to the caller and is applied to whichever key was
selected. The window's body — dispatch table, absolute deadline, auth
envelope, refusal semantics — is **unchanged**; it was already correct.

### Config keys

| Setting | Where | Default | Meaning |
| --- | --- | --- | --- |
| `OTA_BOOT_LISTEN_MS` | `configota.py` | `1000` | Unchanged. The window on a boot that follows a healthy application run. `0` disables it. |
| `OTA_BOOT_RECOVERY_LISTEN_MS` | `configota.py` | `8000` | The window on a boot that follows a boot which never reached `OTA.poll()`, or with a candidate still on trial. `0` disables the wide window *and* the marker entirely. |
| `OTA_BOOT_MARK_FILE` | `configota.py` | `otampy-boot.mark` | Marker path. |

Named constants, all in `core.py` so nothing is defined twice:
`_DEFAULT_BOOT_MARK_FILE = "otampy-boot.mark"` and
`_DEFAULT_BOOT_RECOVERY_LISTEN_MS = 8000`. `core._boot_recovery_window_ms(config)`
is the single parse of the key and `core._boot_mark_path(config)` the single
path resolver; `boot.py` imports both rather than redeclaring the constant or
repeating the parse, and `ota.py` imports the resolver.

This repo documents settings in `docs/architecture.md` (the `configota.py`
block at ~L126 and the prose at ~L134) and `docs/protocol.md` §2.4; there is no
`docs/configuration.md`. All three new rows land in both.

## Device cost

- **Hot-path allocation:** none added to `manager.poll`. `OTA.poll()` gains one
  boolean attribute check per call (`if not self._boot_mark_cleared:`) and does
  filesystem work exactly once per process.
- **Per-boot filesystem cost, healthy device:** one `open(..., "w")` of a
  1-byte file at boot, one `os.remove` at first poll. A stranded device in a
  boot loop does **zero** writes — the marker is already present and is left
  alone. LittleFS wear at this rate is negligible against a Pico's flash, but
  it is new and is stated here deliberately.
- **Wall-clock, healthy device:** unchanged at `OTA_BOOT_LISTEN_MS` (~1 s).
  This is the whole point of Option C.
- **Wall-clock, unproven or previously-stranded device:** `8 s` at the default.
  Paid on the first boot of every new candidate (until `CONFIRM`) and on every
  boot after a boot that never polled.
- **Watchdog.** `8000` sits **under the RP2040's ~8388 ms WDT cap** — chosen on
  that basis, so an integrator whose *custom* `boot.py` arms a watchdog
  **before** `OTA(...).boot()` can still use the default, provided their WDT
  period is at the cap. OTAmpy itself arms no watchdog this early. Anyone
  raising `OTA_BOOT_RECOVERY_LISTEN_MS` above 8388 gives up compatibility with
  a pre-`boot()` RP2040 watchdog entirely, since no WDT period can cover it.
  Must be spelled out in `docs/architecture.md` (which currently makes this
  claim only about `OTA_BOOT_LISTEN_MS`) and `docs/protocol.md` §2.4.
- **Margin over the measured radio wake-up.** The window opens at t≈2.05 s, so
  `8000` keeps it open to **t≈10.05 s** against a worst observed cold-radio
  first frame of **t+8.7 s** — ~1.35 s of headroom on five boots' evidence.
  That margin is the tightest number in this spec; see *Risks*.
- **Mux deployments:** the window reads `mux.ota_port` as it already does; a
  wide window simply holds that port for longer at boot. No mux or framing
  change.
- **Module weight:** no new module. `boot.run()`'s existing local
  `from .restore import ...` gains `state` and `_LABEL_STABLE`; `ota.py` gains
  no import it does not already make in `recover()`. Importing a private name
  across that boundary follows the existing precedent in the same statement
  (`_ROLLED_BACK`), so it is consistent rather than a new liberty.

## Build steps

Step order matters here: the marker is **written** (1), then **cleared** (2),
and only then does anything **read** it (3). Any other order leaves an
intermediate commit on which a healthy device pays the wide window on every
boot, because nothing removes the marker yet.

> ### 🛑 MODEL GATE — steps 1–4 Sonnet, step 5 Opus
>
> Steps 1–4 are mechanical execution against a pinned spec: **Sonnet is fine.**
>
> **Step 5 must not be started on Sonnet.** It is HIL evidence interpretation
> and the closure of a P1 finding. The precedent is on this branch: step 9 of
> `failsafe-update-boot-listen-spec.md` was ticked in error, having "repaired"
> F-10 against a premise that on-device instrumentation later falsified.
> Misreading hardware timing is the exact failure this spec exists to undo.
>
> **On finishing step 4: STOP. Tell Simon, loudly and unprompted, to `/clear`
> and switch to Opus (`/model opus`) before step 5 begins.** Do not begin
> step 5's HIL work in the same session, whatever the momentum.
>
> Same stop applies mid-build if a test goes red for a reason this spec did
> not anticipate — that is a broken premise, not a bug to improvise around.

- [x] **1. `core._boot_mark_path` + the marker written at boot**
  - What changes: `core.py` gains `_DEFAULT_BOOT_MARK_FILE`,
    `_DEFAULT_BOOT_RECOVERY_LISTEN_MS`, `_boot_recovery_window_ms(config)` (the
    single parse — non-integer falls back to the default) and
    `_boot_mark_path(config)` (returning `None` when that parse is `<= 0`).
    `boot.run()` reads the marker's
    existence into a local **before** writing it, and writes it only when
    absent, at the position pinned under *Data and contracts*. The local is not
    used yet. No window behaviour change.
  - Test: `src/otampy/device/tests/test_ota_core.py` (the parse — default when
    absent, override, and fall-back to the default on a non-integer; path
    resolution — default, override, and `None` when the recovery key is `0` or
    negative, but **not** when it is non-integer);
    `test_ota_boot.py` (written when absent; **not** rewritten when present;
    absent entirely when the recovery key is `0`; not written when `trial()`
    returns `_ROLLED_BACK`; an `OSError` on write does not propagate out of
    `run()`).
  - Done when: those tests pass and
    `python3 .agents/scripts/pre_flight_check.py` is clean.

- [x] **2. Clear the marker on the first `OTA.poll()`**
  - What changes: `OTA.__init__` sets `self._boot_mark_cleared = False`;
    `OTA.poll()` removes the marker on its first call and sets the flag
    regardless of outcome, then delegates to `manager.poll` unchanged. Never
    raises.
  - Test: `test_ota_facade.py` — first `poll()` removes the marker; the second
    does no filesystem work; an `OSError` on remove is swallowed and `poll()`
    still delegates; nothing happens when the recovery key is `0`. Follow
    `test_ota_facade.py`'s existing `sys.modules` save/restore pattern (see
    *Notes for the build*).
  - Done when: those tests pass and `pre_flight_check.py` is clean.

- [x] **3. Select the window duration**
  - What changes: `_run_boot_listen(core, window_ms)` takes the duration as an
    argument; the parse/fall-back/`<= 0` logic moves to `run()`, which picks
    wide vs short per the *Window duration selection* table. The wide duration
    comes from `core._boot_recovery_window_ms` (step 1), not a second parse.
  - Test: `test_ota_boot.py` — marker present → wide; journal `trial` with no
    marker → wide; `committing` → wide; neither → short (existing tests must
    still pass unchanged); wide key `0` → no window at all; non-integer wide
    key → default; short key `0` with marker present → still wide (the two keys
    are independent).
  - Done when: those tests pass, every pre-existing `_run_boot_listen` test
    still passes, and `pre_flight_check.py` is clean.

- [ ] **4. Documentation, CHANGELOG and CLI wording**
  - What changes: `docs/architecture.md` (the `configota.py` block and the
    recovery-window prose, including the corrected watchdog constraint),
    `docs/protocol.md` §2.4 (**When** / **Duration** now two-tier, plus the
    marker contract and the WDT note), `CHANGELOG.md`. In `src/otampy/cli.py`,
    the `--recover` operator prompt gains one clause: if the application had
    been running and only later crashed, a second power cycle may be needed.
  - Test: none for the docs. If any `tests/test_cli.py` assertion pins the
    prompt string, update it in the same diff.
  - Done when: `pre_flight_check.py` is clean and `docs/protocol.md` §2.4
    describes both durations, the marker, and the 8388 ms cap.

- [ ] **5. HIL verification and F-10 closure** — 🛑 **OPUS ONLY. Do not start
      this step on Sonnet.** If the running model is not Opus, stop and tell
      Simon to `/clear` and `/model opus` first. See the model gate above.
  - What changes: `docs/development/findings.md` — F-10 to **fixed (awaiting
    re-review)** with the measured figures; the dev log carries the raw runs.
  - Test: none (hardware evidence, see *Verification*).
  - Done when: HIL tests 1, 2, 3 and 4 below all pass, their figures are in the
    dev log, and F-10 records the fix.

## Verification

- **Host:** `python3 .agents/scripts/pre_flight_check.py` (ruff + full pytest,
  mirrors CI). Per-step:
  `uv run pytest src/otampy/device/tests/ tests/test_cli.py -q`.
- **Hardware** (Pico W, `otampy` deployed from the build branch — end of
  sub-task, not between steps). Tests 1 and 2 deliberately strand the device;
  keep USB access available before starting. **The two methodology traps
  recorded under F-10 apply and are not optional:** a `--recover` test against
  a *healthy* device proves nothing (the running `manager.poll` answers
  identically), and **every `mpremote` invocation soft-reboots the device on
  exit**, so batch all device interaction into one `mpremote ... + ...` session
  and touch USB not at all between a run's power cycles.
  1. **Recover a device stranded by a fatal `main.py`, on the first power
     cycle.** From a healthy build, `otampy upd --no-confirm main.py` with a
     `main.py` that raises on import and arms **no** watchdog. Evidence it is
     genuinely stranded: `otampy ping` times out. Then
     `otampy rollback --recover`, power-cycle **once** at the prompt.
     Evidence: `ROLLBACK_OK` within the first power cycle, `otampy ping` →
     `PONG`, `otampy cat /main.py` is the previous good version, `otampy ls /`
     shows no `main.py.bck`, no `otampy-update.journal`.
     **Run this three times, re-stranding the device each time.** At `8000` the
     window closes ~1.35 s after the worst observed radio wake-up; one pass
     cannot tell real margin from a lucky boot. Three first-cycle passes is the
     bar. Record the per-attempt outcome in the dev log — if any attempt needs
     a second power cycle, that is the margin talking, and it belongs in F-10
     before the finding is closed.
  2. **Update a stranded device.** Strand it again, then
     `otampy upd --recover main.py` with a good `main.py`. Evidence:
     `Device is READY. Handshake complete.`, then `COMMIT_OK`, then
     `Candidate confirmed.`; `otampy ping` → `PONG`. One power cycle.
  3. **Boot-delay cost on a healthy device is unchanged.** Time power-on →
     first `PONG` on a **confirmed, healthy** device (marker cleared by the
     last run's poll) with `OTA_BOOT_RECOVERY_LISTEN_MS = 8000`, three runs,
     power-cycling fully between them. Evidence: within ~0.3 s of the same
     measurement taken with the recovery key at `0` — i.e. the wide window is
     **not** being paid. Record all six figures in the dev log. This is the
     test that proves Option C actually bought what it was chosen for.
     **Both halves of the A/B are measured in the same session, after a full
     power cycle each** — never against figures carried over from an earlier
     run. F-10's entire first diagnosis came from trusting a timing comparison
     across sessions.
  4. **The marker survives and selects correctly.** On the stranded device
     from test 1, before recovering it: one batched `mpremote` session shows
     `otampy-boot.mark` **present**. After a successful recovery and a normal
     boot into a polling application, one batched session shows it **absent**.
  - Tests 4, 5 and 6 of `failsafe-update-boot-listen-spec.md` (window not
    permanently open; not an auth bypass; refusal does not consume the window)
    are re-run unchanged — the window body is untouched, so these are
    regression checks, not new evidence. Test 5 in particular must be re-run
    against a **wide** window: an 8 s auth-enforcing window is a longer
    exposure than a 1 s one, even though the envelope logic is identical.
  - **Rig note:** `log_to_file` is not installed on the HIL device, so
    `core.logger` is a `NullLogger` and every `logger.*` call inside the window
    goes nowhere. Install it before relying on device logs for any of the
    above, or instrument with prints as the 2026-09-10 root-cause run did.
- **Manual:** Simon runs tests 1 and 3 and confirms by eye that a device he has
  deliberately bricked at the application level comes back over the radio on
  **one** power cycle with no USB — and that a healthy device's boot is no
  slower than it was before this change.

## Risks and open questions

- **`8000` buys ~1.35 s of margin, and that is the tightest figure here.**
  Chosen by Simon (2026-09-10) to stay under the RP2040's ~8388 ms WDT cap, so
  the default remains usable by an integrator arming a watchdog before
  `OTA(...).boot()`. The cost is that the window closes at t≈10.05 s against a
  worst observed cold-radio first frame of t+8.7 s. **HIL test 1 must pass on
  the first power cycle across at least three separate attempts** — a single
  pass does not distinguish 1.35 s of real margin from a lucky boot. If it
  proves marginal in practice, the lever is `OTA_BOOT_RECOVERY_LISTEN_MS`, and
  raising it past 8388 is a deliberate trade of pre-`boot()` WDT compatibility
  for recovery reliability, not a silent tweak.
- **Radio wake-up was characterised on one XBee rig.** t+3.6–8.7 s is five
  boots' worth of evidence, not a datasheet figure. A slower module, or a
  different radio, could exceed even 8 s — which is why the key is tunable and
  the failure mode is "power-cycle again", not "brick".
- **An application that never calls `OTA.poll()`** never clears the marker and
  therefore pays the wide window on every boot. Such a device has no runtime
  OTA surface at all, so a wide boot window is arguably the correct answer for
  it, but it is a behaviour change for that integrator. Documented in
  `docs/architecture.md`; `OTA_BOOT_RECOVERY_LISTEN_MS = 0` opts out.
- **An application that crashes only after it has already polled** costs two
  power cycles rather than one (the crashing boot clears the marker, the next
  sets it, the one after gets the wide window). Accepted; called out in the
  CLI prompt (step 4).
- **`OTA.poll()` is the clearing point, not `manager.poll`.** An integrator
  calling `manager.poll` directly bypasses the clear. The facade is the
  documented entry point and every shipped example uses it; noted rather than
  guarded, to keep the hot path free of a per-call check in `manager`.
- **A full or read-only filesystem silently disables the escalation.** If the
  marker write fails, the device degrades to the short window — i.e. to today's
  broken behaviour — with no host-visible signal. Deliberate (a boot must never
  be stranded by a failed marker write), but it means "recovery worked in
  testing" does not prove "recovery works on a device whose flash has since
  filled up".
- **F-08 is untouched and still open (P2).** A power loss while `restore.py`
  itself is the current commit pair still strands the device, and this window —
  wide or not — cannot help, because `boot.run()`'s `from .restore import ...`
  raises first.

## Notes for the build

- **Read the marker before writing it.** The whole mechanism inverts if
  `run()` writes first and tests afterwards.
- **`_run_boot_listen`'s body is correct and stays correct.** F-10's retired
  lead — "the window may execute only one or two `read()` calls and miss a
  mid-window CONNECT" — is **false**: `read()` blocks for the device's
  `ACK_TIMEOUT_MS` (1000 ms), so one call is a continuous full-window listen.
  Do not "fix" the poll loop.
- **`test_ota_facade.py` leaks `sys.modules` state** (its own `TODO.md` item):
  `test_boot_releases_boot_module_and_can_run_again` deletes
  `device_otampy.boot` and never restores it. Step 3 adds tests to that same
  file — follow
  `test_boot_teardown_survives_micropython_delattr_keyerror`'s local
  save/restore pattern, and do **not** fold the general fixture fix into this
  spec; it is tracked separately.
- **MicroPython is not CPython.** F-09 was `delattr` raising `KeyError` instead
  of `AttributeError` and it stranded every no-auth device on the branch while
  host tests stayed green. Any new `except` clause added by these steps gets
  the same scrutiny.
- Related findings: **F-10** (this spec's reason for existing), **F-08**
  (out of scope, still open), **F-09**, **F-06**, **F-04**.
- Related specs/logs: `failsafe-update-boot-listen-spec.md` (sub-task 4, whose
  D2 this replaces) and its log, `f10-window-evidence.md`.
