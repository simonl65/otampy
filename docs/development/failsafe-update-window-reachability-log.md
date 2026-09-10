# Boot-time recovery window reachability (F-10) — dev log

Narrative record for `failsafe-update-window-reachability-spec.md`. The spec is
the plan; this is what actually happened, including every hardware measurement
with the conditions it was taken under.

**Branch:** `feature/failsafe-update-boot-listen` (continued, not a new one —
the spec's prerequisites are the host-side F-10 fixes in `172d93c` / `269a25d`,
which are unmerged on that branch).

---

## 2026-09-10 — spec amendment before step 1: what a non-integer key means

The approved spec contradicted itself on a non-integer
`OTA_BOOT_RECOVERY_LISTEN_MS`. Step 1 required `_boot_mark_path` to return
`None` for it (marker disabled); step 3 required it to fall back to the default
8000 (wide window enabled). Both could not hold, and as written a typo would
disable the marker while still paying an 8 s window off the journal test.

The deeper look settled it on evidence rather than taste:

1. **A non-integer is a typo, not a config style.** `int("8000")` → 8000 and
   `int(8000.5)` → 8000 both succeed, so only genuine garbage (`None`, `"8s"`,
   `""`) ever reaches the fall-back.
2. **The repo had already decided the question three times**, once in the very
   function step 3 modifies:
   - `_run_boot_listen` / `OTA_BOOT_LISTEN_MS` — garbage → default 1000,
     `<= 0` → off.
   - `_run_default_update_loop` / `OTA_TIMEOUT_MS` — garbage → default 5000,
     `< 1` → default 5000 (no off-switch at all).
   - `restore.read_journal` — an unparseable first line is treated as
     `committing`, its docstring saying "fail safe, meaning restore
     everything".

   House rule: **an unparseable value falls back to the safe working default;
   only an explicit, in-range sentinel turns something off.**
3. Step 1's version was therefore fail-*closed*, and in the dangerous
   direction: `OTA_BOOT_RECOVERY_LISTEN_MS = "8s"` would silently remove the
   only radio recovery path, discovered when a device is bricked and will not
   answer. That is F-10 reintroduced through a config mistake.

**Resolved (Simon, 2026-09-10): option C.** `core._boot_recovery_window_ms`
becomes the single parse (garbage → 8000, `<= 0` → off); `_boot_mark_path`
returns `None` iff that is `<= 0`; step 3's `run()` calls it for the duration
rather than parsing the key a second time. A shared helper rather than just
fixing the wording, because step 3 needs the parsed duration anyway — two parse
sites is the drift that produced the contradiction in the first place.

---

## 2026-09-10 — step 3: two findings the host tests surfaced

**1. The wide window is real, and the test suite proved it the hard way.**
On first running step 3 the device suite went from ~0.5 s to **32 s**. Cause:
`_no_flag_core` and eight inline configs disabled only `OTA_BOOT_LISTEN_MS`.
Any test writing a `trial` journal now correctly selects the *wide* key, and at
its 8000 ms default that is a real 8 s wait per test. Fixed by disabling both
tiers in the "no window" configs (`OTA_BOOT_RECOVERY_LISTEN_MS = 0`) and giving
`_no_flag_core` 1 ms rather than 0, since 0 also switches the marker off and
step 1's tests need it written. Back to 0.54 s.

This is worth recording because it is the *first* independent confirmation
that the selection logic actually fires: nothing was mocked, the tests simply
started paying the wide window because they qualified for it.

**2. The spec's `committing -> wide` row is unreachable through `run()`.**
The spec's *Window duration selection* table lists a stray `committing`
journal as selecting the wide window. It cannot: `repair()` runs first and
reverses a stray `committing` marker, so by the time the duration is chosen
the journal reads confirmed and the short window is correct. `restore.state`'s
own docstring already says as much ("not seen at runtime -- `repair()` clears
it first").

Not a broken premise about device behaviour, and not a reason to change the
code: `!= _LABEL_STABLE` is still the right defensive form, and is strictly
safer than an equality test against `"trial"`. The test was rewritten to pin
what is actually true --
`test_a_stray_committing_journal_never_reaches_the_selection` asserts the
short window *and* that `state()` still maps `committing` to a non-stable
label, so the guard stays honest if `repair()` ever leaves one behind.
Flagged to Simon rather than silently dropped.

**3. A conftest wart, found in step 1 and still open.** `conftest.py`
glob-loads submodules in arbitrary order, so `boot`'s `from .core import ...`
can bind to a `device_otampy.core` instance the loop later replaces in
`sys.modules` -- there are two live `core` modules during a run. Harmless
today (nothing mutates module state) but it makes `monkeypatch.setattr` on a
device module silently no-op. Worked around locally by patching the resolver's
own `__globals__`. Adjacent to the existing `test_ota_facade.py` `sys.modules`
item in `TODO.md`; not fixed here.

---

## 2026-09-10 — step 5, run 1: the wide window breaks `otampy upd`'s health check

**Stopped before the HIL tests proper.** The very first action of step 5 — a
routine `otampy upd` to push a DEBUG/ticks `configota.py` for test 3's
instrumentation — failed, and it failed for a reason the spec did not
anticipate. Recording it here before going further.

### Rig and build

Pico W, deployed from this branch with
`otampy deploy --port /dev/ttyACM0 --device-dir src/otampy/device/examples --with-logger`.
`otampy` resolves to the working tree (editable install), so the deployed
`lib/otampy` is the branch code. Host default port is `/dev/ttyUSB0` (the XBee
gateway), so every `otampy` command below went over the radio, not USB.

Two rig notes, both worth keeping:

- The gitignored `src/otampy/device/examples/configota.py` was **stale** — it
  predated this whole sub-task and carried none of `OTA_BOOT_LISTEN_MS`,
  `OTA_BOOT_RECOVERY_LISTEN_MS` or `OTA_BOOT_MARK_FILE`. It would still have
  tested the right values by falling back to the defaults, but not visibly.
  Rebuilt from `configota.example.py`.
- The saved `device-dir` was `/src/otampy/device`, one level above the
  examples tree that is actually deployed. Set to
  `/src/otampy/device/examples` **permanently**, because the session-scoped
  setting does not survive between CLI invocations (the known `TODO.md`
  session-ports bug — it reports "Session device directory set to" and the
  next process reads the old value). **Restore it to `/src/otampy/device`
  when this sub-task is done.**

### What happened

`otampy upd` (bare, so it sends `boot.py`/`main.py`/`configota.py` from the
device dir) transferred and committed cleanly, then:

```
Committing update transaction...
Update completed successfully! Device is rebooting.
Waiting for the updated device to answer...
Error: Update committed but the device did not come back healthy (no PONG
within 10s). The candidate is NOT confirmed and will auto-restore the previous
version after OTA_TRIAL_BOOTS reboots. Investigate or re-deploy.
```

The device was **not** unhealthy. `otampy ping` answered `PONG` immediately
afterwards and `otampy state` reported `Candidate on trial (boot 1)`. It was
simply slower to answer than the host's 10 s allowance. `otampy confirm` then
took it off trial normally.

### The measurement

One batched `mpremote connect /dev/ttyACM0 fs cat /ota.log + reset` session
(hard reset chained on the end; device left alone to restart, then verified
healthy over the radio with `ping`/`state`, not more USB pokes). `ticks_ms` is
since the last *hardware* reset, so both boots below share one counter — the
second is the `mpremote`-induced soft reboot.

```
 897 [DEBUG] [boot.py] BOOTING...
1454 [DEBUG] [boot.py] Checking for update flag-file...
10353 [DEBUG] [boot.py] update_requested.flag not found
10363 [DEBUG] [boot.py] Cleanup started...
10645 [DEBUG] [boot.py] Cleanup complete
10661 [DEBUG] [boot.py] Loading MAIN...
10783 [DEBUG] [main.py] MAIN start-up...
11044 [DEBUG] [main.py] Application main loop started
...
51958 [DEBUG] [boot.py] BOOTING...
52595 [DEBUG] [boot.py] Checking for update flag-file...
54433 [DEBUG] [boot.py] update_requested.flag not found
54806 [DEBUG] [boot.py] Loading MAIN...
```

| boot | journal / marker | flag-check → not-found | window selected |
|---|---|---|---|
| post-commit (ticks 897) | `trial` | **8899 ms** | wide (8000) |
| post-`mpremote` soft reset (ticks 51958) | confirmed, marker cleared by `poll()` | **1838 ms** | short (1000) |

**The selection logic is correct and this is the first end-to-end proof of it.**
Wide on the trial boot, short on the healthy one, a ~7 s difference matching
`8000` vs `1000` exactly as step 3 specifies. Nothing here is a bug in the
window code.

### The problem it exposes

A post-commit boot has journal `trial`, so it selects the **wide** window by
design. That puts the device's polling main loop at ticks **11044** — but
`_post_commit_confirm` waits `update_ready_timeout_seconds`, default **10.0**
(`src/otampy/cli.py:61`), starting from the commit reply. The device cannot
win that race.

This is not rig-specific and not a logging artefact. The DEBUG writes here are
seven short lines, tens of milliseconds. The arithmetic is structural: 8 s of
window, plus ~1.4 s of pre-window boot, plus ~0.7 s of post-window startup,
against a 10 s budget. Any device at the shipped default loses.

Consequence: **every successful default `otampy upd` now reports failure and
leaves the candidate unconfirmed.** It self-heals if the operator runs
`otampy confirm` (as it did here), but the headline update path tells the
operator their update failed when it did not — and an operator who believes it
and re-deploys is doing so against a device on trial boot 2 of 3.

`_wait_for_pong` is shared with `otampy rollback` (`src/otampy/cli.py:2663`),
which faces the same arithmetic: the boot after a restore has not polled, so
it carries the marker and also selects the wide window. HIL test 1 expects
`ROLLBACK_OK` **and** a healthy device on the first power cycle, so this most
likely lands there too — untested as of this entry.

### Why the run stopped here

Per the spec's model gate: "Same stop applies mid-build if a test goes red for
a reason this spec did not anticipate — that is a broken premise, not a bug to
improvise around." The window behaviour is right; the host's 10 s assumption
is now stale, and choosing between widening the host timeout and narrowing the
`trial -> wide` rule is a design call, not a verification detail. Raised with
Simon; no code written.

Device left healthy, confirmed, on the branch build, with DEBUG/ticks logging
still enabled in its `configota.py`.

## 2026-09-10 — step 5, run 2: HIL 3 passes; the control half exposes F-14

Resumed after step 6 (F-11's fix) unblocked the session. Same rig and build as
run 1: Pico W deployed from this branch, host default port `/dev/ttyUSB0` (the
XBee), `device-dir` still `/src/otampy/device/examples`. The diff-drive-robot
gateway was **off** for the whole session so `otampy` had exclusive use of the
XBee — worth stating, since the gateway muxes that same port.

### Instrument: device-side ticks, not power-on → PONG

The spec words HIL 3 as "time power-on → first `PONG`". Measured that way the
figure is dominated by the XBee's own cold wake-up, which F-10 established at
**t+3.6–8.7 s** — a 5 s spread swamping the ~0.3 s difference the test is
trying to resolve. Used `/ota.log` `ticks_ms` instead: on a boot that begins
at a hardware power-on the counter *is* time-since-power-on, it is independent
of the radio, and it is the instrument F-11 and F-12 already used. Both halves
were taken this way, in one session, with a full power cycle before each
figure and no USB contact between the cycles of a half.

`configota.py` was pushed over the radio with `LOG_LEVEL = "DEBUG"` and
`LOG_USE_TICKS = True` for the measurement; the shipped default is `ERROR`.

### The A/B

Three power cycles per half, `Application main loop started` measured from
power-on. "Window" is the `Checking for update flag-file...` →
`update_requested.flag not found` span that brackets `state(core)` plus
`_run_boot_listen`.

| | window | → main loop |
|---|---|---|
| **A** `OTA_BOOT_RECOVERY_LISTEN_MS = 8000`, cycle 1 | 1876 ms | **4174 ms** |
| A, cycle 2 | 1863 ms | **4137 ms** |
| A, cycle 3 | 1900 ms | **4201 ms** |
| **B** `OTA_BOOT_RECOVERY_LISTEN_MS = 0`, cycle 1 | 1859 ms | **4102 ms** |
| B, cycle 2 | 1914 ms | **4309 ms** |
| B, cycle 3 | 1878 ms | **4166 ms** |

Mean 4171 ms with the wide window configured, 4192 ms with it disabled — a
**21 ms** difference against the spec's ~300 ms allowance, and the two ranges
interleave. **HIL 3 passes.** A healthy, confirmed, marker-cleared device does
not pay the wide window; both halves pay only the ~1 s `OTA_BOOT_LISTEN_MS`
short window (~1.87 s including `state(core)` and the log flush). This is the
evidence Option C was chosen on.

The ~0.87 s of consistent overhead above the configured window duration —
`state(core)`'s journal read, loop granularity, the flush of the bracketing
log line — is the same overhead F-12 measured, now confirmed across nine boots
rather than one.

### HIL 4, second half — proved, and a methodology trap

`otampy ls /` over the radio on the settled device shows **no
`otampy-boot.mark`**: cleared by the first `poll()`, as designed.

**It cannot be checked over USB.** The batched `mpremote fs ls` in this same
session showed the marker **present** — because connecting parks `main.py` in
raw-REPL before `poll()` ever runs, so the act of looking re-creates the thing
being looked for. The log shows it plainly: `KeyboardInterrupt` at 46287
ticks, fresh boot at 49251, and that boot's own marker is what `fs ls` then
reported. The spec's test 4 says "one batched `mpremote` session"; that is
wrong for the *absent* half and has been amended to use `otampy ls` over the
radio. The *present*-while-stranded half is unaffected — a stranded device is
not polling anyway, so USB tells the truth there.

### F-12, independently re-measured

Run 1 measured the wide window's blocking span at 8899 ms for a configured
8000. This session's post-commit trial boot (half A) measured **8952 ms** —
same path, different boot, slightly worse. Both overrun the 8388 ms RP2040 WDT
cap on their own, before the ~1.5 s taken to reach the window. F-12's
"shipped guidance makes a promise the shipped default cannot keep" now rests
on two measurements, not one.

### New: F-14, found by the control half

Half B's post-commit boot bracketed at 1538 → 1594 ticks: a **56 ms** span, or
**no window at all**, against ~1.87 s on the healthy boots of the same half.
Traced to `boot.py:645-651` — the selection is `if had_boot_mark or state !=
stable: window = _boot_recovery_window_ms(...)`, and with the recovery key at
`0` that branch yields `0`. So on a device that has deliberately disabled the
wide window, the **trial boot gets no window at all**, while every ordinary
boot still gets its 1 s. The riskiest boot in the system — the one running an
unconfirmed candidate that may be about to strand the device — is the one
stripped of its listen window, and `configota.example.py` promises only that
`0` "disables the wide window and the boot marker". Filed as F-14; practical
impact is limited by F-10 having already shown the 1 s window to be unhittable
after a power cycle, so this removes something that was barely there.

Not a blocker for this step: it needs the recovery key set to `0`, which is
not the default and not the configuration under test.

## 2026-09-10 — step 5, run 2 continued: HIL 1 fails. The window opens; the host cannot land in it

**HIL 1 does not pass, and F-10 cannot be closed.** Three attempts were
specified; the second consumed the device's whole trial-boot budget and the
run stopped there with a diagnosis, per the spec's "a red for a reason this
spec did not anticipate is a broken premise, not a bug to improvise around".

### Attempt 1 — passed, first power cycle

`otampy upd --no-confirm` with a `main.py` whose only statement is
`raise RuntimeError(...)` (no watchdog). Stranded confirmed: `otampy ping` →
`Failed to send command over transport`. Then `otampy rollback --recover`,
**one** power cycle at the prompt:

```
Device is reverting to the previous version and rebooting...
Rollback complete. The device is running the previous (stable) version.
```

`otampy ping` → `PONG`; `otampy state` → `Running a confirmed (stable) build.`;
`otampy cat /main.py` → the example `main.py`, no `HIL 1` marker; `otampy ls /`
→ no `main.py.bck`, no `otampy-update.journal`, no `otampy-boot.mark`. Clean
pass on the first cycle.

### Attempt 2 — failed twice, on two genuine power cycles

Re-stranded the same way. `otampy rollback --recover`, power cycle within ~5 s
of the prompt (operator timing confirmed, so the 60 s `recovery-wait` was not
the constraint):

```
Error: No recovery window answered 'ROLLBACK' within 60s.
```

Ran it again. Second genuine power cycle, same result. The device stayed
stranded — `ping` and `state` both `Failed to send command over transport`.

### The window did open. Both times.

Device-side ticks for the three stranded boots, read afterwards **over the
radio** with `otampy cat /ota.log` (no USB, application channel, device
polling normally):

| boot | flag-check → not-found | window |
|---|---|---|
| post-commit (stranding boot) | 1530 → 10536 | **9006 ms** |
| power cycle 1 | 1542 → 10559 | **9017 ms** |
| power cycle 2 | 1513 → 10490 | **8977 ms** |

A ~9 s window, open from t≈1.5 s to t≈10.5 s after power-on, on **every** one
of those boots. The device did exactly what step 3 built it to do. The host,
blind-retrying for 60 s across a window that was open for 9 of them, never
landed a single `ROLLBACK` in it.

### It is the fast recovery handshake, not the window

The decisive observation came by accident. After the session, a **`PING`**
sent on the **normal** handshake path landed inside a boot window and was
refused by the device:

```
Error: Recovery window
```

— `_RECOVERY_REFUSED = b"ERROR:Recovery window"` (`boot.py:31`), the window's
own refusal of a non-recovery command. So the window is reachable over this
radio, from this host, on a cold power cycle. What could not reach it is
`_recover_query`'s fail-fast profile (`cli.py:1055-1057`):
`ACK_TIMEOUT_MS = 500`, `MAX_RETRIES = 0`, serial read timeout `0.1 s`, one
CONNECT attempt per try.

Against this link that profile is close to hopeless, and tonight's logs say so
in every direction: **nearly every normal `otampy` command in this session
logged one or more `Handshake timeout` warnings before connecting**, at the
default 2.0 s serial timeout with 3 query retries — including commands to a
healthy, polling device. A single CONNECT attempt with a 0.1 s read timeout is
therefore a coin flip, and attempt 1's first-cycle success was the lucky side
of it, not evidence of margin.

That profile is F-10's *own* earlier repair (172d93c, "recovery poll — one
CONNECT attempt, small serial timeout"). The wide window fixed the half of
F-10 that was about the device; this is the half that was about the host, and
it is now the binding constraint. Filed as **F-15**.

### What actually rescued the device

Nothing over the radio. The trial-boot counter did it: on the 4th boot into
the unconfirmed candidate, `boot.py` restored the retained generation —

```
140770 [DEBUG] [boot.py] BOOTING...
restoring previous
141530 [INFO ] [boot.py] restore_all: restored /boot.py from backup
141605 [INFO ] [boot.py] restore_all: restored /main.py from backup
141685 [INFO ] [boot.py] restore_all: restored /configota.py from backup
generation restored, resetting
```

— and the device came back healthy and `confirmed (stable)` on the good
`main.py`, with no `.bck` and no journal left. **Sub-task 2's auto-restore is
the safety net that worked**, and it is the only reason attempt 2 did not end
at the USB cable. Worth stating plainly: the layered design held even though
the layer under test did not.

(That 4th boot was triggered by an `mpremote` soft reset during diagnosis, not
by a power cycle. It would have come on the next cycle regardless.)

### Rig notes from this run

- Two `OSError: [Errno 5]` events on the host's serial ports — one mid-transfer
  on `/dev/ttyUSB0`, one on `/dev/ttyACM0` — both host-side (Simon confirmed
  the host machine glitched). The mid-transfer one is incidental evidence
  worth keeping: the interrupted `UPDATE` aborted on the device's own 5 s
  inactivity timeout and the device came back `confirmed (stable)`, no mixed
  tree, no intervention.
- `mpremote` repeatedly could not `enter raw repl` against this device — both
  while stranded and while the application was running. Where it did connect,
  it parked `main.py` and the radio went silent until a power cycle, which is
  the documented hazard behaving exactly as documented. Reading `/ota.log`
  **over the radio** with `otampy cat` avoids the whole problem and is the
  better instrument; it is how the table above was obtained.
- HIL 4, first half, is **not** yet evidenced: the marker was observed present
  via USB, but only after `mpremote`'s own soft reset had written a fresh one,
  so it proves nothing. The second half (absent after a healthy polling boot)
  is evidenced, over the radio.

### Step 5 status

HIL 3 passes. HIL 4's second half passes. HIL 1 **fails**. HIL 2 not attempted
— it depends on the same `--recover` path F-15 indicts, so it would be
measuring the same defect. Step 5 stays unchecked; F-10 stays **open**.
