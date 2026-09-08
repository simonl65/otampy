# Channel-mux CLI mode — dev log

Spec: `docs/development/channel-mux-cli-mode-spec.md` (sub-task 2 of 3).
Branch: `feature/channel-mux-cli-mode`.

## Context at start

- Sub-task 1 (`ChannelCodec` + `ChannelSerial` + `docs/protocol.md` §1.3) is on
  `develop` (merged commit `8a2ea04`).
- Config mechanism: `~/.config/otampy/config.json` with `projects`/`global`
  sections + a per-session JSON in the temp dir. `get_default_port` /
  `set_default_port` / `log_level_cmd` are the templates to mirror.
- 4 `Urst(` construction sites in `cli.py`, all sharing one open/configure/wrap
  block; `deploy.py` builds no transport.
- Baseline: `uv run pytest -q` → 481 passed.
- **No hardware for host-only steps.** End-to-end HIL (`otampy --mux --port
  /dev/ttyUSB0 ping` against diff-drive-robot's Pico, gateway stopped, channel 1
  quiet) is the acceptance evidence and is Simon's to run.
- No findings ledger.

## Progress

### Step 1 — `mux` setting resolution + `--mux/--no-mux` global flag — DONE

- `cli.py`: `MUX_ENV` / `_MUX_TRUE_TOKENS` / `_MUX_FALSE_TOKENS` /
  `_MUX_TOKEN_HELP` next to `CONFIG_SETTINGS`; `get_mux_enabled()` /
  `set_mux_enabled()` mirroring `get_default_port` / `set_default_port`
  (env → session → project → global → `False`); `--mux/--no-mux` tri-state
  option on the `cli` group; `ctx.obj["mux"] = mux if mux is not None else
  get_mux_enabled()`. Nothing reads `ctx.obj["mux"]` yet.
- `tests/test_mux_cli.py::TestMuxSetting` (16 via parametrize) + `TestMuxFlag`
  (2). Fails first with `ImportError: cannot import name 'get_mux_enabled'`.
- Lint: pre-flight's `ruff check` flagged `SIM117` (nested `with`) in the new
  test only — fixed by combining the context managers. No other findings.
- Gate: `pre_flight_check.py` exit 0; `uv run pytest -q tests/test_mux_cli.py`
  → 17 passed.

### Step 2 — extract `_open_transport(ctx)` (pure refactor)
(next)
