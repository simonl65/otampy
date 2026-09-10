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
