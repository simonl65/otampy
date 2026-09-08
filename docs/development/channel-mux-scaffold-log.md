# Channel-mux scaffold — dev log

Narrative record for TODO sub-task 3 (spec:
`docs/development/channel-mux-scaffold-spec.md`). Sub-tasks 1 and 2 (host codec,
CLI `--mux` mode) are already merged on `develop`.

## Step 1 — split the scaffold: direct default + `shared-uart/` set — DONE

- `examples/boot.py` + `main.py` restored to `6f2bd1b~1` (direct mode), via
  `git show`. No non-mux commits touched either since `6f2bd1b`, so this is a
  clean revert — `OTA(uart, …)`, `uart.read()` in `do_application_stuff`.
- Current (mux) `boot.py`/`main.py` moved verbatim to `examples/shared-uart/`
  via `git mv`; added `examples/shared-uart/configota.example.py` (copy of the
  flat template + a header explaining mux mode and a `min_tx_gap_ms` hint).
- `pyproject.toml`: package-data glob += `device/examples/shared-uart/*.py`.
- `tests/test_examples.py` (new): `ast.parse` all 5 example files; default set
  has no `SerialMux`/`mux.`; shared-uart set has `SerialMux` + `mux.ota_port`;
  shared-uart set is complete.
- Gate: `pre_flight_check.py` exit 0 (ruff reflowed the new test only).

## Step 2 — `otampy init --mux` — DONE

- `cli.py init`: new `--mux/--no-mux` flag (default `None`). When unset and
  stdin is a terminal, `click.confirm("Shared UART (channel-mux) mode?")`;
  otherwise direct. Added `_stdin_is_interactive()` helper (also the test seam —
  patching `sys.stdin` directly collides with `CliRunner`'s stdin isolation).
- When mux is chosen, the package resource path gains a `shared-uart` segment;
  same three filenames, `configota.example.py` still lands as `configota.py`.
  Prints `Scaffold: direct` / `shared-uart (channel-mux)`.
- `tests/test_cli.py`: `_run_init` helper + 4 tests — default is direct,
  `--mux` yields `SerialMux`, `--no-mux` beats a TTY, interactive `y` prompt
  yields `SerialMux`.
- Wheel check: `uv build --wheel` → `otampy/device/examples/shared-uart/{boot,
  main,configota.example}.py` present in the archive.
- Gate: `pre_flight_check.py` exit 0.

## Step 3 — docs + CHANGELOG — DONE

- `README.md`: shared-UART feature bullet + tree line + `init` section (direct
  default, `--mux` for shared) + command table row.
- `docs/architecture.md`: new Integration Guide §4 "Sharing the UART with
  application code" pointing at `otampy init --mux`, §1.1/§1.3.
- `docs/protocol.md` §1.1 + §1.3: name `otampy init --mux` / the default direct
  scaffold (wording was already ahead of the code — now true).
- `src/otampy/device/README.md`: two example sets, template-drift note.
- `CHANGELOG.md`: new `## [Unreleased]` covering the whole feature (wire
  contract, host codec, CLI opt-in, scaffolds) + Changed + Compatibility
  (recovery path for a `6f2bd1b` mux device on a plain CLI).
- `TODO.md`: "Channel-mux mode: opt-in on both ends" removed (all 3 sub-tasks
  done).
- Gate: `pre_flight_check.py` exit 0.
