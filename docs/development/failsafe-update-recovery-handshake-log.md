# Recovery-window handshake, host side (F-15) — dev log

Narrative record for `failsafe-update-recovery-handshake-spec.md`. What was
tried, what the hardware actually did, what theory was spent. Every hardware
measurement gets recorded here with the conditions it was taken under.

**Branch:** `feature/failsafe-update-boot-listen` — continued rather than
branched afresh (Simon, 2026-09-11). This spec is sub-task 5 of the same TODO
item, the code it edits (`_recover_query`, `_fast_recovery_handshake`) exists
only on that branch, and the two open P1s that block its merge — F-10 and
F-15 — are what this spec closes. One branch, one merge.

---

## Step 1 — extract the reply-interpretation and outgoing-bytes helpers

2026-09-11. Pure refactor, no behaviour change, no signature change on
`_query`.

- `_interpret_reply(response, command, expected_prefix) -> bytes` replaces two
  near-identical 27-line blocks in `_query` (the transport-provided branch and
  the new-transport branch). `grep -c 'startswith(b"ERROR:")' src/otampy/cli.py`
  went **2 → 1**, which is the step's DRY evidence.
- `_outgoing_bytes(command, signer)` replaces the `outgoing()` closure, so the
  step-3 recovery poll can reuse it without copying the fresh-counter rule.

One subtlety worth recording, because it is the only place the refactor is not
a straight lift. In the new-transport branch the old code called `ser.close()`
*before* raising `DeviceError`, because the `except DeviceError: raise` handler
deliberately bypasses the broad `except Exception` that would otherwise close
the port. Extracting the raise into a helper moves that close out of reach, so
the call site wraps it:

```python
try:
    res = _interpret_reply(response, command, expected_prefix)
except Exception:
    ser.close()
    raise
```

Without that the port would leak on every device refusal. The prefix-mismatch
`ClickException` path is unchanged too: it closes, then the broad handler
catches it, closes again (guarded) and retries, exactly as before.

**Evidence:** 7 new tests in `tests/test_cli.py` covering the `ERROR:` path,
the exact-prefix path, both colon-strip forms, a mismatched prefix, and
`_outgoing_bytes` with and without a signer. Red first with
`ImportError: cannot import name '_interpret_reply' from 'otampy.cli'`, then
`152 passed`. The pre-existing `_query` suite is the regression net and was not
edited. `pre_flight_check.py` exit 0.

No hardware involved in this step.

---

## Step 2 — fix the `--recover` timeout tests (F-13)

2026-09-11. Test-only change. Three tests set `OTAMPY_RECOVERY_WAIT=0`, which
`_coerce_config_value` rejects before the command runs; they asserted only
`"recovery-wait" in output`, which the *validation* error also satisfies. All
three now use `0.001` — the pattern the F-11 tests already use — and assert on
the real wording, `No recovery window answered`, plus the command name.

The demonstration the spec asked for, run in this order so the reds are
attributable to nothing else:

**1. The false pass, proven.** With `_recover_query`'s timeout message
temporarily replaced by `f"SABOTAGED MESSAGE {command.decode()} "`, the three
tests as they stood:

```
3 passed, 149 deselected in 0.22s
```

Green with the message they claim to test entirely destroyed. That is F-13.

**2. The same sabotage, against the fixed tests:**

```
FAILED tests/test_cli.py::test_recover_query_raises_naming_recovery_wait_when_nothing_answers
FAILED tests/test_cli.py::test_recover_query_restores_handshake_timing_even_on_timeout
FAILED tests/test_cli.py::test_rollback_recover_times_out_with_recovery_wait_message
3 failed, 149 deselected in 0.30s
```

The failure output also shows the CLI now reaching the retry loop and printing
the operator prompt before timing out, which the `0` version never did.

**3. Sabotage reverted** (`git checkout -- src/otampy/cli.py`): `152 passed`,
`pre_flight_check.py` exit 0.

Noted in passing: the timeout message renders `within 0s` at a 0.001 s wait,
because it formats with `{wait:.0f}`. Harmless in the test, and step 4 rewrites
that message anyway — recorded so it is a decision rather than an oversight.

`test_recover_query_restores_handshake_timing_even_on_timeout` is fixed here
and **deleted in step 3**, which removes the fast-handshake profile it guards.
Fixing it first is deliberate: it means the restore-on-timeout behaviour was
genuinely exercised at least once before it was removed.

---

## Step 3 — hold the port open and retry the handshake (F-15)

2026-09-11. The fix itself. `_recover_query` now opens the port **once**,
holds it for the whole poll, and retries `transport.protocol.connect()` on
that single transport at stock URST timings. `urst.constants` is no longer
mutated at all.

The body decomposes into three small pieces rather than one long loop:

- `_recovery_attempt(transport, command, expected_prefix, signer)` — one
  handshake-then-command exchange. Every "the window wasn't there" outcome
  raises `_RecoveryMiss`; `DeviceError` passes straight through.
- `_reset_recovery_session(transport)` — clears `is_connected` and drains
  `_recv_queue` after a miss.
- `_close_quietly(ser)` — used by both the `finally` and the reopen path.

Three decisions worth recording, because none is forced by the spec text:

1. **`except OSError` covers `serial.SerialException` too** — pyserial's
   exception is an `OSError` subclass, so one clause handles both rather than
   importing `serial` into this function just to name it.
2. **A reopen that itself fails is not fatal.** On `OSError` the port is
   closed and `transport` set to `None`; the *next* cycle reopens. If that
   reopen also raises, it is caught by the same handler and retried, so a port
   that vanishes for a few seconds (a device resetting its USB) is absorbed
   rather than ending the poll. The initial open stays outside the loop, so a
   genuinely wrong `--port` still fails immediately instead of after 60 s.
3. **A prefix mismatch is treated as a miss, not an error.** `_interpret_reply`
   raises `ClickException` for a reply that doesn't carry the expected prefix;
   `_recovery_attempt` converts that to `_RecoveryMiss`. This preserves the old
   blind-retry behaviour exactly — `_query` raised, `_recover_query` caught
   `ClickException` and retried — and during a recovery poll a non-matching
   frame is far more likely to be a stale frame than a protocol fault.

`_RECOVERY_SERIAL_TIMEOUT` moves 0.1 → 0.2, `_RECOVERY_HANDSHAKE_GAP_S` is new
at 0.05. Deleted: `_fast_recovery_handshake`, `_RECOVERY_ACK_TIMEOUT_MS`,
`_RECOVERY_MAX_RETRIES`, `_query`'s `fast=` parameter and its
`fast_serial_timeout` plumbing, and the now-unused `contextmanager` import.

**Evidence:** 8 of the 10 tests in the rewritten `_recover_query` block were
red before the change (the invariant test and the default-serial-timeout test
were green either way, which is what a guard test should do). After:
`155 passed`, `pre_flight_check.py` exit 0, `grep -c 'fast=' src/otampy/cli.py`
→ **0**.

**Not yet proven on hardware.** Every claim above is host-side reasoning and
unit tests. Whether this actually lands a command in a real window is step 7,
and until that runs F-15 is `fixed`, not `closed`.

---

## Step 4 — re-word the operator prompt

2026-09-11. The prompt an operator reads while standing over the power switch
now matches what the host does. Before:

> Power-cycle the device now. Retrying for 60s...
> ... so one power cycle should be enough. ... If this times out, run the
> command again and power-cycle when prompted.

After:

> Power-cycle the device now. Handshaking about once a second for up to 60s...
> ... so one power cycle is normally enough. ... This command needs the port
> to itself while it waits, so nothing else should be talking to the device.
> If it times out, run it again and power-cycle when prompted.

The exclusivity sentence is the substantive addition — it is the contract
decided 2026-09-10 and written up properly in step 6, and it is the one thing
an operator on a mux deployment can get wrong from the terminal.

**Evidence:** `test_recover_prompt_describes_the_cadence_it_actually_uses`
asserts on flattened whitespace (Rich wraps at the terminal width). I wrote the
wording before the test here, so redness was proven afterwards by restoring the
old prompt: `1 failed`, `AssertionError` at the `about once a second` line.
Restoring that sabotage with `git checkout` also reverted the real change and
it had to be reapplied — noted so the commit's provenance is clear.
`156 passed`, `pre_flight_check.py` exit 0.

---

## Step 5 — F-14: an at-risk boot never gets less than an ordinary boot

2026-09-11. A four-line change in `boot.run()`, plus the docs that promised
something different.

```python
window_ms = 0
if had_boot_mark or state(core)[0] != _LABEL_STABLE:
    window_ms = _boot_recovery_window_ms(core.config)
if window_ms <= 0:
    window_ms = _config_int(
        core.config, "OTA_BOOT_LISTEN_MS", _DEFAULT_BOOT_LISTEN_MS
    )
```

My first attempt read `OTA_BOOT_LISTEN_MS` unconditionally and used
`_boot_recovery_window_ms(...) or window_ms`. Shorter, but it broke the spec's
stated device cost — "zero cost on the default configuration" — by adding a
config read to every at-risk boot. The `<= 0` form skips the short-key read
whenever the wide window was actually selected, which is the default path.

**A finding within the finding.** The second test I wrote,
`..._a_marked_boot_with_the_wide_key_zero_...`, passed *before* the fix. With
the wide key at `0`, `_boot_mark_path()` returns `None` — the off-switch lives
there — so the marker is never written or read, `had_boot_mark` is always
False, and a "marked" boot is indistinguishable from a healthy one. F-14 is
therefore only reachable through the **journal** path, not the marker path.
The test is kept with an honest docstring, because that interaction is
non-obvious and the next reader would otherwise assume both halves fall back.

A third test pins that both keys at `0` still opens no window anywhere — the
fallback is to `OTA_BOOT_LISTEN_MS`, not to a hardcoded default, so opting out
entirely is still possible.

**Docs corrected in four places**, all of which stated or implied that `0`
removes every window: `configota.example.py`, `docs/protocol.md` §2.4 (the
duration table gains the `0` row and the invariant in bold, and the marker
paragraph now says the marker is unread when the wide window is off), and
`docs/architecture.md` in two places.

**Evidence:** `test_a_trial_boot_with_the_wide_key_zero_keeps_the_short_window`
red first with `AssertionError: assert 0 == 111`, then `375 passed` across the
device suite. `pre_flight_check.py` exit 0.

No hardware involved — the measured 56 ms no-window boot in F-14's evidence
already established the behaviour on device; this step changes the selection
and its tests, not the window itself.

---

## Step 6 — docs and changelog for the host-side recovery path

2026-09-11. Documentation only.

`docs/protocol.md` §2.4 gains a **How the host reaches the window** bullet.
The spec's bar was "accurate enough that F-15's failure mode could not be
reintroduced by someone following the doc", so it is written as three
load-bearing properties with the measurements attached rather than as a
description of the current code: the port is held open (reopening toggles
DTR/RTS on the FTDI→XBee at the worst moment), each attempt uses the full
stock handshake (the fail-fast profile landed 0 in 60 s against a window
proven open for 9006 / 9017 / 8977 ms), and the serial-timeout inequality
with the reason `read_frame()` makes it matter. The inequality carries an
explicit instruction to re-check it when touching `serial_timeout_seconds` or
`ACK_TIMEOUT_MS`, since those are the two edits that would silently undo it.

A separate **Exclusivity** bullet records the contract decided 2026-09-10:
`--recover` owns the port for up to `recovery-wait`, so a mux deployment's
gateway must not be contending for `mux.ota_port`. `docs/architecture.md` gets
the short version and points at §2.4.

`CHANGELOG.md`: the existing recovery-window entry gains a "How the host
reaches it" sub-bullet carrying the 0-in-60 s evidence, and the tier bullet's
"Either key set to `0` disables its own tier" is corrected to state F-14's
fallback.

`pre_flight_check.py` exit 0 (no code changed).

---

## Step 7 — HIL verification

**Rig, 2026-09-11 13:49 BST.** Pico W, gateway stopped so `/dev/ttyUSB0` (the
XBee) is uncontended and exclusive. Deployed from this branch with
`otampy deploy --port /dev/ttyACM0 --device-dir src/otampy/device/examples --with-logger`
(device-dir is project-root relative). Host config all at shipped defaults —
`recovery-wait 60`, `serial-timeout 2.0`, `query-retries 3`. Device config from
`configota.example.py`: `OTA_BOOT_LISTEN_MS 1000`,
`OTA_BOOT_RECOVERY_LISTEN_MS 8000`, `OTA_TRIAL_BOOTS 3`, `LOG_LEVEL DEBUG`,
`LOG_USE_TICKS True`, auth off. Post-deploy verified over the radio, not USB:
`ping` → `PONG`, `ls /` clean (no `.bck`, no journal, no marker).

### Two process errors of mine, recorded so the evidence is not misread

1. **`otampy upd --no-confirm main.py` does not do what the spec text says.**
   `upd` resolves an argument as a project-relative path and **preserves that
   path on the device**, so it created `/src/otampy/device/examples/main.py`
   and left `/main.py` untouched. The device was never stranded; a `PONG`
   gave it away. The correct form is the explicit `source:target` syntax:
   `otampy upd --no-confirm src/otampy/device/examples/main.py:main.py`.
   Cleaned up with `otampy confirm` + `otampy rm --literal-remote-paths /src`.
   **The spec's Verification section should be corrected** — anyone following
   it literally will silently fail to strand the device.
2. **Two `rollback --recover` runs were started without waiting for Simon**,
   so nobody was at the rig to power-cycle. Neither is a test result and
   neither is counted. The first aborted instantly on the `[y/N]` prompt
   (no stdin — `rollback` has no `--no-confirm`, so the CLI needs `yes |`);
   the second polled the full 60 s and timed out correctly. Recorded as
   coordination failures, not as HIL 1 attempts.

### Host-side evidence obtained (no power cycle needed)

Against the genuinely stranded, silent device, the poll's cadence was measured
by timestamping urst's handshake logging at `OTAMPY_RECOVERY_WAIT=20`:

```
  0.13s  Handshake attempt 1
  1.18s  Handshake timeout / attempt 2
  2.24s  Handshake timeout / attempt 3
  3.30s  Handshake timeout / attempt 4
  4.46s  Handshake attempt 1      <- next connect(), 0.10s gap
  ...
 21.68s  Handshake timeout
 21.69s  Error: No recovery window answered 'ROLLBACK' within 20s.
```

- **One CONNECT frame on the wire every 1.06 s, continuously** — 20 frames in
  20 s, with only a 0.10 s gap between one `connect()`'s four attempts and the
  next call. This is the `~1 CONNECT/s at stock URST timings` claim of
  `docs/protocol.md` §2.4, confirmed on the real link.
- Against the measured ~9 s window that is **~8 CONNECT frames inside any open
  window**, versus the fail-fast profile that landed 0 commands in 60 s.
- The port was opened **once** for the whole 20 s poll (`_open_transport` is
  not re-entered; no repeated `Initializing Protocol Layer`).
- The step 2/4 timeout message rendered correctly from the real command path.

A caution against my own earlier reading: a first count of "14 handshake
attempts in 60 s" was an artifact of piping the run through `tail -30`, which
kept only the last 30 lines of output. The cadence was never anomalous. Count
from a complete stream or not at all.

### HIL 1/2/4 — outstanding

Still to run; each needs a power cycle at the prompt, so each is gated on
Simon being at the rig and saying go.

### HIL 1 — attempt log

**Protocol correction, made after two wasted attempts.** Asking Simon to
power-cycle and *then* starting the poll races the round-trip latency between
us: he cycles within a second or two of replying, but my command may not start
for another ten, by which time the window (t≈1.5 s to t≈10.5 s from power-on)
has already shut. The poll then handshakes at a device sitting dead at the
REPL, and the log is indistinguishable from a genuine failure. **The poll must
be started and verified live first, and the cycle requested only afterwards.**
`recovery-wait` is raised for these runs purely to absorb that round-trip; what
the evidence then has to show is that the landing itself happens quickly enough
that the shipped 60 s default is ample.

| # | Protocol | Cycled? | Result |
| --- | --- | --- | --- |
| — | ask-then-poll | no (no stdin, aborted on `[y/N]`) | discarded, not an attempt |
| — | ask-then-poll | no | discarded, not an attempt |
| 1 | ask-then-poll, 60 s | yes, within a few seconds | **no landing in 60 s** — inconclusive: cannot separate a real miss from a poll that started after the window shut |
| 2 | **poll-first**, 300 s | yes, poll verified live first | **PASS** |

**Attempt 2 — the first genuine radio recovery of a stranded device.**
Timestamps are seconds into the poll:

```
  34.77s  Handshake attempt 1
  35.83s  Handshake timeout / attempt 2
  36.89s  Handshake timeout / attempt 3
  36.92s  URST Connected (received CONNECT_ACK)   <- the window answered
  36.92s  Sending frame type 0x1, seq 0, attempt 1
  36.95s  Received ACK for seq 0
  37.12s  Device is reverting to the previous version and rebooting...
  ...     post-reboot health wait
  49.94s  Rollback complete. The device is running the previous (stable) version.
```

- **The command landed on the third CONNECT after the device's radio woke** —
  ~2 s from first contact to `ROLLBACK` acknowledged. Power-on cannot be
  timestamped from the host, but with the cold-XBee wake-up at t+3.6 s to
  t+8.7 s the landing sits around t+6 s to t+10 s from power-on, i.e. inside
  the window and far inside the 60 s default. The 300 s wait absorbed the
  Claude↔Simon round-trip, not the recovery.
- Evidence afterwards, all over the radio with no USB: `ping` → `PONG`;
  `otampy cat /main.py` is the good example version again; `otampy ls /` shows
  `boot.py configota.py lib/ main.py ota.log` — **no `main.py.bck`, no
  `otampy-update.journal`, no `otampy-boot.mark`**; `otampy state` → "Running a
  confirmed (stable) build."

**This is the capability F-10 and F-15 exist for, working for the first time:**
a device deliberately bricked at the application level, recovered over the
radio, with USB never touched.

**Not yet the spec's bar.** That is three first-cycle passes, and this is one —
and taken at a raised `recovery-wait`. Attempts 3 and 4 follow, and at least
one run should be taken at the true 60 s default now that the poll-first
protocol removes the latency race.

**Incidental confirmation:** trial auto-restore works. Before this run the
device had spent its 3 trial boots while stranded, and the next boot restored
the good `main.py` by itself, unprompted — observed, not tested for.

### HIL 1 — PASSED (three first-cycle recoveries)

All three at `OTAMPY_RECOVERY_WAIT=300`, poll started and verified live before
the cycle was requested. Timestamps are seconds into the poll; "CONNECT #" is
which attempt within the `connect()` call answered.

| Attempt | Device answered | CONNECT # | Wake→ACK | `Rollback complete` | Tree after |
| --- | --- | --- | --- | --- | --- |
| 2 | 36.92 s | 3rd | ~2.2 s | 49.94 s | clean |
| 3 | 40.20 s | 2nd | ~1.1 s | 55.31 s | clean |
| 4 | 33.65 s | 4th | ~3.2 s | 46.81 s | clean |

"Clean" means, verified over the radio with USB never touched: `ping` → `PONG`,
`otampy state` → "Running a confirmed (stable) build", `otampy cat /main.py` is
the good example version, and `otampy ls /` shows no `main.py.bck`, no
`otampy-update.journal`, no `otampy-boot.mark`. Each attempt was preceded by a
deliberate re-strand (`otampy upd --no-confirm ...:main.py` with the fatal
`main.py`) so every run started with a full trial-boot budget and no attempt
could be rescued by auto-restore.

**The landing is fast once the device is reachable: 1.1 s, 2.2 s, 3.2 s.** All
three landed within a single `connect()` call of the device's radio waking. The
whole recovery — power-on through `Rollback complete`, including the CLI's
post-reboot health wait — fits inside ~15 s.

**On the raised `recovery-wait`.** 300 s was used to absorb the Claude↔Simon
round-trip, not the recovery. The figure that matters for the shipped 60 s
default is wake→ACK, and at 1–3 s it has ~20× margin. An operator standing at
the device, who cycles on reading the prompt, has the whole 60 s available;
our constraint was that a request had to travel to a human reading chat.
A run attempted at the true 60 s default (attempt "3" in the earlier table)
timed out with **no CONNECT_ACK in the log at all** — Simon did not see the
prompt in time and never cycled. That is a harness artifact and is recorded as
discarded, not as a failure of the default.

**Method note worth keeping.** A `--recover` run that logs no `URST Connected`
line anywhere did not miss the window — the device never woke inside the poll
at all. That single line cleanly separates "operator/coordination problem" from
"the mechanism missed", and it is the check that should have been applied to
the 2026-09-10 session before its conclusions were drawn.

### HIL 2 — PASSED (update a stranded device through the window)

`otampy upd --recover src/otampy/device/examples/main.py:main.py` against a
device stranded by the fatal `main.py`, one power cycle, poll-first protocol.
Timestamps are seconds into the command:

```
   0.13s  Handshake attempt 1        <- normal-path pre-flight, 2.0s/attempt
  25.21s  Power-cycle the device now...   <- recovery poll begins, 1.06s cadence
  69.08s  Device is READY. Handshake complete.
  69.08s  Sending manifest (2 files, 4067 bytes)...
  73.79s  Update completed successfully! Device is rebooting.
  88.93s  Candidate confirmed.
```

`Device is READY. Handshake complete.` is the evidence the spec asked for: the
window's `UPDATE_REQUEST` → flag → reset path fed a **normal** update session.
Afterwards, over the radio: `ping` → `PONG`, `state` → confirmed stable, and
`ls /` shows `main.py.bck` and `otampy-update.journal` present — correct after
a *confirmed* update, since that retains the previous generation, unlike a
rollback which consumes it.

Confirmed device-side in `/ota.log.1`:
`10190 [INFO] [boot.py] Recovery window: update requested; resetting`.

**Noted for follow-up:** `upd --recover` spends ~25 s failing on the normal
path (3 × 4 handshake attempts at the 2.0 s serial timeout) *before* printing
the power-cycle prompt. `rollback --recover` starts polling at 0.1 s. An
operator with a stranded device stares at handshake warnings for 25 s before
being told what to do.

### HIL 4, first half — the marker is present while stranded: EVIDENCED

On the stranded device, read over USB (legitimate here — a stranded device is
not polling, so USB is the only truth):

```
ls :/
        1008 boot.py
        3056 configota.py
           0 lib/
         339 main.py          <- the fatal fixture
       10252 ota.log.1
         248 ota.log
           1 otampy-boot.mark <- present, so the wide window is selected
```

No `main.py.bck` and no `otampy-update.journal`, so the wide window was being
selected off the **marker** alone — the `rollback --recover` case the marker
exists for, exercised for real.

### The wide window, measured device-side across the whole session

`Checking for update flag-file...` → `<flag> not found` brackets the window
(the `not found` line is logged at `boot.py:688`, *after* it — an earlier
reading of mine measured `not found` → `Cleanup started`, which is 17 ms of
nothing and briefly looked like a regression):

**8980, 8663, 8976, 8977, 8931, 8978, 8927, 8923 ms** — consistent, on every
boot, including boots caused by `mpremote`'s DTR reset. The 8663 ms entry is
HIL 2's landing, where the window ended early because it did its job.

### Test 6 (refusal with nothing retained) — UNRESOLVED

Set up accidentally but perfectly: see the test-4 finding below. The device was
stranded with no retained generation and the marker present.

Two power cycles across a 300 s poll produced **no `URST Connected` line at
all** — the device never handshook, though `/ota.log.1` shows its windows were
opening at ~8.9 s throughout. Not explained. It is *not* attributable to the
host fix, which landed 4 for 4 in HIL 1 and 2 under the same protocol.

I then compounded it: chasing the silence, I ran several `mpremote ... resume
fs ls` / `fs cat` reads. **`resume` avoids the DTR reset but still enters raw
REPL, which stops the running program** — so the board sat parked, `poll()` was
never reached, `otampy-boot.mark` stayed uncleared, and every subsequent radio
ping failed. I spent several rounds diagnosing a dead radio that I had caused.
A genuine power cycle with hands off USB brought it straight back: `PONG`,
confirmed stable, clean tree. **The rule is not "avoid `mpremote` reset"; it is
"avoid `mpremote`, full stop, on a device you still need to observe."**

Test 6 should be retried on a rig session that has not been polluted by USB
before any conclusion is drawn about it.

### Not attempted

- Test 5 (the window is not an auth bypass) — needs `OTA_REQUIRE_AUTH` set on
  the device plus a redeploy and further cycles. **This is the one outstanding
  test that matters most**, because a held-open poll now hammers an
  auth-enforcing window for up to `recovery-wait`, a longer exposure than
  anything previously tested.
- Regression: the healthy-boot cost A/B (HIL 3). Untouched by this spec.

### Test 5 — the window is not an auth bypass: PASSED

2026-09-11, run after the rest of step 7. Rig prepared by a full USB redeploy
with `OTA_REQUIRE_AUTH = True`, a throwaway 64-hex `COMMAND_AUTH_KEY` and
`OTA_REPLAY_FLOOR_FILE` enabled, so the device required auth from its first
boot rather than being switched over mid-session. Baseline before stranding:
signed `ping` → `PONG`, unsigned `ping` → `Error: Unauthenticated`.

Device then stranded by the fatal `main.py` via a signed
`upd --no-confirm ...:main.py`, which retains `main.py.bck` — so a rollback
had something real to revert, and "nothing was reverted" is a checkable claim.

| Half | Host key | Window's answer | Device afterwards |
| --- | --- | --- | --- |
| A | **unset** | `Error: Unauthenticated` at 35.09 s | still stranded, `.bck` untouched |
| B | **set** | accepted at 34.82 s, `Rollback complete` at 50.40 s | good `main.py`, confirmed stable, clean tree |

Half A, from the timestamped log:

```
  34.78s  Handshake attempt 1
  34.80s  URST Connected (received CONNECT_ACK)   <- the window answered
  34.80s  Sending frame type 0x1, seq 0, attempt 1
  34.84s  Received ACK for seq 0
  35.09s  Error: Unauthenticated
```

**Half B is the evidence that half A reverted nothing.** A signed `ROLLBACK`
afterwards still found a retained generation and restored it; had the
unauthenticated attempt reverted anything, there would have been nothing left
to roll back to. This matters because a stranded device cannot be inspected
with `otampy ls` over the radio, and the alternative — a USB read — would have
parked the board (see the test 6 section above).

Post-recovery, over the radio: signed `ping` → `PONG`, `state` → confirmed
stable, `ls /` shows `boot.py configota.py lib/ main.py ota.log
otampy-replay-floor` — no `.bck`, no journal, no marker — and **unsigned
`ping` still returns `Unauthenticated`**, so recovery did not weaken auth.

#### The exposure concern was wrong, and measurably so

The worry that motivated running this test was that a held-open poll now
hammers an auth-enforcing window for up to `recovery-wait`. It does not.
Measured across half A's 35 s poll:

- **33 handshake attempts, exactly 1 unsigned command delivered.**

Two properties of the design bound it, and both are now confirmed on hardware
rather than merely argued from the source:

1. `_recovery_attempt` sends the command **only after `connect()` succeeds**,
   so nothing is put on the wire at all while the device is absent — which is
   most of any poll.
2. A refusal is a `DeviceError`, which propagates and **ends the poll
   immediately** rather than retrying. The 300 s wait was still available and
   went unused.

So the auth surface sees one unsigned command per `--recover` invocation,
regardless of `recovery-wait`. That is strictly less exposure than the old
reopen-per-cycle design, which blind-sent the command on every cycle.

### HIL fixtures — recreate these, do not hunt for them

The scratchpad is session-scoped, so these do not survive a cleared context.
Both are tiny; recreate rather than search.

**The fatal `main.py`** — strands the device before its runtime OTA surface
exists, and arms no watchdog so trial auto-restore cannot fire and mask
whether `--recover` did the work:

```python
"""
Deliberately fatal main.py -- HIL 1/2 of the recovery-handshake spec.

Raises on import, so the device never reaches ota.poll() and is stranded
before its runtime OTA surface exists. Arms NO watchdog, so trial
auto-restore cannot fire and mask whether --recover did the work.
"""

raise RuntimeError("HIL: deliberately fatal main.py")
```

**The good `main.py`** is just `src/otampy/device/examples/main.py` at HEAD —
it is **tracked**, so the strand/restore cycle is:

```bash
cp <fatal fixture> src/otampy/device/examples/main.py
otampy upd --no-confirm src/otampy/device/examples/main.py:main.py
git checkout -- src/otampy/device/examples/main.py     # restore immediately
```

The `source:target` form is required — a bare `main.py` resolves against the
project root and writes `/src/otampy/device/examples/main.py` on the device
instead of `/main.py`, which looks like a clean update and is a silent no-op.

### Test 6 — COULD NOT BE EXECUTED (second attempt), and it exposes a gap

2026-09-11, retried deliberately after the first inconclusive run. Precondition
built cleanly this time by a fresh USB deploy of the fatal `main.py`, which
provisions the tree from scratch: stranded, **no `.bck`, no journal, no
marker** on the first boot. Confirmed stranded by a failed `ping`.

The refusal never happened, because **no command reached the window**. The poll
ran ~152 s at 1.06 s/CONNECT with zero `URST Connected` lines.

**Device-side ground truth** (`/ota.log`, read over USB after the poll, device
already stranded so nothing was interrupted that was running):

| Boot | `Checking for update flag-file...` -> `not found` | Duration | Tier |
| --- | --- | --- | --- |
| 1 (deploy's reset) | 1547 -> 3374 | **1827 ms** | short -- marker absent, correct |
| 2 (Simon's cycle) | 1507 -> 10415 | **8908 ms** | **wide -- marker present, correct** |

So the device selected the right tier and held a full ~8.9 s window open on the
power cycle, while the host was polling. The radio was then proven healthy
immediately afterwards: 3/3 `PONG` over the same link after restoring a good
`main.py`.

**What the log cannot tell us:** it brackets the window but records nothing
about what the device's transport *received*. A window whose `read()` never
sees a byte and a window nobody transmitted into are indistinguishable in it.
That is the gap to close, and it needs on-device instrumentation (a count of
bytes/frames seen inside the window, logged on exit).

#### The correlation, stated as correlation

| Stranded how | Journal state | Wide window via | `--recover` landings |
| --- | --- | --- | --- |
| `upd --no-confirm` (HIL 1 x3, HIL 2, test 5 x2) | unconfirmed candidate | journal **and** marker | **6 / 6** |
| fresh deploy, or a rollback that consumed the `.bck` (test 6 x2) | stable, none | **marker only** | **0 / 2** |

This is striking and it is *not* proof. Against it: the window body is
identical in both cases, the measured duration is the same ~8.9 s, and
`had_boot_mark` short-circuits the `state(core)` call in both (the marker is
present either way, so the journal never even gets read on the recovery boot).
There is no mechanism in the selection code that could make these differ. A
plainer confound also survives: operator cycle timing relative to the poll,
which we cannot timestamp from the host and which has already produced one
falsely-recorded miss in this session.

Six versus two is also not many trials.

**Why it matters anyway.** The marker exists precisely for the case the
journal cannot see -- a **confirmed** generation that later proves fatal, which
is the `rollback --recover` scenario in F-10's own words. Every landing we have
is from the other path, the one where the journal alone would have sufficed. So
the marker's own reason for existing has never been demonstrated end to end.

**Next step if this is picked up:** add temporary device-side instrumentation
to `_run_boot_listen` logging bytes/frames seen and iteration count on exit,
deploy, and run the marker-only strand three times. That distinguishes "the
window never heard anything" from "the window heard and did not answer" in one
run, and neither can be inferred from what we have.
