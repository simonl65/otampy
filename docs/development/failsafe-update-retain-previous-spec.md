# Retain-previous commit + journal contract — spec

**TODO item:** `[ ] 1. Retain-previous commit + journal contract.` (sub-task 1 of **Fail-safe Updates**)  
**Status:** approved  
**Components:** `src/otampy/device/lib/otampy/` (new `restore.py`, `boot.py`), `docs/protocol.md`, `docs/architecture.md`, `CHANGELOG.md`  
**Dev log:** `docs/development/failsafe-update-retain-previous-log.md` (created by `/sl-build`)

## Goal

After this ships, a boot-time `UPDATE_COMMIT` no longer has a window in which a
target file (`boot.py`, `main.py`, `configota.py`, a `lib/` module) is absent
from the filesystem: the previous version is renamed to `<target>.bck` and the
staged `.ota` is renamed into place. A plain-text journal at the filesystem root
records every retained target plus a boot-attempt counter (always `0` for now).

The commit is **all-or-nothing**. The journal is written with a
`committing` marker *before* the first rename and flipped to `0` only once
every file is in place. If a rename fails, `commit()` rolls the whole set back
from the `.bck` files and answers `COMMIT_ERR` — the device stays entirely on
the previous generation. If power is lost mid-commit, the marker is still
present on the next boot, and `boot.py`'s `repair()` restores **every**
journalled `.bck`, not just the files that didn't make it across. A device
therefore never runs a mixed-generation tree: it is either fully on the new
version or fully back on the old one.

The next update's `UPDATE_START` discards the previous generation's journal and
`.bck` files, so at most one previous generation is retained. No automatic
trial-boot rollback or health confirmation exists yet — that is sub-task 2 —
but a manual recovery is now possible because the previous code physically
survives a bad update, and an interrupted commit can no longer brick the device
or leave it half-updated.

## In scope

- New device module `restore.py`: journal format (with a `committing` marker),
  read/write/clear helpers, an all-or-nothing `commit()` with whole-set
  rollback, and a boot-time `repair()` that finishes or reverses an interrupted
  commit.
- `boot._run_default_update_loop`: `UPDATE_START` clears the prior generation;
  `UPDATE_COMMIT` delegates to `restore.commit()`.
- `boot.run()`: calls `restore.repair()` once, before the update-flag check, on
  every boot (flagged or not).
- `_cleanup_orphaned_ota`: also removes `<x>.bck` files not listed in the
  current journal (orphans from a crashed commit whose journal never landed).
- New config key `OTA_JOURNAL_FILE`, documented in `docs/architecture.md` and
  `docs/protocol.md`.
- Tests: new `test_restore.py`; additions to `test_ota_boot.py`.

## Out of scope

- Trial-boot attempt counting, `OTA_TRIAL_BOOTS`, automatic restore-all when a
  candidate fails to confirm — **sub-task 2** owns this. The counter is written
  and read now (fixed at `0`) only so the journal format does not change later.
- `CONFIRM` / `UPDATE_STATE` commands, `ota.confirm()` — sub-task 2.
- `ROLLBACK` command and `otampy rollback` — sub-task 3.
- Boot-time recovery listen window — sub-task 4.
- Any host CLI change. `otampy upd` is untouched; the device-side commit
  semantics change under it transparently. Host `CONFIRM`-after-commit is
  sub-task 2.
- Runtime `CP_*` copies (`filecopy.py`). Those keep their own transient `.bak`
  behaviour — see **Notes for the build**.
- A *filesystem-atomic* transaction. `commit()` and `repair()` give whole-set
  rollback on a failed or interrupted commit, but they are a sequence of
  ordinary `rename` calls, not one atomic op: a second power loss *during*
  `repair()` itself leaves whatever `repair()` had reached, and the next boot
  resumes it. Recovery is best-effort and converges over reboots; a hard
  power-loss-atomic guarantee needs a dual-slot layout and is not planned.

## Protocol decision

- **Existing OTAmpy/URST command reusable?** No new command is added in this
  sub-task. `UPDATE_START` and `UPDATE_COMMIT` keep their exact wire strings and
  responses (`SPACE_OK`/`SPACE_ERR`, `COMMIT_OK`/`COMMIT_ERR`); only the
  device-side filesystem effect changes.
- **Channel:** 0 (reliable, boot-time update loader). No channel-1 involvement.
- **Wire format change?** No. Host and device wire protocol byte-identical.
- **Signed off:** 2026-09-08 by Simon (covers all four sub-tasks: no URST
  change, `rename`-to-`.bck`, plain-text journal).

## Data and contracts

### Backup file naming — **load-bearing**

`<resolved-target-path> + ".bck"`. Suffix is the module constant
`restore._BACKUP_SUFFIX = ".bck"`, **not** configurable. `.bak` is deliberately
avoided: `filecopy._commit` already uses `<target>.bak` as a transient backup on
filesystems without `os.replace`.

### Journal file — **load-bearing**

- Path: `restore._journal_path(core)` = `_resolve_path(_get_config(core.config,
  "OTA_JOURNAL_FILE", "otampy-update.journal"))`.
- Encoding: UTF-8, `\n`-separated, trailing `\n`.
- Line 1: **either** the sentinel `restore._COMMIT_IN_PROGRESS = "committing"`
  (a commit is partway through — `repair()` must restore every listed `.bck`),
  **or** a base-10 non-negative integer, the boot-attempt counter (commit
  finished cleanly). Written as `committing` at the start of `commit()` and
  rewritten to `0` at the end. `repair()` in the finished state reads the
  integer and writes it back unchanged (sub-task 2 will increment it).
- Lines 2..n: one resolved absolute target path per retained file. Paths never
  contain `\n` (filesystem reality on littlefs/FAT). The backup path is always
  `line + ".bck"` — derived, never stored.
- A missing file or an empty file parses as `(attempt=0, in_progress=False,
  paths=[])`. Any line-1 value that is neither `committing` nor a valid
  integer is treated as `in_progress=True` (fail safe — restore everything).
  `read_journal` never raises.

Example, commit finished (`main.py` and `lib/sensor.py` replaced):

```
0
/main.py
/lib/sensor.py
```

Example, commit in progress (written before the first rename):

```
committing
/main.py
/lib/sensor.py
```

### `restore.py` public surface — **load-bearing**

| Function | Contract |
| --- | --- |
| `read_journal(core)` | `-> (attempt:int, in_progress:bool, paths:list[str])`. Never raises. `(0, False, [])` when absent/empty. Unrecognised line 1 → `in_progress=True`. |
| `write_journal(core, line1, paths)` | Best-effort. `line1` is `"committing"` or an int. Returns `True` on success, `False` on `OSError`. Never raises. |
| `clear_journal(core)` | Removes every `<path>.bck` for paths in the journal, then removes the journal file. Idempotent. Never raises. |
| `commit(core, files, delete_paths)` | All-or-nothing commit. `files` is the flat `[target, staging, target, staging, …]` list `_run_default_update_loop` already builds. Writes the journal with `committing` + targets, renames each `target`→`.bck` then `staging`→`target`, then rewrites line 1 to `0`. On any `rename` failure, restores every already-renamed `.bck` and returns `False`; on full success returns `True`. Never raises. |
| `repair(core)` | If line 1 is `committing` (or unrecognised): restore **every** journalled path whose `<path>.bck` exists (`rename(<path>.bck, target)`, removing a partial `target` first), then rewrite line 1 to `0`. If line 1 is an integer: restore only paths whose target is missing but `.bck` exists, and write line 1 back unchanged. Never raises. Bounded by journal length. |

### Config key

| Setting | Where | Default | Meaning |
| --- | --- | --- | --- |
| `OTA_JOURNAL_FILE` | `configota.py` | `otampy-update.journal` | Path of the retained-previous journal, at the filesystem root. |

### `commit()` sequence (crash analysis)

1. `write_journal(core, "committing", targets)` — every target that has a
   staging file. Written and flushed before any rename. From here on, a power
   loss at any point leaves the `committing` marker, and the next boot's
   `repair()` restores the whole set from `.bck`.
2. For each `(target, staging)` pair, in order:
   a. `staging` does not exist → skip.
   b. `try: _os.remove(target + ".bck")` (clear any stale backup).
   c. `rename(target, target + ".bck")` — if `target` exists.
   d. `rename(staging, target)`.
   If (c) or (d) raises `OSError`: stop, restore every pair already past (c) by
   `rename(<t>.bck, <t>)` (best-effort), leave the journal as `committing` so a
   later `repair()` finishes the job, return `False` → `COMMIT_ERR`.
3. Apply `delete_paths` (and `_os.remove(p + ".bck")` for each).
4. `write_journal(core, 0, targets)` — flip the marker; commit is now
   "finished". Return `True` → `COMMIT_OK`.

Because the update flag is only cleared *after* a successful `commit()`
(unchanged from today), an interrupted commit re-enters the boot update loop,
times out with no host, and continues into `main.py` — with `repair()` having
already restored the entire previous generation.

### `UPDATE_START` change

Before the free-space check: `restore.clear_journal(core)`. This frees the
previous generation's `.bck` files so the space check accounts only for the
incoming `.ota` set plus the current running code (which becomes this
generation's `.bck`). Discarding the previous-previous generation here is safe:
it was already superseded by the code currently running.

### Space accounting

`.bck` files are `rename`s of files that already occupy flash, so retaining them
adds **no new peak usage** during a transfer. The existing check
(`free_bytes * 2 < total_bytes * 3`) is unchanged and still correct once
`UPDATE_START` has cleared the prior generation.

## Device cost

- **Hot-path allocation:** none. `commit()` and `repair()` run once per update /
  once per boot respectively — cold paths. `repair()` does one `os.stat` per
  journal line (typically < 10) plus at most one `rename`.
- **Blocking operations:** `repair()` is O(journal length) `stat`/`rename`
  calls with no I/O wait loop — microseconds to low milliseconds, far under the
  ~8388 ms RP2040 WDT cap. No watchdog is armed this early in `boot.py`.
  `commit()` is the existing rename loop with one extra rename and one small
  file write per commit; no new blocking behaviour.
- **Named constants:** `restore._BACKUP_SUFFIX = ".bck"`,
  `restore._DEFAULT_JOURNAL = "otampy-update.journal"`,
  `restore._ATTEMPT_LINE_DEFAULT = 0`,
  `restore._COMMIT_IN_PROGRESS = "committing"`. `OTA_JOURNAL_FILE` is read via
  `_get_config` with the default, matching every other config key.
- **Extra journal write:** `commit()` now writes the journal twice (marker, then
  flip). Two small file writes on the update cold path — negligible.
- **Module release:** `boot.py` and `restore.py` are released together in
  `otampy` under the existing device-lib sync convention; both are grammar
  -checked by `pytest` where mpy-cross is available (see
  `pre_flight_check.py` line 152).

## Build steps

- [x] **1. Journal format + helpers**
  - What changes: new `src/otampy/device/lib/otampy/restore.py` with
    `_BACKUP_SUFFIX`, `_DEFAULT_JOURNAL`, `_journal_path`, `read_journal`,
    `write_journal`, `clear_journal`. `_resolve_path` / `_get_config` reused
    from the existing helpers (import from `.boot` / `.core` as appropriate, or
    lift `_resolve_path` into a shared spot — decide during build, note DRY).
  - Test: new `src/otampy/device/tests/test_restore.py` — round-trip
    `write_journal`/`read_journal`; missing file → `(0, [])`; malformed line 1
    → `(0, [])`; `clear_journal` removes both a listed `<path>.bck` and the
    journal, and is a no-op when nothing exists.
  - Done when: `uv run pytest src/otampy/device/tests/test_restore.py` passes;
    `uv run ruff check .` clean.

- [x] **2. `restore.commit()` — all-or-nothing rename with `.bck`**
  - What changes: add `commit(core, files, delete_paths)` to `restore.py`
    implementing the numbered `commit()` sequence above — `committing` marker
    first, per-pair renames, whole-set best-effort rollback on any `OSError`,
    `delete_paths`, then flip line 1 to `0`. Returns `True`/`False`.
  - Test: `test_restore.py` — (a) successful multi-file commit: new content at
    each target, old content at each `<target>.bck`, journal line 1 is `0`;
    (b) second pair's `rename` fails → **every** already-renamed target is
    back to its original content, journal line 1 still `committing`, returns
    `False`.
  - Done when: those tests pass.

- [x] **3. `restore.repair()` — finish or fix an interrupted commit**
  - What changes: add `repair(core)` to `restore.py` with the two modes from
    its contract row.
  - Test: `test_restore.py` — (a) line 1 `committing`, two paths, both `.bck`
    present (one target also still present as a half-written new file) →
    `repair()` restores **both** from `.bck` and rewrites line 1 to `0`;
    (b) line 1 `0`, one path, target missing + `.bck` present → restores it,
    line 1 stays `0`; (c) line 1 `0`, target present → no-op; (d) no journal →
    no-op.
  - Done when: those tests pass.

- [x] **4. Wire `repair()` into `boot.run()`**
  - What changes: call `restore.repair(core)` in `boot.run()` immediately after
    `_apply_staged_rtc_update()`, before the flag `stat`. Keep the
    module-release dance in `ota.OTA.boot()` working (add `restore` to the same
    teardown if it is imported eagerly; prefer a local import in `run()` so it
    is GC-eligible like `boot` itself).
  - Test: `test_ota_boot.py` — new tests: (a) flag absent, journal line 1 `0`,
    one target missing + `.bck` present → `boot.run(core)` restores it;
    (b) flag absent, journal line 1 `committing`, all `.bck` present →
    `boot.run(core)` restores the whole set and line 1 becomes `0`. Existing
    `test_boot_no_flag_file` and `test_boot_cleans_orphaned_ota_*` still pass.
  - Done when: full `test_ota_boot.py` passes.

- [ ] **5. `UPDATE_START` clears the prior generation**
  - What changes: `restore.clear_journal(core)` at the top of the
    `UPDATE_START` branch, before `_get_free_space()`. (Ordered before step 6 so
    it lands as a harmless no-op first — nothing writes a journal until step 6.)
  - Test: `test_ota_boot.py` — a new test: a pre-existing journal + `.bck` from
    a prior update are gone after an `UPDATE_START` packet is processed.
  - Done when: that test passes.

- [ ] **6. `UPDATE_COMMIT` delegates to `restore.commit()`**
  - What changes: replace the inline rename loop in the `UPDATE_COMMIT` branch
    of `_run_default_update_loop` with a `restore.commit(core, files,
    delete_paths)` call; send `COMMIT_OK` / `COMMIT_ERR` on its return value;
    keep the flag removal and `machine.reset()` afterwards.
  - Test: `test_ota_boot.py::test_boot_handles_full_update_session` updated —
    after commit, each `<target>.bck` holds the pre-update content and the
    journal exists with the committed targets; `.ota` files gone; flag gone.
  - Done when: `test_ota_boot.py` passes, including the updated full-session
    test.

- [ ] **7. `.bck` orphan cleanup on normal boot**
  - What changes: extend `_cleanup_orphaned_ota` (or add a sibling called from
    the same no-flag path in `boot.run()`) to remove `<x>.bck` files whose
    target is not in the current journal.
  - Test: `test_ota_boot.py` — normal boot with an orphan `stale.py.bck` (no
    journal) removes it; a `.bck` listed in the journal is kept.
  - Done when: that test passes.

- [ ] **8. Docs + changelog**
  - What changes: `docs/protocol.md` §2.4 — `UPDATE_COMMIT` is now all-or-nothing
    (whole-set rollback on failure), retains `<target>.bck`, and writes
    `OTA_JOURNAL_FILE`; `UPDATE_START` discards the prior generation. Replace the
    closing paragraph that says an interruption "can still leave a mixed-version
    deployment" — that is no longer true within one `UPDATE_COMMIT`.
    `docs/architecture.md` — add `OTA_JOURNAL_FILE` to the `configota.py` block;
    a short paragraph under the boot-time update section on retain-previous +
    all-or-nothing commit + `repair()`; fix the line that currently says the
    commit "is a per-file rename sequence, not a power-loss-atomic filesystem
    transaction" to describe the marker/repair recovery. `CHANGELOG.md` — an
    `Unreleased` entry.
  - Test: none — docs.
  - Done when: `docs/protocol.md`, `docs/architecture.md`, `CHANGELOG.md`
    reflect the new behaviour; no stale claim that commit deletes the target or
    leaves a mixed-version tree.

## Verification

- **Host:** `python3 .agents/scripts/pre_flight_check.py` (ruff + full pytest,
  mirrors CI). Per-step: `uv run pytest src/otampy/device/tests/test_restore.py
  src/otampy/device/tests/test_ota_boot.py -q`.
- **Hardware:** on a Pico W with `otampy` deployed:
  1. `otampy upd main.py` with a trivially changed `main.py`. After the device
     reboots, `otampy ls /` shows `main.py.bck` and `otampy-update.journal`;
     `otampy cat /otampy-update.journal` shows `0` then `/main.py`;
     `otampy cat /main.py.bck` is the pre-update content.
  2. Update two files at once (`otampy upd main.py lib/<mod>.py`) and pull power
     *during* the commit (retry a few times). On next boot the device reaches
     `main.py`, `otampy ping` → `PONG`, and **both** files hold the pre-update
     content — the whole set rolled back, not a mix. `otampy cat
     /otampy-update.journal` line 1 is `0` (repair flipped it).
  3. `otampy upd main.py` a second time: the first generation's
     `main.py.bck` is replaced by the new pre-update content, not stacked.
- **Manual:** Simon runs step 1 and 3 above and confirms the `.bck` file and
  journal look right; deliberately deploys a `main.py` that raises on import,
  confirms the `.bck` still holds the good version (recovery is still manual at
  this sub-task — that is the point of sub-task 2).

## Risks and open questions

- **`rename` over an existing destination.** littlefs2 permits
  `rename(staging, target)` when `target` exists and treats it atomically; but
  the commit sequence renames `target` out of the way first, so this only
  matters for `<target>.bck` if a stale `.bck` survived. `clear_journal` and the
  orphan sweep should keep that from happening; `commit()` should still
  `try: _os.remove(target + ".bck")` defensively before step 2. **Verify on
  hardware** that no `EEXIST` is raised on the target Pico's filesystem.
- **`VfsFat` fallback.** If any deployment uses FAT rather than littlefs,
  `rename` onto an existing name raises `EEXIST`. `commit()` removing the `.bck`
  first (above) covers step 2; step 3's `target` is guaranteed absent by step 2.
  Note but do not build a FAT-specific path unless hardware shows one is needed.
- **Journal vs. `configota.py` `OTA_JOURNAL_FILE` typo.** A user pointing the
  journal at a real source path would let a commit clobber it. Low risk (it is
  an opt-in override with a safe default) — a one-line note in the docs that the
  value must be a dedicated scratch path is enough.
- **`repair()` is itself best-effort.** A power loss *during* whole-set restore
  leaves the `committing` marker in place, so the next boot's `repair()` picks
  up where it left off and re-restores from the still-present `.bck` files. It
  converges over reboots. The only unrecoverable case is losing a `.bck` file's
  rename mid-flight *and* its target — vanishingly unlikely for a single
  metadata op, and no worse than today's exposure. Documented, not engineered
  away (that is the dual-slot layout, explicitly out of scope).
- **`repair()` running before the WDT but also before logging is meaningful.**
  `NullLogger` swallows everything; a file logger may not be ready. Keep
  `repair()` silent-by-default; a single `core.logger.info` on an actual
  restore is fine.
- **Interaction with `_apply_staged_rtc_update`.** The staged RTC helper is a
  real file (`_otampy_set_rtc.py`) transferred in the same manifest. It will get
  a `.bck` like any other file. Harmless — it self-deletes on next boot — but
  the orphan sweep should not choke on `_otampy_set_rtc.py.bck`. Covered by the
  "not in journal → remove" rule.

## Notes for the build

- **DRY — two commit helpers now exist.** `filecopy._commit` (runtime single
  file, transient `<target>.bak`, prefers `os.replace`) and `restore.commit`
  (boot-time transactional set, retained `<target>.bck`, journalled). They are
  genuinely different lifecycles — do **not** merge them. Add a comment in each
  pointing at the other so a future change to rename/backup logic considers
  both.
- `_resolve_path`, `_ticks_ms`, `_get_free_space`, `_make_dirs` already live in
  `boot.py`. `restore.py` needs `_resolve_path` and `_get_config`. Either import
  them (`from .boot import _resolve_path`) or, if that creates an awkward import
  cycle with `boot` importing `restore`, lift `_resolve_path` into `core.py`
  alongside `_get_config` and re-export. Decide in step 1; keep it to one copy.
- The `files` list in `_run_default_update_loop` is flat
  `[target, staging, target, staging, …]` — `restore.commit` must accept that
  shape directly, not a list of tuples, to avoid an allocation on the device.
- `delete_paths` in the commit branch are resolved paths already; apply them
  after the renames exactly as today, and additionally attempt
  `_os.remove(path + ".bck")` for each so a deleted target leaves no orphan
  backup.
- Device tests load the library as `device_otampy` (see
  `src/otampy/device/tests/conftest.py`); import `from device_otampy import
  restore`.
- Keep every new function non-raising: all of this runs under `boot.run()` with
  no `try` around it in the example `boot.py`, and the deferred TODO item about
  an unhandled `boot.py` crash is a live concern.
