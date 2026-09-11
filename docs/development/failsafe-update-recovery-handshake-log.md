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
