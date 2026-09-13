# Minifier breaks MicroPython f-strings with a conversion — dev log

Branch: `feature/minify-fstring-conversion`
Started: 2026-09-13

## The bug, restated from the repro

`minify_python_source` (`src/otampy/minify.py`) rebuilds source with
`tokenize.untokenize` fed `(type, string)` pairs. Two-tuples put `untokenize`
into **compat mode**, which reconstructs spacing heuristically rather than from
the recorded token positions — it appends a space after every `NAME` and
`NUMBER` token.

Since Python 3.12, an f-string is no longer one `STRING` token. It is tokenized
as a run: `FSTRING_START` `f"` , then the literal parts as `FSTRING_MIDDLE`,
the replacement-field expressions as ordinary tokens (`NAME`, `OP`, …), and
`FSTRING_END`. The conversion marker `!r` arrives as its own `OP` token.

So compat mode pads *inside* the replacement field. Confirmed locally on
CPython 3.12.12:

```
in : helper_write(f" machine.RTC().datetime({x!r})\n")
out: helper_write (f" machine.RTC().datetime({x !r })\n")
```

CPython still parses `{x !r }`. MicroPython's f-string parser does not: it
rejects whitespace between the expression, the conversion, and the closing `}`.
So `mpy-cross` refuses the minified file outright.

Real-world blast radius (measured in `diff-drive-robot`'s heap-attribution
task, 2026-09-13): 36 of 37 device files minify and compile cleanly. The one
failure is `src/otampy/device/lib/otampy/manager.py:67`, the RTC-update helper:

```python
helper.write(f" machine.RTC().datetime({time_tuple!r})\n")
```

`otampy upd/cp/deploy --minify` would ship that file, and it only fails on the
device's next boot.

## Notes carried in from the TODO item

Minification's heap payoff is negligible (<0.1 KB of steady-state device heap
in the same A/B) because MicroPython compiles to bytecode at import and keeps
no source, comments or docstrings — only line-number tables can shrink. It does
still cut on-flash/transfer size by ~21%. Not a reason to change the default
either way; this task is purely about correctness.

## Build steps

- [x] Step 1 — failing test: a conversion survives minification, and the
      minified `manager.py` compiles under `mpy-cross`.
- [x] Step 2 — fix: collapse each f-string token run back to one verbatim
      token so compat mode cannot pad inside it.

## Narrative

**Step 1 (2026-09-13).** Two tests in `tests/test_minify.py`:

- `test_minify_python_source_preserves_fstring_conversions` — a unit-level
  guard covering `!r`, `!s` with a format spec, and a *nested* f-string
  conversion. It asserts on both the emitted bytes and the executed result.
- `test_minified_device_sources_compile_for_micropython` — the real gate. It
  minifies every deployed device source and compiles each with `mpy-cross`,
  skipping if `mpy-cross` is absent so CI does not hard-fail on it.

Both failed for the right reason before the fix. The `mpy-cross` one
reproduced the hardware finding exactly: `lib/otampy/manager.py` and nothing
else.

The first pass of that test globbed the whole device tree and also caught
`src/otampy/device/tests/test_ota_facade.py`. That is a host-side pytest
suite that is never deployed, so the test now iterates `deploy.LIB_DIR` and
`DEVICE_ROOT/examples` — deploy's own constants, so the test's idea of "what
ships" cannot drift from deploy's.

**Step 2 (2026-09-13).** `_compact_tokens` walks the token stream and, on
`FSTRING_START`, re-emits the whole run through the matching `FSTRING_END` as
one `STRING` token sliced verbatim out of the original text. Compat mode then
sees a single opaque token and has nothing to pad inside. Depth counting
handles PEP 701 nested f-strings.

Row-to-character offsets are built by splitting on `"\n"` only, deliberately
**not** `str.splitlines`, which also breaks on form feed / `\x85` / ` `.
The tokenizer reads through `io.StringIO(text).readline`, which splits on
`"\n"` alone, so anything else would desync the offsets against the very
sources most likely to contain odd bytes.

Evidence after the fix, over the 20 deployed device sources:

```
20 files  111985 -> 86613 bytes  (22.7% smaller)
minified manager.py: helper .write (f" machine.RTC().datetime({time_tuple!r})\n")
```

The conversion is verbatim, and the ~21% size win reported in the TODO is
intact (22.7% measured here). `python3 .agents/scripts/pre_flight_check.py`
exits 0.

**HIL proof (2026-09-13).** Scaffolded a fresh example project (`otampy init`)
and ran `otampy deploy --port /dev/ttyACM0 --minify` (erase + minified deploy)
against a blank Raspberry Pi Pico W (RP2040, MicroPython 1.28.0) direct over
USB. Deploy completed without error — the first proof point, since the
previous bug failed exactly here (a `SyntaxError` on the minified
`manager.py`, surfaced only on the device's next boot).

`otampy ping` then failed with a handshake timeout. One read-only `mpremote
connect ... resume exec` check (immediately followed by the mandatory hard
`mpremote connect ... reset`, then left alone to settle) showed why: the
board is alive and responsive, and

```
>>> import otampy.manager as m; print('manager imported OK:', m)
manager imported OK: <module 'otampy.manager' from '/lib/otampy/manager.py'>
```

confirms the minified `manager.py` — containing the fixed
`f" machine.RTC().datetime({time_tuple!r})\n"` line — imports cleanly under
the real MicroPython compiler, not just `mpy-cross`. `ping`'s failure is
unrelated to this fix: the scaffold's default `configota.py` puts OTA on
UART1 pins 4/5, not the USB-CDC port `/dev/ttyACM0` exposes, so the CLI and
device were never on the same wire. Nothing was wired for a full
`ping`/`sr`/`RTC_STAGE` round trip on this ad hoc bench setup.

Considered sufficient: the regression this task fixes is a compile-time
failure, and real MicroPython accepting the minified source is direct proof
of that. The `_stage_rtc_update` runtime behaviour (the helper file's content
and execution) is already covered host-side by
`test_minify_python_source_preserves_fstring_conversions`, which `exec()`s
the minified output and asserts on the result.
