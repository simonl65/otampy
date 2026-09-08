# Findings ledger

Durable record of code-review findings. IDs are permanent and never reused.
See `~/.claude/skills/sl-findings` for the process.

Gate rule: an **open** or **fixed** P0/P1 blocks a merge. P2/P3 do not.

---

## Open / fixed

### F-06 — an interrupted `boot.py` commit strands the device: `repair()` lives in the file that got deleted

- **Severity:** P0
- **Status:** open
- **Area:** `src/otampy/device/lib/otampy/` (`boot.run` / `restore` design;
  the shipped `main.py` scaffold)
- **Found:** 2026-09-08, HIL fault-injection of
  `feature/failsafe-update-retain-previous` (doctored `restore.py` with a 25 s
  wait loop on the last commit pair; Simon pulled power in the window).
- **Evidence:** `otampy upd main.py boot.py` was interrupted mid-commit, after
  `main.py` had fully committed and `boot.py` had been renamed to
  `boot.py.bck` but its `.ota` was not yet renamed into place. On the next
  boot, `otampy -p /dev/ttyUSB0 ls /` showed: **`boot.py` absent**,
  `boot.py.bck` + `boot.py.ota` present, `otampy-update.journal` =
  `committing` / `/main.py` / `/boot.py`, `update_requested.flag` still set.
  `otampy ping` returned `PONG` (the newly-committed `main.py` runs), but the
  `committing` state persisted across reboots — no self-repair.
- **Root cause:** `restore.repair()` is only ever invoked from `boot.run()`,
  i.e. from `boot.py`. `commit()` renames each target out to `<target>.bck`
  before renaming the staged copy in, so an interrupt while `boot.py` is the
  current pair leaves `boot.py` absent. MicroPython then boots straight to
  `main.py`, `boot.run()` never executes, and the journal/flag/`.bck` state is
  never resolved. The device is stuck on a mixed tree (new `main.py`, no
  `boot.py`) with no remote recovery path — exactly the "never destroy the only
  remote recovery path" invariant the Fail-safe Updates task exists to enforce.
- **Impact:** A normal-path power loss during any update whose set includes
  `boot.py` (every `otampy upd` with no args sends `boot.py`, `main.py`,
  `configota.py`) can strand a field device. Runtime commands still work while
  `main.py` runs, so recovery is possible over the radio via `otampy cp` — but
  only by luck (if `main.py` committed or was untouched); if the interrupt
  caught `main.py` instead, or `main.py` also fails, the device needs USB.
- **Blocks:** merge (P0). HIL cannot proceed past this.
- **Suggested fix (needs a design decision — see dev log 1-3-1):**
  - **A (recommended):** the shipped `main.py` scaffold also runs
    `restore.repair()` once at startup (or a new `OTA(...).recover()`). Since
    `commit()` touches one file at a time, at any interrupt point at most one of
    `boot.py`/`main.py` is absent, so the survivor heals the set. Smallest
    change; scaffold contract gains one line; a custom `main.py` must include it.
  - **B:** special-case `boot.py` in `commit()` to copy-into-place (never leave
    `boot.py` absent). Keeps recovery in `boot.py`; risks a truncated `boot.py`
    on a crash mid-write.
  - **C:** freeze a minimal recovery `_boot.py` (runs before `boot.py`) into the
    deployed image that calls `repair()` and chains on. Heaviest; needs a
    manifest/freeze change at deploy time.

### F-04 — the orphan sweep deletes freshly-committed `.bck` files on the next boot

- **Severity:** P1
- **Status:** fixed
- **Area:** `src/otampy/device/lib/otampy/boot.py` (`_cleanup_orphaned_ota`)
- **Found:** 2026-09-08 during HIL of `feature/failsafe-update-retain-previous` (Simon, Phase 2)
- **Evidence:** After `otampy upd main.py` and the device's post-commit reboot,
  `otampy ls /` showed the journal (`0` / `/main.py` / `/_otampy_set_rtc.py`)
  but **no `main.py.bck`**. `ota.log` on the device:
  `Cleanup started... / Removing orphaned file: /./main.py.bck / Cleanup complete`.
  `commit()` creates `/main.py.bck` correctly; on the next boot
  `boot.run()` → `_cleanup_orphaned_ota(core, path=".")` builds the candidate as
  `_resolve_path("./main.py.bck")`, which on MicroPython is `"/" + "./main.py.bck"`
  = `"/./main.py.bck"`. The journal's kept-set is `{"/main.py.bck"}`, so
  `"/./main.py.bck" not in kept_backups` is true and the backup is removed.
  littlefs resolves `/./` transparently, so the delete succeeds.
- **Impact:** Retain-previous's core guarantee — the previous version physically
  survives an update — is **void on hardware**. Every committed `.bck` is
  deleted on the first reboot after the commit. `repair()` after a real power
  loss then finds no `.bck` to restore from. The unit test
  `test_boot_removes_orphan_bck_but_keeps_journalled_one` passed because it
  patches `_resolve_path` with a mock and CPython's `pathlib`/string handling
  collapses the `./` that bare concatenation on the device does not.
- **Suggested fix:** start the `_cleanup_orphaned_ota` traversal from `"/"`
  instead of `"."`, so every `item_path` is built in the same `/dir/file` form
  the journal stores (`_resolve_path("/x")` is identity on both host and
  device). Add a regression test that uses the real `core._resolve_path` (not a
  mock) so the `.`-vs-`/` mismatch is actually exercised.
- **Resolution:** 2026-09-08, `feature/failsafe-update-retain-previous` step 9.
  Traversal root left at `"."` (flipping to `"/"` made the no-flag boot tests
  that don't mock `_os.listdir` walk the real filesystem — one hung). Instead,
  new `boot._canonical(path)` collapses `/./`, strips a leading `./`, and forces
  a leading `/`; it is applied to both the journal-derived `kept_backups` set
  and each `.bck` candidate before the membership test. `resolved_item` is still
  passed unchanged to `_os.remove`. Test:
  `test_ota_boot.py::test_cleanup_keeps_journalled_bck_with_real_resolve_path`
  (no `_resolve_path` mock — exercises the real `.`-vs-`/` mismatch).
- **Awaiting:** re-review (`/sl-findings review`) and HIL re-run (Phase 2 must
  show `main.py.bck` present after the post-commit reboot).

### F-05 — `commit()` retains the transient RTC helper; `repair()` then resurrects it

- **Severity:** P2
- **Status:** fixed
- **Area:** `src/otampy/device/lib/otampy/boot.py` (`_run_default_update_loop` /
  `restore.commit`)
- **Found:** 2026-09-08 during HIL of `feature/failsafe-update-retain-previous`
  (journal on device listed `/_otampy_set_rtc.py`)
- **Evidence:** `otampy upd` appends the one-shot RTC helper
  `_otampy_set_rtc.py` to the transfer manifest unless `--no-rtc`
  (`src/otampy/cli.py:2235`). It arrives via `FILE_START`/`CHUNK`/`FILE_END`
  like any file, so `commit()` backs it up to `_otampy_set_rtc.py.bck` and adds
  `/_otampy_set_rtc.py` to the journal. The helper self-deletes on the next
  boot (`deploy.rtc_helper_content()` ends `finally: os.remove(...)`). Once F-04
  is fixed and the `.bck` survives, `repair()` on the boot after that sees
  `/_otampy_set_rtc.py` missing but `/_otampy_set_rtc.py.bck` present and
  renames the `.bck` back into place — so the stale-dated helper runs a second
  time (setting the RTC to the *update's* wall-clock time, not now) before
  self-deleting again. The journal permanently lists a path that normally does
  not exist.
- **Impact:** One spurious, stale `machine.RTC().datetime(...)` call on the
  boot after every `otampy upd` (without `--no-rtc`). RTC feeds log timestamps
  and seeds the command-auth replay counter, so a backwards jump is not purely
  cosmetic. Currently *masked* by F-04 (the `.bck` is deleted before `repair()`
  can use it) — fixing F-04 unmasks it, so both must land together.
- **Suggested fix:** in `_run_default_update_loop`'s `UPDATE_COMMIT` branch,
  split `_otampy_set_rtc.py` out of `files` before calling `commit()` and place
  it with a plain `rename(staging, target)` — never backed up, never journalled.
  Named constant in `boot.py` (it already knows the module name in
  `_apply_staged_rtc_update`).
- **Resolution:** 2026-09-08, `feature/failsafe-update-retain-previous` step 10.
  New `boot._RTC_HELPER_FILE` constant. The `UPDATE_COMMIT` branch now walks
  `files`, places any pair whose target basename is `_RTC_HELPER_FILE` with a
  plain `remove`+`rename`, and passes only the `retained` pairs to
  `commit()`. `_apply_staged_rtc_update` derives its import name from the same
  constant (DRY). Test:
  `test_ota_boot.py::test_commit_does_not_retain_the_transient_rtc_helper` —
  full session with the helper in the manifest; asserts it is placed but has no
  `.bck` and is absent from the journal, while `main.py` is backed up normally.
- **Awaiting:** re-review (`/sl-findings review`) and HIL (the journal after an
  `otampy upd` must list only real targets, no `/_otampy_set_rtc.py`).

## Closed

### F-01 — `ChannelSerial.in_waiting` and `_pump` block on an empty serial port

- **Severity:** P2
- **Status:** closed
- **Area:** `src/otampy/` (channel.py; activated by the mux CLI wiring)
- **Found:** 2026-09-08 by /code-review (feature/channel-mux-cli-mode)
- **Evidence:** `src/otampy/channel.py:153` — `_pump` does
  `pending = getattr(self._ser, "in_waiting", 0) or 1` then
  `self._ser.read(pending)`. When the raw port's buffer is momentarily empty,
  `pending` is `1` and `serial.Serial.read(1)` blocks up to
  `serial_timeout_seconds` (default 2.0). `ChannelSerial.in_waiting`
  (`channel.py:174`) calls `_pump` first, so it blocks too — but a real
  `serial.Serial.in_waiting` never blocks. URST's `read_frame`
  (`urst/codec_layer.py`) does `bytes_to_read = max(1, self.ser.in_waiting)`
  then `self.ser.read(bytes_to_read)` — two `_pump` calls per loop iteration, so
  in mux mode one iteration can stall ~2×`serial_timeout` (~4 s) against a
  silent peer. Reproduced: with a raw port whose `read` sleeps 500 ms,
  `ChannelSerial(raw).in_waiting` took 500 ms and `.read(10)` a further 500 ms.
- **Impact:** Against a responsive device the exchange still completes (the
  end-to-end `test_mux_ping_roundtrip_returns_pong` passes), but on a slow or
  lossy link mux mode is ~2× slower to retry/give up than direct mode, and
  `read_frame`/`send_reliable` overshoot their millisecond timeout budgets.
  Direct mode is unaffected (`serial.in_waiting` is non-blocking there).
- **Suggested fix:** in `_pump`, read only `self._ser.in_waiting` bytes and
  return early when that is 0 (never fall back to a blocking `read(1)`).
- **Resolution:** 2026-09-08, `feature/channel-mux-cli-mode`. `_pump`
  (`src/otampy/channel.py:152`) now reads `getattr(self._ser, "in_waiting", 0)`
  and only calls `self._ser.read(pending)` when `pending` is non-zero — no
  `or 1` fallback. `ChannelSerial.read` returns `b""` promptly and URST's
  `read_frame` poll loop does the waiting. Tests:
  `tests/test_channel.py::TestChannelSerial::test_pump_does_not_read_when_port_is_empty`
  (fake serial whose `read` raises) and `test_pump_reads_only_what_is_pending`.
- **Closed:** 2026-09-08, /sl-findings review. Re-read `channel.py:152-167` as it
  now stands: `pending = getattr(self._ser, "in_waiting", 0)` with no `or 1`,
  `read()` only called when `pending` is truthy, `read()`/`in_waiting` return
  promptly. Blocking path gone. Full suite green (513). New Risk noted below
  (`.any()`-only ports). Re-review was same-session/same-agent as the fix; the
  producing `/code-review` was independent.

### F-02 — Mux CLI eagerly imports `urst` at `otampy.cli` import time

- **Severity:** P3
- **Status:** closed
- **Area:** `src/otampy/cli.py`
- **Found:** 2026-09-08 by /code-review (feature/channel-mux-cli-mode)
- **Evidence:** `src/otampy/cli.py:21` adds `from .channel import ChannelSerial`
  at module scope; `channel.py` does `from urst.codec_layer import cobs_decode,
  cobs_encode` at *its* module scope. Confirmed: `import otampy.cli` now leaves
  `urst` and `urst.codec_layer` in `sys.modules` (they were not before — the
  rest of cli.py keeps `import serial` / `from urst import Urst` function-local,
  and even guards the type-only imports under `TYPE_CHECKING`). `serial` is
  still lazy.
- **Impact:** `otampy --help`, shell completion and every non-device subcommand
  now pay the `urst` import (small — a pure-Python module plus a 256-entry CRC
  table build). Minor, but it breaks the deliberate lazy-import pattern this
  diff otherwise preserves.
- **Suggested fix:** move `from otampy.channel import ChannelSerial` inside
  `_open_transport`, alongside the existing `import serial` / `from urst import
  Urst`.
- **Resolution:** 2026-09-08, `feature/channel-mux-cli-mode`. Moved
  `from .channel import ChannelSerial` from `cli.py` module scope into
  `_open_transport`. Verified: `import otampy.cli` leaves neither `urst` nor
  `serial` in `sys.modules`. Test:
  `tests/test_mux_cli.py::TestLazyImport::test_importing_cli_does_not_pull_in_urst_or_serial`
  (subprocess).
- **Closed:** 2026-09-08, /sl-findings review. `ChannelSerial` now appears in
  `cli.py` only at `_open_transport`'s local import and its one use site
  (grep-verified); no module-scope reference. Subprocess test confirms `import
  otampy.cli` leaves `urst`/`serial` out of `sys.modules`.

### F-03 — A malformed `OTAMPY_MUX` fails every command, including the ones to fix it

- **Severity:** P2
- **Status:** closed
- **Area:** `src/otampy/cli.py`
- **Found:** 2026-09-08 by /code-review (feature/channel-mux-cli-mode)
- **Evidence:** `src/otampy/cli.py:831` — the `cli` group callback runs
  `ctx.obj["mux"] = mux if mux is not None else get_mux_enabled()` for **every**
  subcommand, and `get_mux_enabled()` (`cli.py:518`) raises `ClickException` on
  an unrecognised `OTAMPY_MUX` token. Reproduced: with `OTAMPY_MUX=maybe`,
  `otampy mux --show`, `otampy mux --clear` and `otampy ports --show` all exit 1
  with `Error: OTAMPY_MUX must be one of …` — the user cannot use the `mux`
  command to inspect or clear the setting while the bad env var is present.
- **Impact:** Self-inflicted lockout from a typo in an env var. Recovery is
  `unset OTAMPY_MUX` (the error message names the var), so impact is limited,
  but a config-inspection/repair command should not be blocked by the config it
  inspects.
- **Suggested fix:** in the `cli` callback, treat an unparseable `OTAMPY_MUX` as
  "unset" with a warning (fall through to the saved setting), or defer the
  strict parse to the point of use so `otampy mux` still runs.
- **Resolution:** 2026-09-08, `feature/channel-mux-cli-mode`. `get_mux_enabled`
  (`src/otampy/cli.py`) no longer raises on an unrecognised token — it prints
  `Warning: ignoring OTAMPY_MUX=… ` to stderr and falls through to the config
  chain (new `_parse_mux_token` / `_mux_from_config` helpers). `_mux_state`
  appends `(env OTAMPY_MUX=… invalid, ignored)` to the source so `otampy mux
  --show` still reports it. Verified: `OTAMPY_MUX=maybe otampy ping` and
  `otampy mux --clear` now exit 0 with a warning. Tests:
  `test_invalid_env_token_is_ignored_with_warning`,
  `test_invalid_env_falls_through_to_default`,
  `TestMuxCommand::test_show_still_works_with_a_malformed_env_var`.
- **Closed:** 2026-09-08, /sl-findings review. `get_mux_enabled` (`cli.py:532`)
  has no `raise` path — unrecognised token → stderr warning → `_mux_from_config`.
  Its only caller is the `cli` group callback (`cli.py:848`); `_mux_state` uses
  `_parse_mux_token` directly. Re-verified live: `OTAMPY_MUX=maybe otampy ping`
  and `otampy mux --clear` both exit 0. The empty-string-is-disable behaviour is
  unchanged (tracked as a Risk).

---

## Risks

Concerns worth keeping but not confirmed defects. No ID, block nothing.

- **`ChannelSerial` decoded-buffer overflow drops the oldest bytes.**
  `channel.py:161` caps the decoded channel-0 buffer at `OTA_BUFFER_BYTES`
  (2048) and drops from the front on overflow, which would truncate an in-flight
  URST frame. Not filed as a finding because URST is stop-and-wait — the host
  reads each frame (and each fragment) before the next arrives, so >2 KB of
  unread decoded data has no known path. Mirrors the shipped device
  `_VirtualPort._feed` behaviour. Revisit if a large unsolicited burst path
  appears.
- **`OTAMPY_MUX=` (set but empty) is treated as an explicit "disable".**
  `_MUX_FALSE_TOKENS` (`cli.py:94`) includes `""`, so an empty `OTAMPY_MUX`
  overrides a saved `mux = true` and silently selects direct mode. Deliberate in
  the current design and asserted by `test_env_token_parsing`, but many CLIs
  treat an empty env var as unset. `otampy mux --show` does report the source as
  `env OTAMPY_MUX`, so it is discoverable. Reconsider if it bites.
- **`ChannelSerial` only reads via `in_waiting`, not `any()`.** After the F-01
  fix, `_pump` (`channel.py:156`) does `getattr(self._ser, "in_waiting", 0)` and
  reads nothing if that attribute is absent — so a MicroPython-style port
  exposing only `.any()` would receive nothing. Not a defect today: `cli.py`'s
  `_open_transport` always wraps a real `serial.Serial`, and every test double
  provides `in_waiting`. If `ChannelSerial` is reused with a non-pyserial port,
  add an `elif hasattr(self._ser, "any")` branch like `urst.codec_layer` has.
