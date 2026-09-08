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
