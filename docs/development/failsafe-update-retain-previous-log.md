# Retain-previous commit + journal contract — dev log

Spec: `docs/development/failsafe-update-retain-previous-spec.md`
Branch: `feature/failsafe-update-retain-previous`

## 2026-09-08 — build started

Branch created from `develop` (clean, at `78ef5c3`). Findings ledger
(`docs/development/findings.md`) does not exist yet — nothing open to block
this work.

### Design decision taken in step 1 — where `_resolve_path` lives

The spec left this open ("import from `.boot` … or lift `_resolve_path` into
`core.py` … decide during build"). `boot.py` will import `restore` (steps 4-6),
so `restore` importing from `.boot` would be a cycle. Lifted `_resolve_path`
into `core.py` next to `_get_config`; `boot.py` now does
`from .core import _get_config, _resolve_path`, which keeps the module-level
name `boot._resolve_path` that the existing tests monkeypatch. One copy, no
cycle.

### Build progress

- **Step 1** (`046bffc`) — `restore.py` journal helpers + `test_restore.py`.
  One test assertion was wrong (expected re-resolved journalled paths); the
  code stores paths verbatim, so the test was corrected.
- **Step 2** (`00caaf7`) — `restore.commit()`. The in-progress pair must be
  recorded in the rollback list *before* the staging rename: if that rename
  fails, the target has already moved to `.bck` and must be rolled back too.
  Caught by `test_commit_rolls_back_whole_set_on_rename_failure`.
- **Step 3** (`5c7da3e`) — `restore.repair()`, two modes.
- **Step 4** (`b9b14e8`) — `boot.run()` calls `repair()` after the staged-RTC
  step via a local `from .restore import repair`; `ota.OTA.boot()` teardown
  releases `restore` alongside `boot`.
- **Step 5** (`ce3f0cc`) — `clear_journal()` at the top of `UPDATE_START`.
- **Step 6** (`d5a8003`) — `UPDATE_COMMIT` now just calls `commit()`;
  `COMMIT_ERR` is a documented response.
- **Step 7** (`0a3fece`) — `_cleanup_orphaned_ota` sweeps `<x>.bck` not in the
  journal; journalled backups threaded through recursion as `kept_backups`.
- **Step 8** — docs, changelog, both `configota` examples, `TODO.md`.

Pyright reports "Import '.restore' could not be resolved" for the in-function
imports in `boot.py`. Editor-only LSP artefact — the device lib is not on
pyright's path. The import works at runtime (every device test exercises it)
and pre-flight (ruff + full pytest, mirrors CI) is green at every step.

## 2026-09-08 — HIL: not yet run

Host side is complete: all 8 build steps committed, `pre_flight_check.py`
green (ruff + full pytest). Findings ledger (added by Simon at `98ea791`) is
empty — nothing blocks a merge.

**Robot not reachable from this session.** `otampy -p /dev/ttyUSB0 ping`
(direct on the gateway XBee) failed with "device reports readiness to read but
returned no data (… multiple access on port?)" after three handshake attempts
— consistent with the diff-drive-robot gateway daemon holding `/dev/ttyUSB0`,
or the robot being powered down. Not probed further: grabbing that port while
the gateway may be running, or repeated USB pokes, is exactly the
false-alarm pattern to avoid.

HIL therefore stays with Simon. Plan is the spec's Verification section
(happy path, power-loss whole-set rollback, single-generation retention, bad
firmware survives + manual `.bck` recovery). Bootstrapping needs
`otampy deploy` on the feature branch (raw-port, human-run only). Results and
every measurement to be appended here before `git flow feature finish`.

## 2026-09-08 — merged `develop` (channel-mux)

`develop` gained the **channel-mux** feature (three merged sub-branches:
`opt-in`, `cli-mode`, `scaffold`). Merged into this branch at `a8f3633`.

- **Conflict surface was small.** Two conflicts: `CHANGELOG.md` (both prepend
  an `[Unreleased]` entry — kept both, channel-mux's `Added` first, the
  retain-previous item folded into the shared `Changed` section) and
  `docs/development/findings.md` (add/add — took `develop`'s, which records and
  closes F-01..F-03 from the channel-mux review; this branch's copy was the
  empty ledger from `98ea791`). `docs/protocol.md` and `docs/architecture.md`
  auto-merged with both sets of changes intact.
- **No device-lib interaction.** `git diff 0ee2a52..HEAD -- device/lib/`
  is exactly the four retain-previous files. Channel-mux is host-side
  (`cli.py`, `channel.py`) plus `examples/shared-uart/` scaffolds; it does not
  touch `boot.py`, `ota.py`, or the OTA update loop.
- **Protocol decision still holds.** The mux outer frame
  (`COBS(channel_id ‖ inner_URST_frame) ‖ 0x00`, protocol §1.3) is opt-in and
  sits *below* URST. When mux mode is on, retain-previous's `UPDATE_*` traffic
  is wrapped transparently like everything else — the commit/journal/repair
  logic is above the wire and unaffected. The spec's "Wire format change? No"
  line is still true *for retain-previous*; the mux frame is orthogonal. Not
  re-signed — no scope change.
- `pre_flight_check.py` green after the merge (ruff + full pytest, now
  including channel-mux's suite).

## 2026-09-08 — HIL round 1: two defects, both fixed

Phase 1 bootstrap (`otampy deploy`) succeeded — `restore.py` on device, new
`boot.py`. Phase 2 (`otampy upd main.py`) exposed:

- **F-04 (P1, fixed `9659bc1`).** After the post-commit reboot, `otampy ls /`
  showed the journal but **no `main.py.bck`**. Device `ota.log`:
  `Removing orphaned file: /./main.py.bck`. `_cleanup_orphaned_ota` compared
  `_resolve_path("./main.py.bck")` (= `"/./main.py.bck"` on MicroPython)
  against the journal's `"/main.py.bck"` — never equal, so every retained
  backup was swept on the first boot after a commit. Retain-previous's whole
  guarantee was void on hardware. The unit test missed it because CPython
  collapses the `./` that device string-concat does not. Fix: `boot._canonical`
  normalises both sides before the membership test. New regression test does
  not mock `_resolve_path`.
- **F-05 (P2, fixed `81c70c7`).** The journal also listed `/_otampy_set_rtc.py`
  — the one-shot RTC helper the host ships in every `otampy upd` manifest.
  `commit()` was backing it up and journalling it; once F-04 was fixed,
  `repair()` would resurrect the stale-dated helper from `.bck` on the boot
  after each update. Fix: `UPDATE_COMMIT` places the helper with a plain rename
  and passes only real targets to `commit()`. (Masked by F-04 until now — the
  `.bck` was being deleted before `repair()` could use it.)

Full device suite (281) + `pre_flight_check.py` green after both fixes.

**HIL round 2 pending** (Simon): re-bootstrap and re-run Phase 2 onward. F-04
and F-05 stay `fixed` (not `closed`) until hardware confirms:
- Phase 2: `main.py.bck` is **present** after the post-commit reboot;
  `otampy cat /otampy-update.journal` lists only `/main.py` (no
  `/_otampy_set_rtc.py`).
- Then Phases 3–5 as originally planned.

## 2026-09-08 — HIL round 2: F-06 (P0), and the test device went dark

Fault-injection HIL for the interrupted-commit path. A doctored `restore.py`
(scratchpad `restore_HIL.py`) added a 25 s `time.sleep` wait loop on the last
commit pair, after `target -> .bck` and before `staging -> target`, so the
`otampy upd` CLI hangs at the worst-case interrupt point. (`core.logger` is
`NullLogger` on this device — no `--with-logger` — so the countdown messages
went nowhere; the CLI hang is the only cue.)

`otampy upd main.py boot.py` was interrupted (power) during the window. Result
on the device (`otampy -p /dev/ttyUSB0 ls /` / `cat`):

```
main.py            <- new (committed)         main.py.bck   <- old
boot.py  ABSENT                               boot.py.bck   <- old
boot.py.ota        <- staged, never placed
otampy-update.journal:  committing / /main.py / /boot.py
update_requested.flag   still set
```

**F-06 (P0).** `repair()` never ran because it lives in `boot.run()` /
`boot.py`, and `boot.py` is the file the interrupt deleted. MicroPython booted
straight to the new `main.py` (hence `otampy ping` -> PONG), the `committing`
state persisted across reboots, and the device had no remote self-recovery.
See findings.md F-06 and the 1-3-1 below.

### Recovery attempt + device went unresponsive

Over the radio while `main.py` was still serving runtime commands:
1. `otampy cp .../restore.py:lib/otampy/restore.py` — **succeeded** (real
   6346-byte version back on device; doctored `restore_HIL` gone).
2. `otampy cp .../examples/boot.py:boot.py` — **"Failed to send command over
   transport"**, and the device stopped answering the radio entirely from that
   point. `/dev/ttyACM0` still enumerates as "MicroPython Board in FS mode"
   (Pico is powered, MicroPython running) — it is a radio / `main.py` liveness
   issue, not a dead board. Not power-cycled or USB-inspected from this session
   (physical access + the reset/settle discipline are Simon's). Repeated radio
   pokes stopped here deliberately.

Device state when last seen: `boot.py` absent, `restore.py` = real version,
journal `committing`, flag set. Recovery steps handed to Simon.

### 1-3-1 — where does `repair()` run when `boot.py` can be the casualty?

**Problem:** `restore.repair()` is only reachable from `boot.py`, which is
exactly the file an interrupted `commit()` can leave absent.

**Options:**
- **A. `main.py` also calls `repair()` at startup** (or `OTA(...).recover()`).
  `commit()` renames one file at a time, so at any interrupt at most one of
  `boot.py`/`main.py` is missing — the survivor heals the set. One line in the
  scaffold; a custom `main.py` must opt in.
- **B. Special-case `boot.py` in `commit()`** — copy-into-place so `boot.py` is
  never absent. Recovery stays in `boot.py`; risk of a truncated `boot.py`.
- **C. Frozen minimal `_boot.py`** that runs `repair()` before `boot.py`.
  Robust; needs a freeze/manifest change at deploy time.

**Recommendation: A.** Smallest change, sound given the one-file-at-a-time
property, and it mirrors the existing `boot()`/`poll()` split in the facade.
Fold in as spec step 11, or split to its own sub-task alongside sub-task 4's
recovery theme — Simon's call.

### Resolution — step 11 (`b29d2c6`), Option A

Simon: go with A; no preference on step-11-vs-sub-task-4, so folded in here as
step 11. New `OTA.recover()` (`ota.py`, 8 lines incl. docstring) =
`restore.repair(self._core)` via local import. Both `main.py` scaffolds call
`ota.recover()` once after `ota = OTA(...)`. `recover()` is *just* `repair()` —
the stale `update_requested.flag` is left for the next boot's `boot.run()` to
time out and clear (~5 s), rather than adding flag-handling to the scaffold.

Device was recovered by Simon (`otampy deploy` + power-cycle) — but that deploy
predates `b29d2c6`, so the device's `main.py` has no `recover()` yet. HIL
round 3 must redeploy first.

Doctored `restore_HIL.py` regenerated in the scratchpad (30 s window on the
last commit pair; `core.logger.error` countdown — only visible in
`/ota.log`/`LOG_FILE` if `--with-logger` is installed, otherwise the ~30 s CLI
hang is the cue).

**HIL round 3 (Simon), all on `feature/failsafe-update-retain-previous`:**
1. Redeploy so `main.py` has `recover()` and the lib has F-04/F-05:
   `otampy deploy -p /dev/ttyACM0` → power-cycle → `otampy ping`.
2. Phase 2 (F-04/F-05): `otampy upd main.py` → `main.py.bck` present, journal
   lists only `/main.py`.
3. Phase 3 (F-06 + whole-set rollback): deploy `restore_HIL.py` over
   `lib/otampy/restore.py`, `otampy upd main.py boot.py`, pull power in the
   ~30 s hang. After power-up: **no USB touch** — `otampy ping` → PONG,
   `otampy cat /otampy-update.journal` line 1 `0`, `otampy ls /` shows `boot.py`
   present and both files rolled back. Then redeploy the real `restore.py`
   (do **not** pull power that time).
4. Phases 4–5 as before.
5. F-04/F-05/F-06 close only after this passes.

## 2026-09-08 — HIL round 3 attempt: operator error, not a code fault

Simon caught the commit window cleanly on `otampy upd main.py boot.py` (real
commit, no doctored `restore.py` needed — the CLI's "commit failed: None" is
its read timing out when power drops). Resulting device state was the exact
F-06 case: `main.py` committed, `boot.py` renamed to `.bck`, `boot.py.ota`
unplaced, `boot.py` absent, journal `committing`, flag set.

**But it did not self-heal** — because the `main.py` that got pushed had **no
`ota.recover()` call**: while adding the HIL marker to
`src/otampy/device/examples/main.py`, the `ota.recover()` line (from `b29d2c6`)
was deleted in the same edit. `otampy upd` sends the working-tree file, so the
committed `/main.py` on the device genuinely lacked the recovery call. F-06's
fix itself is intact and correct in `b29d2c6`; nothing to change in the code.

Scaffolds restored from HEAD, clean `# HIL-R3` marker re-added with
`ota.recover()` kept. Doctored `restore_HIL.py` regenerated (30 s window).
Device needs a clean `otampy deploy` (its FS is mid-interrupted-commit).

**HIL round 3, corrected:**
1. `otampy deploy -p /dev/ttyACM0` (clean tree + `# HIL-R3` markers), power-cycle,
   `otampy ping`. Confirm `otampy cat /main.py | grep recover` shows the call.
2. Phase 2 (F-04/F-05): `otampy upd main.py` → `main.py.bck` present, journal
   lists only `/main.py`.
3. Phase 3 (F-06): `otampy upd main.py boot.py`, pull power mid-commit. After
   power-up, **no USB** — `otampy ping` → PONG, `cat /otampy-update.journal`
   line 1 `0`, `ls /` shows `boot.py` present, both files rolled back.
   (Optional: deploy `restore_HIL.py` over `lib/otampy/restore.py` first for a
   reliable 30 s window; redeploy the real one after, no power pull.)
4. Phases 4–5.
