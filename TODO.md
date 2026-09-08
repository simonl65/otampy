# TODO

Project-wide outstanding-work tracker — the source of truth for implementation status.

This file lists only what remains open. Update it in the same change as newly discovered work; when a task is done, remove it here and let the commit/PR that did the work be the record, rather than leaving completed items in this file.

Non-trivial tasks get their own dev log in `docs/development/`, named for the task (e.g. `docs/development/<task slug>>-log.md`), not one shared file.

## Tasks in priority order

[ ] **Fail-safe Updates** The current solution overwrites working code once it's been verified but this leaves the chance that the new firmware might "brick" the device. I want to understand what options we have to ensure that we can always get back to a known working firmware. I'd prefer not to make any changes to the underlying URST package if possible, but may consider it if it has advantages.

  - Model: Opus — device-safety architecture with cross-repo trade-offs and a hard "never destroy the only recovery path" invariant.
  - Spec : yes — settle the rollback design and URST-change decision before any code.
  - Fresh: yes — start clean; heavily overlaps the deferred rollback item below, consider merging.

## Deferred - do not run these

[ ] **Run the `micropython-nasa-power-of-ten` skill against this repo (and `urst-mpy`).** Surfaced 2026-08-20 as a `Needs Review`/deferred item (D-1) in `diff-drive-robot`'s own NASA Power of Ten audit (`docs/development/NASA-Power-of-Ten-review.md`), which explicitly can't audit vendored code per its own `CLAUDE.md` convention -- `diff-drive-robot/robot/device/lib/otampy`/`lib/urst` are synced verbatim from here and from `urst-mpy`, not maintained in that repo. That audit's shallow grep pass (not a deep read) flagged four spots worth a proper look, evidence as of otampy 4.5.0/urst-mpy 3.2.0:

- `device/lib/otampy/boot.py:112` -- `while True:` in `_run_default_update_loop`. Likely fine on inspection: it has its own `OTA_TIMEOUT_MS`-based inactivity timeout (`_ticks_diff(...) >= timeout_ms` -> sends `UPDATE_ABORTED` and breaks), confirmed while investigating an unrelated `diff-drive-robot` watchdog issue the same day -- but that was one read, not a full audit pass.
- `device/lib/otampy/mux.py:179` -- `while True:`, not yet reviewed.
- `urst-mpy`'s `device/lib/urst/core_handler.py:274` -- `while True:`, not yet reviewed (different repo).
- `device/lib/otampy/boot.py:358,438` -- two bare `except Exception:` blocks, not yet reviewed.
  Rather than one-off reading these four spots, run the full skill against both repos to get a proper structured audit (same as `diff-drive-robot`'s own, which found real value beyond just these four lines) instead of a partial manual pass.

  - Model: Sonnet — the `sl-micropython-nasa-power-of-ten` skill drives the work; audit is read-only and mechanical.
  - Spec : no — the skill is the process; feed real findings into `sl-findings` afterwards.
  - Fresh: yes — dedicated audit session per repo.

[ ] **An interrupted/aborted update handshake can crash `boot.py` entirely.** (Not sure if this is an `otampy` or `urst-mpy` issue and has only been seen once so far) Discovered 2026-08-17 while testing the gc-collect-scheduling change (see `docs/development/gc-collect-scheduling-log.md`'s later entry) -- not related to that task, a real robustness gap hit by chance. When a manifest-send handshake failed repeatedly (radio-level flake, not code), the device raised an unhandled `RuntimeError: reply() called with nothing received yet to reply to` from vendored `lib/otampy/boot.py:132` (`_run_default_update_loop`) via `lib/urst/core_handler.py:226` (`reply()`). `robot/device/boot.py` has no `try/except` around `OTA(...).boot()`, so this took the whole boot process down -- `main.py` never ran (dead status LED, fully local symptom), and the radio link went fully unresponsive since nothing was left running to service it. The crash recurred even after a genuine power-off/on of the robot (Pico + peripherals, via the PSU board -- the host USB link is data-only, not power), most plausibly because host-side retry traffic kept re-triggering the same handshake state on each fresh boot (not confirmed). Recovery was a full reflash + `otampy deploy`. Needs: root-causing the `reply()` state machine bug in `urst-mpy` (Simon's repo, `/home/simon/Documents/myOSS`), and a design decision on whether `robot/device/boot.py` should catch-and-fall-through to `main.py` on an OTA.boot() failure rather than crash outright.

  - Model: Opus — state-machine root-cause across otampy + urst-mpy plus a boot-robustness design call.
  - Spec : yes — the catch-and-fall-through decision needs deciding before code.
  - Fresh: yes.

[ ] Is session-based port setting being used - seems to fail with "Error: Error: Missing serial port. Specify with --port or -p option"?

  - Model: Sonnet — contained bug hunt in the CLI's port-resolution path.
  - Spec : no — investigate then fix.
  - Fresh: yes.

[ ] Enable `cp` to copy from device to host.

  - Model: Sonnet — small, well-bounded CLI feature mirroring the existing host→device path.
  - Spec : no — but confirm arg/direction syntax first.
  - Fresh: yes.

[ ] `--all-files` should ignore `__pycache__/` folders and `_.example._` files.

  - Model: Haiku — one localised filter change to the file-walk with a matching test.
  - Spec : no.
  - Fresh: yes.

[ ] Add a serial monitor window/pane that unobtrusively displays live data that's sent/received on the port.

  - Model: Sonnet — moderate UI/stream feature; the port-sharing/contention design is the only hard part.
  - Spec : yes — decide how it coexists with active `otampy` commands on the same port.
  - Fresh: yes.

[ ] Create a CLI decoder for URST frame data (e.g. "000205020407202001e80303036b3d00" and "b'\x00\x02\x05\x02\x04\x07 \x01\xe8\x03\x03\x03k=\x00'")

  - Model: Sonnet — self-contained parser/pretty-printer against the URST frame spec.
  - Spec : yes — pin the input formats accepted and output layout before building.
  - Fresh: yes.

[ ] Truly remote-safe updates need rollback: retain the previous application, reboot into the candidate, require a health confirmation, and restore the previous version if startup fails. Without that, a validly transferred but faulty boot.py, main.py or configota.py can still strand the device. For OTAmpy’s actual purpose, “never destroy the only remote recovery path” should be a core invariant, enforced on the device—not merely a CLI precaution.

  - Model: Opus — core device-enforced rollback invariant; the deepest design task here.
  - Spec : yes.
  - Fresh: yes — same problem space as "Fail-safe Updates" above; spec them together.
