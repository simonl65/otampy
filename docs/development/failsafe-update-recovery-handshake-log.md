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
