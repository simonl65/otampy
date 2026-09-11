# TODO

Project-wide outstanding-work tracker — the source of truth for implementation status.

This file lists only what remains open. Update it in the same change as newly discovered work; when a task is done, remove it here and let the commit/PR that did the work be the record, rather than leaving completed items in this file.

Non-trivial tasks get their own dev log in `docs/development/`, named for the task (e.g. `docs/development/<task slug>>-log.md`), not one shared file.

## Tasks in priority order

[ ] **Fail-safe Updates** The current solution overwrites working code once it's been verified but this leaves the chance that the new firmware might "brick" the device. I want to understand what options we have to ensure that we can always get back to a known working firmware. I'd prefer not make any changes to the underlying URST package if possible, but may consider it if it has advantages.

  Truly remote-safe updates need rollback: retain the previous application, reboot into the candidate, require a health confirmation, and restore the previous version if startup fails. Without that, a validly transferred but faulty boot.py, main.py or configota.py can still strand the device. For OTAmpy's actual purpose, "never destroy the only remote recovery path" should be a core invariant, enforced on the device — not merely a CLI precaution.

  OTAmpy should also provide a `ROLLBACK` command, to cover situations where new code runs but the user finds an issue.

  - Model: Opus
    - device-safety architecture with cross-repo trade-offs and a hard "never destroy the only remote recovery path" invariant; the deepest design task here.
  - Spec : yes
    - settle the rollback design (retain-previous / reboot-into-candidate / health-confirm / auto-restore) and the URST-change decision before any code.
  - Fresh: yes
    - start clean.

  Protocol decision (signed off 2026-09-08): no URST change. New application-layer
  commands on channel 0 only (`ROLLBACK`, `CONFIRM`, `UPDATE_STATE`), retained-previous
  via `rename` to `<target>.bck` (`.bak` is already used transiently by `filecopy._commit`),
  a plain-text on-device journal. Split into four sub-tasks, each leaving the device safe
  to power on; build in order.

  - [x] **1. Retain-previous commit + journal contract.** `UPDATE_COMMIT` becomes
    all-or-nothing: it renames each replaced file to `<target>.bck` instead of deleting
    it, and a plain-text journal carries a `committing` marker written before the first
    rename and flipped to a boot-attempt counter (`0`) after the last. A failed or
    power-interrupted commit is rolled back as a whole set from the `.bck` files by
    `restore.commit()` or by `boot.py`'s `repair()` on the next boot - the device is
    never left on a mixed-generation tree. The next `UPDATE_START` discards the prior
    generation's journal and `.bck` files. Journal format and `.bck` naming are the
    load-bearing contract for sub-tasks 2-4.
    Spec: `docs/development/failsafe-update-retain-previous-spec.md`.
  - [x] **2. Trial boot, health confirmation, auto-restore.** `boot.py` increments the
    journal attempt counter on each boot into an unconfirmed candidate; past
    `OTA_TRIAL_BOOTS` it restores every `.bck` and resets. `CONFIRM` (host, after a
    successful `PING`) and `ota.confirm()` (application) flip the journal to
    `confirmed`, stopping the counter but keeping `.bck` until the next `UPDATE_START`.
    `UPDATE_STATE` -> `STATE_OK:<trial|stable>:<attempt>`. `otampy upd` sends `CONFIRM`
    after `COMMIT_OK` + a health `PING` (unless `--no-confirm`).
    Spec: `docs/development/failsafe-update-trial-boot-spec.md`.
  - [x] **3. `ROLLBACK` command + `otampy rollback` CLI.** User-initiated revert of a
    candidate that booted and was confirmed but is wrong. `restore.rollback()` reuses
    `restore_all()`; `manager.poll` takes the `RB` pre-reset path (`_persist_replay_floor`
    then `machine.reset()`). `otampy rollback` prompts, sends `ROLLBACK`, waits for `PONG`.
    Spec: `docs/development/failsafe-update-rollback-spec.md`.
  - [x] **4. Boot-time recovery listen window.** `boot.py` briefly accepts
    `UPDATE_REQUEST`/`ROLLBACK` with no flag set (`OTA_BOOT_LISTEN_MS`), so a device
    stranded by a faulty `main.py` or `boot.py` still has a remote recovery path.
    Spec: `docs/development/failsafe-update-boot-listen-spec.md`.
    Made hittable in practice under F-10 — a ~1 s window opens and shuts before a
    power-cycled XBee is awake, so a boot following one that never reached
    `OTA.poll()` now opens `OTA_BOOT_RECOVERY_LISTEN_MS` (default `8000`) instead.
    Spec: `docs/development/failsafe-update-window-reachability-spec.md`.
  - [ ] **5. Land a `--recover` command in the boot-time recovery window.**
    Sub-task 4's window is open and reachable on hardware — 9006 / 9017 /
    8977 ms on three consecutive stranded boots, and a normal-path `PING` drew
    the window's own `ERROR:Recovery window` refusal from inside one. But
    `_recover_query`'s fail-fast handshake profile (one CONNECT attempt, a
    0.1 s serial timeout, the port reopened every cycle) cannot complete a
    handshake over an XBee, so radio recovery still fails (F-15). The host
    opens the port once and retries `connect()` at stock URST timings instead.
    Folds in F-13 (a `--recover` timeout test that passes on a validation error
    and never reaches the path it names) and F-14 (a trial boot gets no listen
    window at all when the wide window is disabled). Closes F-10.
    Spec: `docs/development/failsafe-update-recovery-handshake-spec.md`.
    **HIL verification outstanding — this sub-task's step 7, Opus only.**

[ ] **Feed a caller-supplied watchdog inside the boot-time recovery window.** Follow-up to finding F-12 (P2, `docs/development/findings.md`). `configota.example.py` tells an integrator arming a watchdog before `OTA(...).boot()` to keep `OTA_BOOT_RECOVERY_LISTEN_MS` "under your watchdog period... 8000 is just under the RP2040's ~8388 ms cap" — but the wide window's own blocking span measures 8899-9570 ms on real hardware (two independent HIL runs, `docs/development/failsafe-update-window-reachability-log.md` and this session's F-18 diagnostic), already past 8388 before the ~1.5 s pre-window boot cost is added. Nothing feeds a watchdog anywhere in that span: `_run_boot_listen`'s idle path is `read()` -> `sleep` -> `continue` with no WDT awareness, and `manager.py` deliberately places watchdog feeding on the caller, once per `poll()` — which `boot()` never calls. An integrator who follows the shipped guidance is reset mid-window on every at-risk boot, in a loop that never reaches `main.py`. Decided direction (2026-09-11): let `OTA` take a caller-supplied watchdog object and feed it inside `_run_boot_listen`'s read loop — keeps both the wide window and boot-path WDT cover, the only option of the three considered that keeps the promise `configota.example.py` currently makes. Changes `OTA`'s constructor signature, so it needs a spec before any code (rejected alternatives: lowering the default window spends recovery margin F-10 already called the tightest number in the spec, and documenting the incompatibility away doesn't fix it for anyone who needs both).

  - Model: Opus
    - touches the OTA constructor's public signature and the boot-time window's real-time behaviour; a wrong call here reintroduces F-12 or breaks the window's timing guarantees.
  - Spec : yes
    - settle the watchdog-object interface (what `OTA` accepts, what "feed" means across MicroPython WDT APIs) and confirm the feed point can't itself blow the window's own deadline before any code.
  - Fresh: yes.

[ ] Add some way to version firmware so we know which version is actually running at any time. The version should be available via a `otampy ver`

[ ] **Freeze `restore.py` / a recovery `_boot.py` into the deployed image.** Follow-up to finding F-08 (P2, `docs/development/findings.md`). The recovery logic lives in `src/otampy/device/lib/otampy/restore.py`, imported lazily by both `boot.run()` and `ota.recover()`. `commit()` renames one file at a time, so a power loss while `restore.py` itself is the current commit pair leaves `/lib/otampy/restore.py` absent with `restore.py.bck` present: the next boot's `from .restore import ...` raises `ImportError` in both `boot.py` and `main.py`, and the boot-time recovery window (sub-task 4) cannot help because its own `from .restore import ...` raises first. Only triggered by a library update (`otampy upd lib/otampy/...` or a full re-deploy) with power lost in the narrow commit window — never a normal app update — and strictly smaller than the pre-retain-previous exposure, hence P2. A real fix needs frozen code: freeze `restore.py` into the deployed image, or F-06 Option C (a frozen `_boot.py` that runs `repair()` before `boot.py`). Needs a manifest/freeze change at deploy time.

  - Model: Opus
    - device-safety design touching the deploy-time freeze/manifest path and the boot chain; picks between freezing `restore.py` and a frozen `_boot.py`.
  - Spec : yes
    - settle the freeze mechanism and which module(s) get frozen before any code.
  - Fresh: yes.

[ ] **`test_ota_facade.py` leaks `sys.modules` state and can flake CI.** Found 2026-09-09 during F-09's HIL verification. `test_boot_releases_boot_module_and_can_run_again` calls `ota.boot()` with `boot.run` patched, so the teardown deletes `device_otampy.boot` (and `restore`, `authgate`) from `sys.modules` and never restores them. Under a `pytest-randomly` seed that orders this test before the `test_ota_boot.py` boot tests, those tests then `patch("device_otampy.boot._resolve_path", ...)` against a freshly re-imported module while their own module-level `from device_otampy import boot` still points at the stale one — 5 tests fail (`test_boot_handles_full_update_session`, `test_boot_aborts_active_update_and_cleans_staging`, `test_boot_cleans_orphaned_ota_on_normal_boot`, `test_commit_does_not_retain_the_transient_rtc_helper`, `test_boot_removes_orphan_bck_but_keeps_journalled_one`). Pre-existing, currently masked by alphabetical collection order; `test_boot_teardown_survives_micropython_delattr_keyerror` (added for F-09) already does the save/restore dance locally, which is the pattern to generalise — a `conftest.py` autouse fixture that snapshots and restores the `device_otampy` submodule table, or an explicit restore in the offending test. **Related, found 2026-09-10 during the F-10 window work:** `conftest.py` glob-loads the submodules in arbitrary order, so `boot`'s module-level `from .core import ...` can bind to a `device_otampy.core` instance that the loop then *replaces* in `sys.modules` — there are two live `core` modules during a run. Harmless today (nothing mutates module state) but it makes `monkeypatch.setattr` on a device module silently no-op, which cost real debugging time; `test_ota_boot.py`'s `_boot_mark_in_tmp` fixture works around it by patching the resolver's own `__globals__`. Loading `core` first (or importing submodules through the package rather than by path) would fix both this and the ordering flake above.

  - Model: Sonnet
    - contained test-infrastructure fix; the failure mode is understood, the fix is a fixture.
  - Spec : no.
  - Fresh: yes.

## Deferred - do not run these

[ ] **Run the `micropython-nasa-power-of-ten` skill against this repo (and `urst-mpy`).** Surfaced 2026-08-20 as a `Needs Review`/deferred item (D-1) in `diff-drive-robot`'s own NASA Power of Ten audit (`docs/development/NASA-Power-of-Ten-review.md`), which explicitly can't audit vendored code per its own `CLAUDE.md` convention -- `diff-drive-robot/robot/device/lib/otampy`/`lib/urst` are synced verbatim from here and from `urst-mpy`, not maintained in that repo. That audit's shallow grep pass (not a deep read) flagged four spots worth a proper look, evidence as of otampy 4.5.0/urst-mpy 3.2.0:

- `device/lib/otampy/boot.py:112` -- `while True:` in `_run_default_update_loop`. Likely fine on inspection: it has its own `OTA_TIMEOUT_MS`-based inactivity timeout (`_ticks_diff(...) >= timeout_ms` -> sends `UPDATE_ABORTED` and breaks), confirmed while investigating an unrelated `diff-drive-robot` watchdog issue the same day -- but that was one read, not a full audit pass.
- `device/lib/otampy/mux.py:179` -- `while True:`, not yet reviewed.
- `urst-mpy`'s `device/lib/urst/core_handler.py:274` -- `while True:`, not yet reviewed (different repo).
- `device/lib/otampy/boot.py:358,438` -- two bare `except Exception:` blocks, not yet reviewed.
  Rather than one-off reading these four spots, run the full skill against both repos to get a proper structured audit (same as `diff-drive-robot`'s own, which found real value beyond just these four lines) instead of a partial manual pass.

  - Model: Sonnet
    - the `sl-micropython-nasa-power-of-ten` skill drives the work; audit is read-only and mechanical.
  - Spec : no
    - the skill is the process; feed real findings into `sl-findings` afterwards.
  - Fresh: yes
    - dedicated audit session per repo.

[ ] **An interrupted/aborted update handshake can crash `boot.py` entirely.** (Not sure if this is an `otampy` or `urst-mpy` issue and has only been seen once so far) Discovered 2026-08-17 while testing the gc-collect-scheduling change (see `docs/development/gc-collect-scheduling-log.md`'s later entry) -- not related to that task, a real robustness gap hit by chance. When a manifest-send handshake failed repeatedly (radio-level flake, not code), the device raised an unhandled `RuntimeError: reply() called with nothing received yet to reply to` from vendored `lib/otampy/boot.py:132` (`_run_default_update_loop`) via `lib/urst/core_handler.py:226` (`reply()`). `robot/device/boot.py` has no `try/except` around `OTA(...).boot()`, so this took the whole boot process down -- `main.py` never ran (dead status LED, fully local symptom), and the radio link went fully unresponsive since nothing was left running to service it. The crash recurred even after a genuine power-off/on of the robot (Pico + peripherals, via the PSU board -- the host USB link is data-only, not power), most plausibly because host-side retry traffic kept re-triggering the same handshake state on each fresh boot (not confirmed). Recovery was a full reflash + `otampy deploy`. Needs: root-causing the `reply()` state machine bug in `urst-mpy` (Simon's repo, `/home/simon/Documents/myOSS`), and a design decision on whether `robot/device/boot.py` should catch-and-fall-through to `main.py` on an OTA.boot() failure rather than crash outright.

  - Model: Opus
    - state-machine root-cause across otampy + urst-mpy plus a boot-robustness design call.
  - Spec : yes
    - the catch-and-fall-through decision needs deciding before code.
  - Fresh: yes.

[ ] **Session-based ports** Is session-based port setting being used - seems to fail with "Error: Error: Missing serial port. Specify with --port or -p option"?

  - Model: Sonnet
    - contained bug hunt in the CLI's port-resolution path.
  - Spec : no
    - investigate then fix.
  - Fresh: yes.

[ ] **Copy direction** Enable `cp` to copy from device to host.

  - Model: Sonnet
    - small, well-bounded CLI feature mirroring the existing host→device path.
  - Spec : no
    - but confirm arg/direction syntax first.
  - Fresh: yes.

[ ] **Ignore caches** `--all-files` should ignore `__pycache__/` folders and `_.example._` files.

  - Model: Haiku
    - one localised filter change to the file-walk with a matching test.
  - Spec : no.
  - Fresh: yes.

[ ] **Serial Monitor** Add a serial monitor window/pane that unobtrusively displays live data that's sent/received on the port.

  - Model: Sonnet
    - moderate UI/stream feature; the port-sharing/contention design is the only hard part.
  - Spec : yes
    - decide how it coexists with active `otampy` commands on the same port.
  - Fresh: yes.

[ ] **OTAmpy Decoder** Create a CLI decoder for URST frame data (e.g. "000205020407202001e80303036b3d00" and "b'\x00\x02\x05\x02\x04\x07 \x01\xe8\x03\x03\x03k=\x00'")

  - Model: Sonnet
    - self-contained parser/pretty-printer against the URST frame spec.
  - Spec : yes
    - pin the input formats accepted and output layout before building.
  - Fresh: yes.
