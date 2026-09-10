# Recovery-window handshake, host side (F-15) — spec

**TODO item:** Fail-safe Updates → sub-task 5, "Land a `--recover` command in
the boot-time recovery window"
**Status:** approved
**Components:** `src/otampy/cli.py`, `tests/test_cli.py`,
`src/otampy/device/lib/otampy/boot.py` (F-14 only), `docs/`
**Dev log:** `docs/development/failsafe-update-recovery-handshake-log.md`
(created by `/sl-build`)

## Goal

`otampy rollback --recover` and `otampy upd --recover` reliably land their
command inside the device's boot-time recovery window, so an operator can
recover a device stranded before `main.py` over the radio, on one power cycle,
with no USB — repeatably, not once in three. The device half of this is already
built and measured (a ~9 s window opens on every stranded boot, F-10 step 3);
what changes is entirely how the host drives the serial port while it waits.

## In scope

- **F-15 (P1).** Replace `_recover_query`'s fail-fast poll — one CONNECT per
  cycle, `ACK_TIMEOUT_MS` 500, `MAX_RETRIES` 0, serial timeout 0.1 s, port
  reopened every cycle — with a poll that opens the port **once** and retries
  `protocol.connect()` on that single transport at stock URST timings.
- Removal of `_fast_recovery_handshake()`, `_RECOVERY_ACK_TIMEOUT_MS`,
  `_RECOVERY_MAX_RETRIES` and the `fast=` parameter on `_query`, which exist
  only to serve that poll.
- **F-13 (P2).** The `--recover` timeout tests that pass on a config-validation
  error and never reach the path they name.
- **F-14 (P3).** A trial boot with `OTA_BOOT_RECOVERY_LISTEN_MS = 0` currently
  gets *no* listen window at all; it should fall back to `OTA_BOOT_LISTEN_MS`.
- The operator-facing prompt and timeout text on the `--recover` path.
- `docs/protocol.md` §2.4 and `docs/architecture.md` where they describe the
  window and its host-side counterpart; `CHANGELOG.md`.
- Re-running the outstanding HIL tests of
  `failsafe-update-window-reachability-spec.md` (step 5), which is what closes
  F-10.

## Out of scope

- **The device-side window itself.** `_run_boot_listen`'s body, the dispatch
  table, the auth envelope and the two-tier duration selection are proven
  correct on hardware and are not touched, except for F-14's one branch.
- **F-12 (P2, the 8952 ms window vs the 8388 ms WDT cap).** Real, measured
  twice, and orthogonal — it is about the *device's* window duration against a
  watchdog an integrator may arm, not about the host reaching it. Left open.
- **F-08 (P2, a power loss while `restore.py` is the commit pair).** Its own
  TODO item; no window, wide or narrow, can help it.
- **Making `OTA_BOOT_RECOVERY_LISTEN_MS` larger.** If this spec's host fix
  still proves marginal on HIL, the device-side lever is the *next* decision,
  not a silent tweak inside this one.
- **A device-side beacon.** Rejected for the third time — see *Protocol
  decision*.

## Protocol decision

- **Existing OTAmpy/URST command reusable?** Yes, unchanged. The window still
  serves exactly `UPDATE_REQUEST` and `ROLLBACK`. Nothing about *what* is
  spoken changes; only how the host works the serial port while it waits for a
  window to open.
- **Channel:** 0 (reliable). Unchanged.
- **Wire format change?** **None.** No new verb, no new response token,
  `PROTOCOL_VERSION` does not move. Every change is host-side, plus one
  device-side branch for F-14 and doc text.
- **URST change?** **None.** In particular this spec *stops* mutating
  `urst.constants` at runtime, which is a reduction in coupling, not an
  increase.
- **Signed off:** parent decision 2026-09-08 by Simon (no URST change, channel
  0 only). **This spec's shape — Option B, hold the port open — signed off
  2026-09-10 by Simon.**

### What this replaces

`failsafe-update-window-reachability-spec.md` replaced signed-off **D2**
("silent window + host blind-retry") only on its *device* half: the window is
now wide enough to overlap a cold XBee's wake-up, which HIL proved
(9006 / 9017 / 8977 ms on three consecutive stranded boots). Blind retry
survives as the host's strategy; what is falsified is the **profile** the
retry uses. Fail-fast was chosen when the target was a 1 s window and cadence
was believed to be the constraint. With a ~9 s window, cadence is cheap and
per-attempt robustness is what matters — the opposite trade.

Rejected again, for the record:

- **A device-side beacon.** An unacknowledged `Urst.send()` is stop-and-wait
  and costs up to ~8 s per boot; an unreliable one needs URST's frame codec,
  which the parent sign-off excludes. Unchanged since 2026-09-08.
- **Retuning the fail-fast constants in place (Option A).** It leaves the
  port being reopened ~1.2 times a second, toggling DTR/RTS on the FTDI→XBee
  at exactly the moment a freshly-booted device needs the link quietest. That
  churn is a live hypothesis for the 0-hit result and Option A bets against it
  without testing it.

## Data and contracts

### The recovery poll — **load-bearing**

The contract `_recover_query` owes its callers is unchanged and must stay
unchanged: given a command and an expected prefix, return the reply payload,
raise `DeviceError` if the device *answered* with a refusal, and raise
`click.ClickException` naming `recovery-wait` if nothing answered in time.
`rollback --recover` and `upd --recover` both depend on exactly that shape.

What changes is the body:

| | Today (F-15) | This spec |
| --- | --- | --- |
| Serial port | reopened every cycle (~1.2/s), DTR/RTS toggled each time | opened **once**, held for the whole poll |
| Handshake | `_query(fast=True)` → one CONNECT, `ACK_TIMEOUT_MS` 500, `MAX_RETRIES` 0 | `transport.protocol.connect()` at stock URST timings — 4 CONNECT frames, 1 s listen after each |
| `urst.constants` | mutated and restored around the poll | **not touched** |
| Serial read timeout | `0.1 s` | `_RECOVERY_SERIAL_TIMEOUT` (below) |
| CONNECT cadence | ~1.2/s, 500 ms listen each | ~1/s, a full 1 s listen each |
| Command sent | every cycle, blind | only after a handshake has actually completed |

### Why the serial read timeout is load-bearing, not a taste knob

`urst/codec_layer.py:226-266` — `read_frame(timeout_ms)` loops
`ser.read(max(1, in_waiting))`, and against a silent port `in_waiting` is 0, so
each iteration blocks for the **pyserial** timeout. If the pyserial timeout
exceeds `ACK_TIMEOUT_MS`, the ACK deadline is unenforceable: with the default
`serial_timeout_seconds = 2.0` a nominal 1000 ms handshake attempt actually
takes ~2 s, and `connect()`'s four attempts take ~8 s — one CONNECT every 2 s,
with the loop unable to react in under 8. The recovery poll therefore **must**
pass an explicit serial timeout, and the invariant is:

> `_RECOVERY_SERIAL_TIMEOUT <= urst.constants.ACK_TIMEOUT_MS / 1000`

This is asserted by a test, not just written down, because a later change to
either number silently un-does the fix.

### Named constants

All in `src/otampy/cli.py`, next to the poll they serve:

| Constant | Value | Why |
| --- | --- | --- |
| `_RECOVERY_SERIAL_TIMEOUT` | `0.2` | Bounds one `read_frame` iteration so `ACK_TIMEOUT_MS` is the real per-attempt deadline (above). Already exists at `0.1`; the value moves and the docstring changes. |
| `_RECOVERY_HANDSHAKE_GAP_S` | `0.05` | Quiet gap between `connect()` calls. XBees drop or buffer back-to-back frames without a ~30 ms gap (Simon, recorded under F-10). New. |

Deleted: `_RECOVERY_ACK_TIMEOUT_MS`, `_RECOVERY_MAX_RETRIES`.

No new user-facing config key. `recovery_wait_seconds` (`recovery-wait`,
default 60) still bounds the whole poll and remains the operator's lever.

### F-14: window selection when the wide window is disabled

`boot.py` `run()`, the `if not has_flag:` branch:

| Condition at boot | Today | This spec |
| --- | --- | --- |
| Marker present or journal `!= stable`, `OTA_BOOT_RECOVERY_LISTEN_MS > 0` | wide | wide (unchanged) |
| Marker present or journal `!= stable`, key is `0` | **no window at all** | `OTA_BOOT_LISTEN_MS` (short) |
| Neither | short | short (unchanged) |

The invariant this restores, and which belongs in `docs/protocol.md` §2.4:
**a boot that is more at risk never gets a shorter window than an ordinary
boot.** `0` disables the *wide* window and the marker; it was never documented
as removing the short window from the one boot most likely to need it.

## Device cost

- **Hot-path allocation:** none. `manager.poll` and `OTA.poll()` are untouched.
- **Per-boot cost:** F-14 adds one `_config_int` read of `OTA_BOOT_LISTEN_MS`
  on a branch that is only taken when the wide window is disabled *and* the
  boot is at-risk. Zero cost on the default configuration.
- **Blocking operations:** none added on the device. The window's duration is
  unchanged by this spec (F-12 owns that question).
- **Watchdog:** unchanged. F-14's fallback makes an at-risk boot's window
  *shorter or equal* to what a wide-window device already pays, so it cannot
  worsen any WDT margin.
- **Everything else here is host-side** and costs the device nothing.

## Build steps

- [ ] **1. Extract the reply-interpretation and outgoing-bytes helpers**
  - What changes: `src/otampy/cli.py`. `_query` interprets a reply in two
    near-identical blocks (the transport-provided branch at ~`cli.py:1120` and
    the new-transport branch at ~`cli.py:1180`) — `ERROR:` → `DeviceError`,
    prefix check, optional-colon payload strip. Extract
    `_interpret_reply(response, command, expected_prefix) -> bytes` and use it
    from both. Extract the per-attempt `outgoing()` closure into
    `_outgoing_bytes(command, signer)` so the recovery poll in step 3 can reuse
    it without copying the fresh-counter rule. Pure refactor: no behaviour
    change, no signature change on `_query`.
  - Test: `tests/test_cli.py` — direct tests for `_interpret_reply` covering
    the `ERROR:` path, the exact-prefix path, the `PREFIX:payload` colon strip
    and the `PREFIXpayload` no-colon strip; plus a mismatched prefix raising
    `ClickException`. The existing `_query` suite is the regression net.
  - Done when: `uv run pytest tests/test_cli.py -q` is green with no test
    changed other than additions, and `ERROR:`/prefix handling appears once in
    `cli.py` rather than twice (AGENTS.md DRY —
    `grep -c 'startswith(b"ERROR:")' src/otampy/cli.py` goes from `2` to `1`).

- [ ] **2. Fix the `--recover` timeout tests before touching the code (F-13)**
  - What changes: `tests/test_cli.py` only. Three tests set
    `OTAMPY_RECOVERY_WAIT=0`, which `_coerce_config_value` (`cli.py:369-372`)
    rejects outright — they assert on an error message that is the *validation*
    failure, not the recovery timeout, and never enter the retry loop:
    `test_rollback_recover_times_out_with_recovery_wait_message`,
    `test_recover_query_raises_naming_recovery_wait_when_nothing_answers`, and
    `test_recover_query_restores_handshake_timing_even_on_timeout` (which step 3
    deletes). Use a tiny positive wait (`0.001`, the pattern the F-11 tests
    already use) and assert on the real wording — `No recovery window answered`
    and the command name — not the bare key.
  - Test: this step *is* the test change.
  - Done when: each fixed test fails when `_recover_query`'s timeout message is
    altered, and passes otherwise. Demonstrate it: temporarily change the
    message, show the reds, revert. Record both outputs in the dev log — that
    is the evidence F-13 was actually a false pass and is now not.

- [ ] **3. Hold the port open and retry the handshake (F-15) — the fix**
  - What changes: `src/otampy/cli.py`. Rewrite `_recover_query`:
    - Open once with `_open_transport(ctx, serial_timeout=_RECOVERY_SERIAL_TIMEOUT)`,
      close it in a `finally`.
    - Loop until `recovery_wait_seconds` expires: call
      `transport.protocol.connect()`; on `False`, sleep
      `_RECOVERY_HANDSHAKE_GAP_S` and retry.
    - On `True`, send `_outgoing_bytes(...)` (fresh signer counter per send)
      and read with `_read_full_reply`, then `_interpret_reply`.
    - **A connect that lands as the window shuts is a miss, not a failure:** if
      the send or the read comes back empty, clear `protocol.is_connected`,
      drain `protocol._recv_queue`, and continue the loop rather than raising.
    - **A port that dies mid-poll is recovered, not fatal:** on `OSError` /
      `serial.SerialException`, close and reopen the transport and continue.
      Two `OSError: [Errno 5]` events occurred on the HIL host during the
      2026-09-10 run; the old reopen-per-cycle design absorbed that implicitly
      and the held-open design must do it explicitly.
    - `DeviceError` still propagates immediately — the device answered.
    - Delete `_fast_recovery_handshake`, `_RECOVERY_ACK_TIMEOUT_MS`,
      `_RECOVERY_MAX_RETRIES`, the `fast=` parameter on `_query` and the
      `fast_serial_timeout` plumbing, and the two tests that assert on the fast
      profile.
  - Test: `tests/test_cli.py` —
    (a) the port is opened **once** across many failed handshakes;
    (b) `_open_transport` is called with `serial_timeout=_RECOVERY_SERIAL_TIMEOUT`;
    (c) `_RECOVERY_SERIAL_TIMEOUT <= urst.constants.ACK_TIMEOUT_MS / 1000`
        (the invariant, asserted directly);
    (d) `urst.constants.ACK_TIMEOUT_MS` / `MAX_RETRIES` are the same objects
        before and during the poll — nothing is mutated;
    (e) a `connect()` that succeeds but whose reply never arrives loops again
        and succeeds on a later attempt, and the second send re-wraps with a
        fresh auth counter;
    (f) an `OSError` mid-poll reopens the transport and the poll continues;
    (g) `DeviceError` propagates; (h) the timeout raises the `recovery-wait`
        message from step 2.
  - Done when: all of the above pass, `grep -c fast= src/otampy/cli.py` is 0,
    and `python3 .agents/scripts/pre_flight_check.py` is green.

- [ ] **4. Re-word the operator prompt and the timeout message**
  - What changes: `src/otampy/cli.py` `_recover_query`'s two messages. The
    prompt still says the host "blind-retries several times a second", which
    stops being true. It should say: power-cycle now; the host is handshaking
    once a second for `<wait>`s; a device that failed before reaching its
    application opens a wide window on the next boot, so one power cycle is
    normally enough; a device that crashed *after* polling needs two. The
    timeout message keeps naming `recovery-wait` and the `otampy config --set`
    lever.
  - Test: `tests/test_cli.py` — assert the prompt no longer claims a
    sub-second retry rate and still tells the operator to power-cycle; the
    timeout assertions from step 2 stand unchanged.
  - Done when: `otampy rollback --recover` against a dead port prints a prompt
    that matches what the code now does, and the step-2 tests still pass.

- [ ] **5. F-14: an at-risk boot never gets less than an ordinary boot**
  - What changes: `src/otampy/device/lib/otampy/boot.py` `run()` — the
    `if had_boot_mark or state(core)[0] != _LABEL_STABLE:` branch falls back to
    `OTA_BOOT_LISTEN_MS` when `_boot_recovery_window_ms(core.config)` is not
    `> 0`. Plus the doc text that currently promises less:
    `src/otampy/device/examples/configota.example.py`,
    `docs/architecture.md`, `docs/protocol.md` §2.4.
  - Test: `src/otampy/device/tests/` (the `test_ota_boot.py` window-selection
    tests) — with the recovery key at `0` and the journal reporting `trial`,
    `_run_boot_listen` is called with the short window, not `0`; with the key
    at its default the wide window is still selected; a healthy stable boot is
    unchanged. (This repo has no separate device grammar-check test — the
    device suite imports the modules directly, so a syntax error fails
    collection.)
  - Done when: the three selection tests pass, and the docs state the invariant
    ("`0` disables the wide window and the marker; an at-risk boot then falls
    back to `OTA_BOOT_LISTEN_MS`, never to no window").

- [ ] **6. Docs and changelog for the host-side recovery path**
  - What changes: `docs/protocol.md` §2.4 gains a short "how the host reaches
    the window" note — one held-open port, ~1 CONNECT/s at stock URST timings,
    bounded by `recovery-wait` — and the `_RECOVERY_SERIAL_TIMEOUT` invariant
    is recorded where a future editor of `serial_timeout_seconds` will see it.
    §2.4 also states the exclusivity contract decided 2026-09-10: **`--recover`
    takes exclusive use of the port for its duration** (up to `recovery-wait`),
    so in a mux deployment the gateway must not be contending for
    `mux.ota_port` while it runs. `docs/architecture.md` where it describes
    `--recover`. `CHANGELOG.md`.
  - Test: none — documentation.
  - Done when: §2.4 describes the poll accurately enough that F-15's failure
    mode could not be reintroduced by someone following the doc.

- [ ] **7. HIL verification and finding closure**
  - What changes: no code. Re-runs the outstanding hardware tests of
    `failsafe-update-window-reachability-spec.md` step 5 — see *Verification*.
  - Test: none — hardware evidence, recorded in this spec's dev log **and**
    appended to the window-reachability log so F-10's trail stays in one place.
  - Done when: HIL 1 passes on the first power cycle **three times running**,
    HIL 2 passes, HIL 4's first half is evidenced; then F-15 and F-10 move to
    `fixed` and are re-reviewed for closure via `/sl-findings`, and F-13/F-14
    close on their steps' tests.

## Verification

- **Host:** `python3 .agents/scripts/pre_flight_check.py` (ruff + full pytest,
  mirrors CI). Per-step:
  `uv run pytest tests/test_cli.py src/otampy/device/tests/ -q`.
- **Hardware** (Pico W, `otampy` deployed from the build branch, at the end of
  step 6 — not between steps). The two methodology traps recorded under F-10
  are mandatory, not advisory:
  - a `--recover` test against a **healthy** device proves nothing, because the
    running `manager.poll` answers `ROLLBACK` identically. The device must be
    genuinely stranded;
  - **every `mpremote` invocation soft-reboots the device on exit.** Read
    `/ota.log` over the radio with `otampy cat` instead. Where USB is
    unavoidable, batch it into one `mpremote ... + ...` session and follow it
    with a genuine `mpremote connect <port> reset` and a full settle before
    trusting the device again.

  1. **HIL 1 — recover a device stranded by a fatal `main.py`, on the first
     power cycle, three times running.** Strand with
     `otampy upd --no-confirm main.py` where `main.py` raises on import and
     arms no watchdog; confirm stranded with `otampy ping` timing out. Then
     `otampy rollback --recover` and **one** power cycle at the prompt.
     Evidence per attempt: `ROLLBACK_OK`, `otampy ping` → `PONG`,
     `otampy cat /main.py` is the previous good version, `otampy ls /` shows
     no `main.py.bck`, no `otampy-update.journal`, no `otampy-boot.mark`.
     **Three first-cycle passes is the bar** — attempt 1 of the 2026-09-10 run
     passed and attempt 2 failed twice, so one pass proves nothing. Record
     every attempt's outcome, including the failures, in the dev log.
     Watch the trial-boot budget: attempt 2 of the last run consumed it and
     the device was rescued by auto-restore, ending the session. Re-strand
     deliberately between attempts rather than letting the counter run out.
  2. **HIL 2 — update a stranded device.** Strand again, then
     `otampy upd --recover main.py` with a good `main.py`. Evidence:
     `Device is READY. Handshake complete.`, `COMMIT_OK`,
     `Candidate confirmed.`, `otampy ping` → `PONG`. One power cycle.
     Not attempted on 2026-09-10 because it exercises the same defect.
  3. **HIL 4, first half — the marker is present while stranded.** Read over
     the radio if `--recover` now works well enough to get a command in;
     otherwise one batched `mpremote` session, accepting that USB tells the
     truth here because a stranded device is not polling.
  4. **Regression: the healthy-boot cost is still not paid.** HIL 3 already
     passed (mean 4171 ms with the wide window configured vs 4192 ms with it
     disabled, nine boots). Nothing in this spec touches that path, so re-run
     **one** pair of cycles as a sanity check only, not the full A/B.
  5. **Regression: tests 4, 5 and 6 of `failsafe-update-boot-listen-spec.md`**
     (window not permanently open; not an auth bypass; refusal does not consume
     the window) re-run unchanged. Test 5 matters most: a held-open host poll
     hammering an auth-enforcing window for up to 60 s is a longer exposure
     than anything tested so far.
  - **Rig note:** `log_to_file` is not installed on the HIL device, so
    `core.logger` is a `NullLogger` and `logger.*` calls inside the window go
    nowhere. Install it, or instrument with prints, before relying on device
    logs. `LOG_LEVEL = "DEBUG"` + `LOG_USE_TICKS = True` pushed over the radio
    is how the 2026-09-10 measurements were taken.
- **Manual:** Simon runs HIL 1 three times and confirms by eye that a device he
  has deliberately bricked at the application level comes back over the radio
  on **one** power cycle, with no USB, every time.

## Risks and open questions

- **Holding the port open for up to 60 s is a real behaviour change under
  mux.** Today the poll releases the port between cycles; after this it does
  not. In a mux deployment the gateway owns that port, and a `--recover` run
  now holds `mux.ota_port` continuously for the whole `recovery-wait`.
  **Decided 2026-09-10 by Simon: accepted, and the poll does not yield.**
  Recovery is an exclusive operation — getting the device back to solid,
  working firmware outranks anything else sharing that port, and the
  2026-09-10 HIL run turned the gateway off for exactly this reason. Step 6
  documents it as a contract in `docs/protocol.md` §2.4: **`--recover` takes
  exclusive use of the port for its duration.** No longer an open question;
  kept here as the rationale a `diff-drive-robot` operator will want.
- **The port-churn hypothesis is a hypothesis.** The evidence for it is
  circumstantial: an accidental normal-profile `PING` landed in a window, the
  fail-fast profile landed 0 in ~18 s of open window, and Simon's XBee note
  about back-to-back frames. If HIL 1 still fails after this, the next
  suspects in order are (a) `connect()`'s `discard_buffered()` throwing away a
  late `CONNECT_ACK`, (b) the device's own `read()` inside the window
  interacting badly with a 1 s host cadence, (c) the window duration itself
  (F-12's lever). Record which, if any, is reached.
- **~1 CONNECT/s over a ~9 s window is ~9 attempts.** That is comfortable but
  not enormous, and it assumes the window and the radio's wake-up overlap as
  measured (t+1.5→10.5 s window vs t+3.6–8.7 s first frame). A slower radio
  narrows it. The failure mode stays "power-cycle again", not "brick".
- **Step 1 is a refactor of a path with a P1 open against it.** It lands first
  deliberately — it is behaviour-preserving and it removes the duplication
  step 3 would otherwise copy — but if the existing `_query` tests are thinner
  than they look, a refactor bug would be attributed to step 3. Read the
  existing `_query` coverage before starting, and say in the log whether it
  was sufficient.
- **F-12 remains open and is arguably the more dangerous finding** for anyone
  arming a watchdog before `OTA(...).boot()`. Nothing here changes it; it must
  not be forgotten because F-10 closed.

## Notes for the build

- **`_recover_query` is called by two commands with different follow-on
  behaviour.** `rollback --recover` expects `ROLLBACK_` and the device resets
  immediately; `upd --recover` expects `REBOOTING` and then runs a *fresh*
  update session on a newly-opened transport (`cli.py:2494`). The held-open
  transport therefore never needs to be handed onward — close it and let the
  existing session code reopen. Do not "optimise" that.
- **The fresh-counter rule is load-bearing, not a style choice.** `_query`'s
  `outgoing()` is deliberately called per attempt: a first attempt that reached
  the device but lost its reply would make every retry look like a replay if
  the wrapped bytes were hoisted. The recovery loop inherits that rule exactly
  — wrap at each send, never once before the loop.
- **`send_reliable` auto-connects** (`urst/protocol_layer.py:239`), so an
  explicit `connect()` is a *probe*, not a prerequisite. Probing explicitly is
  the point: it is how the loop learns a window is open without spending an
  auth counter or putting a command on the wire.
- **`connect()` already retries 4× internally** with a full `ACK_TIMEOUT_MS`
  listen after each CONNECT frame (`protocol_layer.py:175-226`), which is why
  the outer loop does not need its own inner retry count. One `connect()` call
  is ~4 s of continuous, correctly-spaced attempts.
- **Do not reintroduce `urst.constants` mutation.** It was a workaround for a
  1 s window and it made every attempt too fragile to finish a handshake. The
  irony is worth keeping in mind: F-15 *is* F-10's own earlier repair
  (commit `172d93c`).
- Related: **F-15**, **F-14**, **F-13**, **F-10** in
  `docs/development/findings.md`; dev logs
  `docs/development/failsafe-update-window-reachability-log.md` (the 2026-09-10
  step 5 runs, where all of the measurements above come from) and
  `docs/development/failsafe-update-boot-listen-log.md`.

## TODO.md

Written 2026-09-10, approved by Simon: sub-task 5 under **Fail-safe Updates**,
after sub-task 4. Sub-task 4's "HIL verification outstanding" line moved onto
it, since step 7 here is that verification.
