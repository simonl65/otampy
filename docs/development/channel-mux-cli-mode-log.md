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

### Step 2 — extract `_open_transport(ctx)` (pure refactor) — DONE

- New `_open_transport(ctx, *, clear_queue=True) -> (serial.Serial, Urst)`
  just above `_query`. Holds the open + DTR/RTS + buffer-reset + `Urst` +
  queue-clear block. `import serial` added to the `TYPE_CHECKING` block for the
  return annotation (`from __future__ import annotations` keeps it unevaluated).
- All four sites now call it: `_query` retry loop, `_recursive_rm_with_connection`,
  `copy_files`, `_update_files` READY loop. Site 4 passes `clear_queue=False` —
  it never cleared the queue before, and step 2 must be a true no-op.
- Each site's early `port = …; baud = …; if not port:` guard collapsed to
  `if not ctx.obj.get("port"):` (the same `ClickException`, same message) since
  `port`/`baud`/`serial_timeout` are now only used inside `_open_transport`.
- Net: `cli.py` +57 / −84.
- **Zero test edits.** `uv run pytest -q tests/test_cli.py tests/test_mux_cli.py`
  → 132 passed. Full `pre_flight_check.py` exit 0. The existing `test_cli.py`
  assertions (`mock_serial.assert_called_once_with("/dev/ttyFake",
  baudrate=57600, timeout=2.0)`, the 3-retry count, `send.assert_called_once_with`)
  all still pass unchanged — the refactor is behaviour-preserving.

### Step 3 — wire mux into `_open_transport` — DONE

- `cli.py`: module-top `from .channel import ChannelSerial`;
  `port_obj = ChannelSerial(ser) if ctx.obj.get("mux") else ser` in
  `_open_transport` (5-line change). DTR/RTS still set on the raw `ser` before
  the wrap.
- `tests/test_mux_cli.py::TestMuxWiring` (4): mux-on → `Urst` gets a
  `ChannelSerial` wrapping the mock serial; mux-off → raw serial; **end-to-end**
  `--mux ping` → `Received PONG` via a background real-`Urst` mux device over
  `test_channel._cross_pipe`; one-sided mismatch (`--mux` host, unframed device)
  → clean non-zero exit, no traceback.
- **Gotcha:** the device test-suite conftest swaps `sys.modules["urst"]` for a
  fake `Urst`. The two integration tests must `mock.patch("urst.Urst",
  real_Urst)` (real class from `urst.core_handler`) or they silently exercise
  the fake and time out. Without device tests collected they pass either way;
  with them collected the patch is required.
- Gate: `pre_flight_check.py` exit 0; `uv run pytest -q` → 502 passed.

### Step 4 — `otampy mux` management command — DONE

- `cli.py`: `_mux_state() -> (bool, str)` (value + source for display) and
  `@cli.command("mux")` `mux_cmd(show, enable, disable, clear)` modelled on
  `log_level_cmd`. `--show` prints e.g. `Channel-mux: direct mode (from
  default)` / `mux mode (from project config)` / `... (from env OTAMPY_MUX)`;
  `--enable`/`--disable` persist to project config + clear the session
  override; `--clear` removes session + project + global; bare invocation
  confirms the flip then prompts `(p=permanent, s=session, c=cancel)`.
- `tests/test_mux_cli.py::TestMuxCommand` (6): default→direct, enable→project,
  disable, clear, env source reported, interactive session choice.
- Gate: `pre_flight_check.py` exit 0; full `uv run pytest -q` → 508 passed.
- Manual: `uv run otampy mux --show` → `Channel-mux: direct mode (from
  default)`; `otampy --help` and `otampy mux --help` list it.

### Step 5 — documentation
(next)
