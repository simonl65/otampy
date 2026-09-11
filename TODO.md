# TODO

Project-wide outstanding-work tracker — the source of truth for implementation status.

This file lists only what remains open. Update it in the same change as newly discovered work; when a task is done, remove it here and let the commit/PR that did the work be the record, rather than leaving completed items in this file.

Non-trivial tasks get their own dev log in `docs/development/`, named for the task (e.g. `docs/development/<task slug>>-log.md`), not one shared file.

## Tasks in priority order

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

## Deferred - do not run these

[ ] **Firmware versioning** Add some way to version firmware so we know which version is actually running at any time. The version should be available via a `otampy ver`

  - Model: Sonnet
    - touches both the deploy-time manifest/CLI path and a new `otampy ver` command, but no novel design once the scheme is settled.
  - Spec : yes
    - decide how the version is set (manual/derived from git), where it's stored on-device, and how `otampy ver` retrieves it before any code.
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

[ ] **Freeze `restore.py` / a recovery `_boot.py` into the deployed image.** Follow-up to finding F-08 (P2, `docs/development/findings.md`). The recovery logic lives in `src/otampy/device/lib/otampy/restore.py`, imported lazily by both `boot.run()` and `ota.recover()`. `commit()` renames one file at a time, so a power loss while `restore.py` itself is the current commit pair leaves `/lib/otampy/restore.py` absent with `restore.py.bck` present: the next boot's `from .restore import ...` raises `ImportError` in both `boot.py` and `main.py`, and the boot-time recovery window (sub-task 4) cannot help because its own `from .restore import ...` raises first. Only triggered by a library update (`otampy upd lib/otampy/...` or a full re-deploy) with power lost in the narrow commit window — never a normal app update — and strictly smaller than the pre-retain-previous exposure, hence P2. A real fix needs frozen code: freeze `restore.py` into the deployed image, or F-06 Option C (a frozen `_boot.py` that runs `repair()` before `boot.py`). Needs a manifest/freeze change at deploy time.

  - Model: Opus
    - device-safety design touching the deploy-time freeze/manifest path and the boot chain; picks between freezing `restore.py` and a frozen `_boot.py`.
  - Spec : yes
    - settle the freeze mechanism and which module(s) get frozen before any code.
  - Fresh: yes.

[ ] **An interrupted/aborted update handshake can crash `boot.py` entirely.** (Not sure if this is an `otampy` or `urst-mpy` issue and has only been seen once so far) Discovered 2026-08-17 while testing the gc-collect-scheduling change (see `docs/development/gc-collect-scheduling-log.md`'s later entry) -- not related to that task, a real robustness gap hit by chance. When a manifest-send handshake failed repeatedly (radio-level flake, not code), the device raised an unhandled `RuntimeError: reply() called with nothing received yet to reply to` from vendored `lib/otampy/boot.py:132` (`_run_default_update_loop`) via `lib/urst/core_handler.py:226` (`reply()`). `robot/device/boot.py` has no `try/except` around `OTA(...).boot()`, so this took the whole boot process down -- `main.py` never ran (dead status LED, fully local symptom), and the radio link went fully unresponsive since nothing was left running to service it. The crash recurred even after a genuine power-off/on of the robot (Pico + peripherals, via the PSU board -- the host USB link is data-only, not power), most plausibly because host-side retry traffic kept re-triggering the same handshake state on each fresh boot (not confirmed). Recovery was a full reflash + `otampy deploy`. Needs: root-causing the `reply()` state machine bug in `urst-mpy` (Simon's repo, `/home/simon/Documents/myOSS`), and a design decision on whether `robot/device/boot.py` should catch-and-fall-through to `main.py` on an OTA.boot() failure rather than crash outright.

  - Model: Opus
    - state-machine root-cause across otampy + urst-mpy plus a boot-robustness design call.
  - Spec : yes
    - the catch-and-fall-through decision needs deciding before code.
  - Fresh: yes.
