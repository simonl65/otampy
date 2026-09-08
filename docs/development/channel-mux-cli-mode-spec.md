# Channel-mux CLI mode — spec

**TODO item:** `[ ] 2. CLI mux mode. --mux flag + otampy.toml key; wire the codec into all Urst(ser) sites (cli.py:973, 1422, 1829, 2205). otampy ping succeeds against a mux-mode device; direct mode unchanged.` (sub-task 2 of "Channel-mux mode: opt-in on both ends" in `TODO.md`)  
**Status:** approved  
**Components:** `src/otampy/` (host CLI package)  
**Dev log:** `docs/development/channel-mux-cli-mode-log.md` (created by `/sl-build`)  

This is **sub-task 2** of 3. Sub-task 1 (frame contract + host codec) is on
`develop` — `src/otampy/channel.py` has `ChannelCodec` + `ChannelSerial`,
`docs/protocol.md` §1.3 documents the wire format. Sub-task 3 (scaffold
direct-by-default + separate mux example set) follows this.

---

## Background

`src/otampy/channel.py` already provides `ChannelSerial(ser)` — a synchronous
serial-like adapter that wraps a raw `serial.Serial`, applies the channel-mux
outer frame on write, strips it on read, and surfaces only channel 0 to URST.
It is fully tested (`tests/test_channel.py`, `tests/test_channel_conformance.py`)
including a real `Urst` PING→PONG round-trip through the frame.

Nothing in `cli.py` uses it. The CLI builds `Urst(serial.Serial(...))` on the
raw port at four sites, so `otampy` against a mux-mode device (e.g.
diff-drive-robot's Pico running `SerialMux`) times out on every command. This
sub-task adds the opt-in switch that routes those four sites through
`ChannelSerial`.

The four `Urst(ser)` construction sites (line numbers drift — identify by
function):

| # | Function | What it does |
| --- | --- | --- |
| 1 | `_query` — "create new transport with retry logic" loop | every `ping`/`ls`/`cat`/`rm`/`rb`/`sr`/`mem`/`rtc` command |
| 2 | `_recursive_rm_with_connection` | `rm` of a directory (persistent connection) |
| 3 | `cp` command body | runtime file copy |
| 4 | `upd` command — "wait for device READY" loop | OTA update session |

All four share an identical block: open `serial.Serial`, set `dtr`/`rts` False
(guarded), `reset_input_buffer()` + `reset_output_buffer()`, `Urst(ser)`, then
`transport.protocol._recv_queue.clear()` (guarded). That duplication is
extracted first (step 2), then the mux wrapping goes in one place (step 3).

`deploy` (`deploy.py`) does **not** use `Urst`, `_query` or `ctx.obj` — the
`deploy` command delegates entirely to `deploy.deploy(args)` — so "deploy stays
direct-mode only" needs no code: it never builds a transport, even with `mux`
saved globally.

`upd`'s `UPDATE_REQUEST` goes through `_send_command` → `_query` (site 1); its
reconnect for the `READY` broadcast is site 4. Every other command routes
through `_query` or `_send_command`. Confirmed: only four `Urst(` construction
sites exist.

## Goal

After this ships: `otampy --mux <command>` (or a saved `mux` setting, or
`OTAMPY_MUX=1`) makes every device-facing command speak the channel-mux outer
frame, so `otampy --mux ping` returns `PONG` from a mux-mode device. With no
flag and no saved setting the CLI behaves exactly as it does today — direct
URST on the raw port, byte-for-byte unchanged. The switch is global (a property
of the link, like `--port`), persists per-project or globally like the default
port, and has an `otampy mux` management command mirroring `otampy log-level`.

## In scope

- `get_mux_enabled()` / `set_mux_enabled()` with the same precedence chain as
  `default_port`: `OTAMPY_MUX` env → session config → project config → global
  config → default `False`.
- A global `--mux / --no-mux` tri-state option on the `cli` group (`None` =
  use the resolved setting; `True`/`False` = override for this one command),
  resolved into `ctx.obj["mux"]`.
- `_open_transport(ctx) -> (serial.Serial, Urst)` helper — the extracted
  open+configure+wrap+clear-queue block, used by all four sites.
- Mux wiring inside `_open_transport`: when `ctx.obj["mux"]` is true, wrap the
  raw `ser` in `ChannelSerial`, run the buffer resets on the wrapper, and hand
  the wrapper to `Urst`. `dtr`/`rts` still set on the raw `ser` first.
- `otampy mux` command: `--show` / `--enable` / `--disable` / `--clear`, plus an
  interactive permanent/session/cancel prompt (mirrors `log_level_cmd`).
- Docs: `docs/protocol.md` §1.3 (host-enable paragraph + settings row),
  `README.md` (env-var list + one line), `docs/deployment.md` (persistence note).

## Out of scope

- **Configurable channel ids and `min_tx_gap_ms` on the host.** `ChannelCodec`
  already accepts `ota_channel` / `app_channel` args and `ChannelSerial` accepts
  `min_tx_gap_ms`, all defaulting to the device defaults (`0` / `1` / `0` ms).
  No known deployment changes the device defaults, so exposing these as CLI
  settings is deferred to a follow-up TODO item — noted in "Risks". Adding them
  later is additive (more `get_*`/`set_*` + flags), not a rework.
- **Changing the example scaffold or `otampy init`** — sub-task 3.
- **Any change to `src/otampy/channel.py` or `device/lib/otampy/mux.py`** — the
  codec is done and the device side is unchanged.
- **A distinct `otampy.toml` file.** The TODO's "otampy.toml key" predates
  checking: `otampy` has no such file. Config lives in
  `~/.config/otampy/config.json` (project/global sections) plus session config
  in the temp dir — this task uses that existing mechanism, same as
  `default_port`.
- **Making a one-sided mismatch anything other than a timeout.** Per the
  signed-off protocol decision it stays a silent command timeout; the CLI
  already reports that as `Timeout waiting for response to command: …`.

## Protocol decision

Already settled and signed off (2026-09-08, in `TODO.md` and
`docs/development/channel-mux-opt-in-spec.md`). This sub-task adds **no wire
change**: the outer frame is exactly what sub-task 1 documented and what the
device emits today. `ChannelCodec` / `ChannelSerial` are the host implementation
of that already-agreed format. No new sign-off is required — there is nothing
new on the wire to sign.

- **Existing OTAmpy/URST command reusable?** N/A — this is transport wiring, not
  an application command.
- **Wire format change?** No.
- **Signed off:** 2026-09-08 by Simon (covers the whole task).

## Data and contracts

### `mux` setting — **load-bearing** (sub-task 3's `otampy init` will reference it)

| Aspect | Value |
| --- | --- |
| Config key | `"mux"` in the session / project / global config dicts (bool) |
| Env override | `OTAMPY_MUX` — truthy: `1` `true` `yes` `on` (case-insensitive); falsey: `0` `false` `no` `off` `""`; anything else → `ClickException` |
| Default | `False` (direct mode) |
| Precedence | env → session → project → global → default (identical to `get_default_port`) |
| CLI flag | `--mux / --no-mux` on the `cli` group, `default=None`; `None` → resolved setting, else the flag value wins for that command only |
| Resolved location | `ctx.obj["mux"]: bool` |

No entry in a `docs/configuration.md` (this repo has none); documented in
`docs/protocol.md` §1.3, `README.md` and `docs/deployment.md` instead.

### `_open_transport(ctx, *, clear_queue: bool = True) -> tuple[serial.Serial, "Urst"]` — **load-bearing**

- Reads `ctx.obj["port"]` / `ctx.obj["baud"]`; raises the existing
  `"Error: Missing serial port. Specify with --port or -p option."`
  `ClickException` when no port.
- Opens `serial.Serial(port, baudrate=baud, timeout=<serial_timeout_seconds>)`.
- Sets `ser.dtr = False`, `ser.rts = False` inside a bare `except Exception:
  pass` (matches current behaviour on ports without modem lines).
- If `ctx.obj.get("mux")`: `port_obj = ChannelSerial(ser)`, else `port_obj = ser`.
- `port_obj.reset_input_buffer()`, `port_obj.reset_output_buffer()`.
- `transport = Urst(port_obj)`.
- If `clear_queue`: `try: transport.protocol._recv_queue.clear()` /
  `except Exception: pass`.
- Returns `(ser, transport)` — callers keep closing the **raw** `ser`
  (`ChannelSerial.close()` also delegates, but callers already hold `ser`).

`clear_queue` exists because **site 4 (`upd` READY loop) does not currently
clear the queue** — sites 1/2/3 do. Step 2 must be a true no-op, so site 4
passes `clear_queue=False`. A follow-up may decide the clear is safe/desirable
there and drop the argument; that is a behaviour change and not this task's.

Constants: the timeout already comes from `get_config_value("serial_timeout_seconds")`;
no new numeric constants. The `OTAMPY_MUX` truthy/falsey token sets live as
module-level frozensets next to `CONFIG_SETTINGS` (`_MUX_TRUE_TOKENS`,
`_MUX_FALSE_TOKENS`).

## Build steps

- [x] **1. `mux` setting resolution + `--mux/--no-mux` global flag**
  - What changes: `cli.py` — add `get_mux_enabled()`, `set_mux_enabled(enabled,
    session=False)` (mirror `get_default_port`/`set_default_port`), the
    `_MUX_TRUE_TOKENS` / `_MUX_FALSE_TOKENS` frozensets, a `--mux/--no-mux`
    option on the `cli` group with `default=None`, and
    `ctx.obj["mux"] = mux if mux is not None else get_mux_enabled()`. Nothing
    consumes `ctx.obj["mux"]` yet.
  - Test: `tests/test_mux_cli.py::TestMuxSetting` — precedence (env beats
    session beats project beats global beats default-`False`); `OTAMPY_MUX`
    token parsing incl. an invalid token raising; `--mux` / `--no-mux` override
    the saved setting for one command; `set_mux_enabled` round-trips through the
    project and session config files.
  - Done when: `uv run pytest -q tests/test_mux_cli.py::TestMuxSetting` passes
    and `otampy --mux ping` / `otampy --no-mux ping` parse (still direct — no
    wiring yet).

- [x] **2. Extract `_open_transport(ctx)` — pure refactor**
  - What changes: `cli.py` — add `_open_transport(ctx)` per "Data and
    contracts" (direct mode only in this step; `ctx.obj["mux"]` not read yet).
    Replace the duplicated open/configure/`Urst`/clear-queue block at all four
    sites with `ser, transport = _open_transport(ctx)` — site 4 passes
    `clear_queue=False` to stay byte-identical. Keep every surrounding line
    (retry loop, `ser.close()` in `finally`, the READY loop's `if ser is None:`
    guard) exactly as is.
  - Test: none new — the existing `tests/test_cli.py` suite is the regression
    guard. Its assertions (`mock_serial.assert_called_once_with("/dev/ttyFake",
    baudrate=57600, timeout=2.0)`, `mock_device_instance.send.assert_called_once_with(...)`,
    the 3-retry count test, etc.) must pass with **zero edits**.
  - Done when: `uv run pytest -q` is green with no changes to any existing test.

- [x] **3. Wire mux into `_open_transport`**
  - What changes: `cli.py` — `from otampy.channel import ChannelSerial` (module
    top). In `_open_transport`, when `ctx.obj.get("mux")` is true: wrap `ser` in
    `ChannelSerial` after setting `dtr`/`rts`, run the buffer resets and `Urst`
    on the wrapper. Direct path unchanged.
  - Test: `tests/test_mux_cli.py::TestMuxWiring` —
    (a) `otampy --mux ping` → the object passed to the patched `urst.Urst` is a
    `ChannelSerial` whose `_ser is serial.Serial.return_value`;
    (b) `otampy ping` (no mux) → `urst.Urst` gets the raw mock serial;
    (c) `otampy --mux ping` completes with `Success: Received PONG` — patch
    `serial.Serial` to return the host end of `_cross_pipe` (from
    `test_channel.py`), run a background real-`Urst` mux device on a thread
    (the `test_urst_roundtrip` harness), invoke `ping` via `CliRunner`. This is
    the one integration-level test; the frame correctness itself is already
    covered in `test_channel.py`.
    (d) `otampy --mux ping` against a fake serial that replies with *unframed*
    (direct) bytes → exits non-zero with `Timeout waiting for response` and no
    traceback (one-sided-mismatch behaviour).
  - Done when: `uv run pytest -q tests/test_mux_cli.py` passes and full
    `uv run pytest -q` is green.

- [x] **4. `otampy mux` management command**
  - What changes: `cli.py` — `@cli.command(name="mux")` `mux_cmd(show, enable,
    disable, clear)` modelled on `log_level_cmd`: `--show` prints the resolved
    value and its source; `--enable`/`--disable` persist to project config and
    clear the session override; `--clear` removes project + session + global;
    bare invocation prints current state and prompts
    `(p=permanent, s=session, c=cancel)`.
  - Test: `tests/test_mux_cli.py::TestMuxCommand` — `--show` with nothing set
    reports `direct` (default); `--enable` then `--show` reports `mux` from
    project config; `--disable`; `--clear`; `OTAMPY_MUX=1` makes `--show` report
    the env source.
  - Done when: `uv run pytest -q tests/test_mux_cli.py::TestMuxCommand` passes.

- [x] **5. Documentation**
  - What changes:
    - `docs/protocol.md` §1.3 — new short "Enabling mux mode on the host"
      paragraph (the `--mux` flag, `OTAMPY_MUX`, `otampy mux`, default direct)
      and a settings-table row; reinforce the existing "enable both ends" note.
    - `README.md` — add `OTAMPY_MUX` to the env-var list and one line to the
      port/config bullet.
    - `docs/deployment.md` — one sentence next to the `--log-level` persistence
      paragraph noting `--mux` persists the same way; add `otampy --mux ping` to
      the Verification example for a shared-UART device.
  - Test: none — documentation.
  - Done when: the three sections exist and Simon has read them at the gate.

- [x] **Repair F-01 — `ChannelSerial._pump` / `in_waiting` must not block**
  - What changes: `src/otampy/channel.py` `_pump` reads only
    `self._ser.in_waiting` bytes and does not read at all when that is 0 (no
    blocking `read(1)` fallback). `ChannelSerial.read` / `in_waiting` then return
    promptly (`b""` / current count) and let URST's own `read_frame` poll loop
    do the waiting, matching how a real non-blocking `serial.in_waiting`
    behaves.
  - Test: `tests/test_channel.py::TestChannelSerial` — a fake serial whose
    `read()` records calls / would block; assert `in_waiting` and `read` do not
    call `self._ser.read` when `in_waiting == 0`, and still decode normally when
    data is present.
  - Done when: `uv run pytest -q tests/test_channel.py` passes and the new test
    proves no read on an empty port; `docs/development/findings.md` F-01 →
    `fixed`.

- [x] **Repair F-03 — malformed `OTAMPY_MUX` must not lock out `otampy mux`**
  - What changes: `get_mux_enabled` warns + falls through instead of raising on
    an unrecognised token (`_parse_mux_token` / `_mux_from_config` helpers);
    `_mux_state` notes the ignored env value.
  - Test: `tests/test_mux_cli.py` — `get_mux_enabled` returns the config value
    with a stderr warning; `otampy mux --show` exits 0 and reports it.
  - Done when: `uv run pytest -q tests/test_mux_cli.py` passes; `OTAMPY_MUX=x
    otampy mux --clear` exits 0; F-03 → `fixed`.

- [x] **Repair F-02 — keep `ChannelSerial` import lazy**
  - What changes: move `from .channel import ChannelSerial` from `cli.py` module
    scope into `_open_transport`.
  - Test: `tests/test_mux_cli.py::TestLazyImport` — subprocess `import
    otampy.cli` leaves `urst` / `serial` out of `sys.modules`.
  - Done when: that test passes; F-02 → `fixed`.

## Verification

- **Host:** `python3 .agents/scripts/pre_flight_check.py` (mirrors CI: `ruff
  check`, `ruff format`, full `pytest`). Per-step: `uv run pytest -q
  tests/test_mux_cli.py` and, for step 2, the full `tests/test_cli.py`.
- **Hardware:** against diff-drive-robot's Pico (which runs `SerialMux` — the
  device that motivated this task). With the diff-drive-robot **gateway stopped**
  (it owns `/dev/ttyUSB0` and channel 0 otherwise) and **channel 1 quiet**:
  - `otampy --port /dev/ttyUSB0 ping` → times out (baseline: mismatch).
  - `otampy --mux --port /dev/ttyUSB0 ping` → `Success: Received PONG`.
  - `otampy --port /dev/ttyUSB0 ping` against a **direct** device (a Pico
    flashed with a direct-mode `main.py`) still works unchanged.
  Restart the gateway afterwards. This is real end-to-end evidence; the CLI
  mock tests are not a substitute for it.
- **Manual:** `otampy mux --enable`, then `otampy ping` (no `--mux`) uses the
  saved setting; `otampy mux --show`; `otampy --no-mux ping` overrides it.

## Risks and open questions

- **Is on/off enough for sub-task 2, or do channel ids / `min_tx_gap_ms` need
  CLI exposure now?** Recommendation: on/off only. Every known mux user runs the
  device defaults (`0` / `1` / `0` ms). Deferred to a follow-up TODO; adding the
  extra settings later is purely additive. **Confirm at the review gate.**
- **`upd` (site 4) and the post-`UPDATE_REQUEST` reboot.** After `UPDATE_REQUEST`
  the device reboots into `boot.py`; for a mux device, `boot.py` must also run
  `SerialMux` for `--mux upd` to complete. Today's scaffold wires the mux in
  both `boot.py` and `main.py`, so this holds. Sub-task 3 makes the mux a
  separate example set where `boot.py` is *also* mux — still consistent. Flag
  in the sub-task 3 spec that the shared-UART `boot.py` must keep the mux.
- **Retry isolation.** `_query`'s retry loop opens a fresh `serial.Serial` (and
  therefore a fresh `ChannelSerial` + `ChannelCodec`) per attempt, so a
  half-decoded outer frame from a failed attempt cannot leak into the next —
  handled by construction, no extra `reset()` call needed. Noted so it is not
  "fixed" later.
- **`reset_input_buffer` mid-connection.** Some sites clear buffers only at
  open. `_open_transport` runs the reset on the wrapper (mux) or raw port
  (direct) at construction; no site calls `reset_input_buffer` again mid-session,
  so nothing else moves onto the wrapper. If a future change adds a mid-session
  clear it must target the wrapper.
- **Auth envelope.** `_command_signer().wrap(command)` operates above URST on
  the command bytes; the mux frame is below URST. Independent — a signed command
  in mux mode just means signed bytes inside the URST frame inside the outer
  frame. No interaction, but worth a one-line note in the log.
- **`ChannelSerial` has no `dtr`/`rts`.** The CLI sets them on the raw `ser`
  before wrapping (step 3 keeps that order). No site sets `dtr`/`rts` on the
  transport object after construction — verified against the four sites. If that
  changes, `ChannelSerial` needs pass-through properties.
- **`from urst import Urst` is monkeypatched in `tests/test_cli.py`** via
  `mock.patch("urst.Urst")`. `_open_transport`'s late `from urst import Urst`
  still picks up the patch. New `tests/test_mux_cli.py` follows the same
  pattern; the real-`Urst` round-trip case uses `from urst.core_handler import
  Urst` (unshadowed) exactly as `tests/test_channel.py` does.

## Notes for the build

- Click idiom: `@click.option("--mux/--no-mux", "mux", default=None,
  help=...)` on the `cli` group — a tri-state boolean. As a group option it must
  precede the subcommand (`otampy --mux ping`), exactly like `--port` /
  `--log-level`.
- `get_mux_enabled()` is called from the `cli` group body (not as a Click
  `default=` callable), so raising `ClickException` on an invalid `OTAMPY_MUX`
  token surfaces cleanly.
- Mirror `get_default_port` / `set_default_port` / `log_level_cmd` closely —
  same config-file helpers (`_read_json`, `_write_project_config`,
  `_write_global_config`, `_session_config_path`), same session-vs-permanent
  prompt wording. DRY: do not invent a parallel config path.
- Step 2 is a pure refactor: if any existing test needs editing, the refactor
  changed behaviour — stop and fix the refactor, not the test.
- `_open_transport` returns the raw `ser` (not the wrapper) so the many
  `ser.close()` / `ser = None` call sites keep working untouched.
- The `ChannelSerial` round-trip and conformance tests already live in
  `tests/test_channel.py` / `tests/test_channel_conformance.py`; reuse their
  `outer_frame` helper and `_cross_pipe` rather than rebuilding fakes.
- Dev log to update at the end: tick `TODO.md` sub-task 2, and record the
  channel-id/`min_tx_gap_ms` deferral decision for whoever picks up the
  follow-up.
- `docs/architecture.md`'s Integration Guide still shows pre-`6f2bd1b`
  direct-mode examples — that is sub-task 3's fix, not this one. Do not touch it
  here.
