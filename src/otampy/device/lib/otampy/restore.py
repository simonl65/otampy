"""Retain-previous update journal and all-or-nothing boot-time commit.

Two commit helpers exist in this library and they are deliberately separate:

* ``filecopy._commit`` -- runtime, single file, *transient* ``<target>.bak``,
  prefers ``os.replace``. The backup exists only for the length of one copy.
* ``restore.commit`` (this module) -- boot-time, a whole transactional set,
  *retained* ``<target>.bck``, journalled so an interrupted commit can be
  reversed on the next boot.

They have genuinely different lifecycles, so they are not merged. A change to
rename/backup logic in one should consider the other.

Every function here runs under ``boot.run()`` with no ``try`` around it, so
none of them may raise.
"""

try:
    import uos as _os
except ImportError:
    import os as _os

from .core import _get_config, _resolve_path

_BACKUP_SUFFIX = ".bck"
_DEFAULT_JOURNAL = "otampy-update.journal"
_ATTEMPT_LINE_DEFAULT = 0

# Journal line 1 grammar. "committing" means a commit is partway through;
# a base-10 integer is a committed candidate on trial, counting boots; and
# "confirmed" means the candidate was accepted and is no longer counted.
_STATE_COMMITTING = "committing"
_STATE_TRIAL = "trial"
_STATE_CONFIRMED = "confirmed"

# UPDATE_STATE label for a candidate that is no longer counting boots.
_LABEL_STABLE = "stable"

# Boots into an unconfirmed candidate before the device auto-restores the
# previous generation. Overridden by the OTA_TRIAL_BOOTS config key.
_DEFAULT_TRIAL_BOOTS = 3

# trial() returns this so boot.run() knows to machine.reset() onto the
# just-restored previous generation.
_ROLLED_BACK = "rolled_back"

# rollback() returns this when a commit marker is present: the caller must
# refuse the request rather than reset. Distinct from 0 ("nothing to revert").
# Private to this module -- rollback_result() folds it into a reply so it
# never crosses a module boundary.
_ROLLBACK_BUSY = -1

# ROLLBACK wire replies. Shared by manager.poll and the boot-time recovery
# window, which is why they live here rather than at either call site.
_REPLY_ROLLBACK_OK = b"ROLLBACK_OK"
_REPLY_ROLLBACK_BUSY = b"ROLLBACK_ERR:Commit in flight"
_REPLY_ROLLBACK_NONE = b"ROLLBACK_ERR:Nothing to roll back"


def _journal_path(core):
    return _resolve_path(
        str(_get_config(core.config, "OTA_JOURNAL_FILE", _DEFAULT_JOURNAL))
    )


def read_journal(core):
    """Return ``(attempt, state, paths)``. Never raises.

    ``state`` is one of ``_STATE_COMMITTING`` / ``_STATE_TRIAL`` /
    ``_STATE_CONFIRMED``. A missing or empty journal is
    ``(0, _STATE_CONFIRMED, [])`` -- nothing is on trial, so nothing counts it.
    A first line that is none of the two sentinels nor a base-10 integer is
    treated as ``committing`` -- fail safe, meaning "restore everything".
    """
    try:
        with open(_journal_path(core)) as handle:
            lines = handle.read().split("\n")
    except OSError:
        return (_ATTEMPT_LINE_DEFAULT, _STATE_CONFIRMED, [])

    if not lines or not lines[0]:
        return (_ATTEMPT_LINE_DEFAULT, _STATE_CONFIRMED, [])

    paths = [line for line in lines[1:] if line]

    first = lines[0]
    if first == _STATE_COMMITTING:
        return (_ATTEMPT_LINE_DEFAULT, _STATE_COMMITTING, paths)
    if first == _STATE_CONFIRMED:
        return (_ATTEMPT_LINE_DEFAULT, _STATE_CONFIRMED, paths)
    try:
        return (int(first), _STATE_TRIAL, paths)
    except ValueError:
        return (_ATTEMPT_LINE_DEFAULT, _STATE_COMMITTING, paths)


def write_journal(core, line1, paths):
    """Write the journal. Returns ``True`` on success, ``False`` on OSError."""
    try:
        with open(_journal_path(core), "w") as handle:
            handle.write(str(line1))
            handle.write("\n")
            for path in paths:
                handle.write(path)
                handle.write("\n")
        return True
    except OSError:
        return False


def clear_journal(core):
    """Discard the retained generation: every ``.bck``, then the journal."""
    _, _, paths = read_journal(core)
    for path in paths:
        try:
            _os.remove(path + _BACKUP_SUFFIX)
        except OSError:
            pass
    try:
        _os.remove(_journal_path(core))
    except OSError:
        pass


def _exists(path):
    try:
        _os.stat(path)
        return True
    except OSError:
        return False


def commit(core, files, delete_paths):
    """All-or-nothing commit of a staged update set. Never raises.

    ``files`` is the flat ``[target, staging, target, staging, ...]`` list the
    boot update loop already builds. Writes the journal with a ``committing``
    marker and every target, then for each pair renames ``target`` to
    ``<target>.bck`` and ``staging`` into place. On any ``OSError`` the whole
    set is rolled back from the ``.bck`` files and ``False`` is returned; the
    journal stays ``committing`` so a later ``repair()`` can finish reversing
    it. On full success line 1 is flipped to ``0`` and ``True`` returned.
    """
    targets = [
        files[i] for i in range(0, len(files), 2) if _exists(files[i + 1])
    ]
    write_journal(core, _STATE_COMMITTING, targets)

    done = []
    for i in range(0, len(files), 2):
        target = files[i]
        staging = files[i + 1]
        if not _exists(staging):
            continue
        backup = target + _BACKUP_SUFFIX
        try:
            _os.remove(backup)
        except OSError:
            pass
        had_target = _exists(target)
        try:
            if had_target:
                _os.rename(target, backup)
            # Recorded before the staging rename: if that step fails, the
            # target has already moved to .bck and must be rolled back too.
            done.append((target, backup, had_target))
            _os.rename(staging, target)
        except OSError as err:
            core.logger.error(f"Commit failed for {target}: {err}")
            _rollback(done)
            return False

    for path in delete_paths:
        for candidate in (path, path + _BACKUP_SUFFIX):
            try:
                _os.remove(candidate)
            except OSError:
                pass

    write_journal(core, _ATTEMPT_LINE_DEFAULT, targets)
    return True


def restore_all(core):
    """Restore the whole retained generation, then discard the journal.

    Rename every journalled ``<path>.bck`` that exists back over its target
    (removing a partial target first), then remove the journal file. Returns
    the count restored. Never raises. Bounded by the journal length.
    """
    _, _, paths = read_journal(core)
    restored = 0
    for target in paths:
        backup = target + _BACKUP_SUFFIX
        if not _exists(backup):
            continue
        try:
            _os.remove(target)
        except OSError:
            pass
        try:
            _os.rename(backup, target)
            core.logger.info(f"restore_all: restored {target} from backup")
            restored += 1
        except OSError:
            pass
    try:
        _os.remove(_journal_path(core))
    except OSError:
        pass
    return restored


def repair(core):
    """Finish or reverse an interrupted commit. Never raises.

    ``committing`` (or an unrecognised) line 1 means a commit was partway
    through: ``restore_all()`` puts the whole previous generation back and
    removes the journal. A ``trial`` line 1 (an integer) means the commit
    finished: only restore paths whose target vanished but whose ``.bck``
    survived, and rewrite the journal **only if** something was restored
    (F-07). ``confirmed`` or an empty journal is a no-op.
    """
    attempt, state, paths = read_journal(core)
    if not paths or state == _STATE_CONFIRMED:
        return
    if state == _STATE_COMMITTING:
        restore_all(core)
        return

    restored = False
    for target in paths:
        backup = target + _BACKUP_SUFFIX
        if _exists(backup) and not _exists(target):
            try:
                _os.rename(backup, target)
                core.logger.info(f"repair: restored missing {target}")
                restored = True
            except OSError:
                pass

    if restored:
        write_journal(core, attempt, paths)


def confirm(core):
    """Take the running candidate off trial. Never raises.

    Flips a ``trial`` journal's line 1 to ``confirmed``, keeping the retained
    path list so the previous generation stays recoverable until the next
    ``UPDATE_START``. Idempotent: ``True`` when the candidate is (now or
    already) confirmed or there is nothing on trial; ``False`` only while a
    commit marker is present.
    """
    _, state, paths = read_journal(core)
    if state == _STATE_COMMITTING:
        return False
    if state == _STATE_TRIAL:
        write_journal(core, _STATE_CONFIRMED, paths)
    return True


def rollback(core):
    """Revert to the retained generation on the host's command. Never raises.

    Returns ``_ROLLBACK_BUSY`` when a ``committing`` marker is present --
    ``repair()`` owns that state, so the caller must not reset. Returns ``0``
    when there is no journal or no journalled ``<path>.bck`` survives: there is
    nothing to revert, and the journal is left exactly as it was. Otherwise
    delegates to ``restore_all()`` and returns its count, at which point the
    caller resets onto the restored generation.

    The ``.bck`` pre-scan is not redundant. ``restore_all()`` removes the
    journal unconditionally, so calling it with nothing to restore would take a
    trialling candidate off trial -- stopping the boot counter -- while
    reporting failure to the host.
    """
    _, st, paths = read_journal(core)
    if st == _STATE_COMMITTING:
        return _ROLLBACK_BUSY
    for target in paths:
        if _exists(target + _BACKUP_SUFFIX):
            return restore_all(core)
    return 0


def rollback_result(core):
    """Map ``rollback()`` onto ``(reply_bytes, restored_count)``. Never raises.

    The reply/refusal mapping the runtime command surface and the boot-time
    recovery window share. ``restored_count`` is non-zero only when the caller
    should reset onto the restored generation; it is also the number to log.
    """
    restored = rollback(core)
    if restored == _ROLLBACK_BUSY:
        return (_REPLY_ROLLBACK_BUSY, 0)
    if restored == 0:
        return (_REPLY_ROLLBACK_NONE, 0)
    return (_REPLY_ROLLBACK_OK, restored)


def trial(core):
    """Advance the trial-boot counter; auto-restore past the limit. Never raises.

    Called from ``boot.run()`` on every boot. A no-op (returns ``None``, no
    write) unless a candidate is on trial. Otherwise increments the counter;
    once it exceeds ``OTA_TRIAL_BOOTS`` the whole previous generation is put
    back via ``restore_all()`` and ``_ROLLED_BACK`` is returned so
    ``boot.run()`` resets onto it. The trigger is therefore a reboot during
    the trial window -- a crash, panic, brownout, watchdog, or power cycle.
    """
    attempt, st, paths = read_journal(core)
    if st != _STATE_TRIAL:
        return None
    attempt += 1
    limit = _get_config(core.config, "OTA_TRIAL_BOOTS", _DEFAULT_TRIAL_BOOTS)
    if attempt > limit:
        core.logger.warning(
            f"trial: candidate failed {attempt - 1} boots, restoring previous"
        )
        restore_all(core)
        return _ROLLED_BACK
    write_journal(core, attempt, paths)
    return None


def state(core):
    """Return ``(label, attempt)`` for ``UPDATE_STATE``. Never raises.

    ``("trial", n)`` while a candidate is counting boots, ``("stable", 0)``
    once confirmed or with no journal. A stray ``committing`` marker (not seen
    at runtime -- ``repair()`` clears it first) reports ``("trial", 0)``.
    """
    attempt, st, _ = read_journal(core)
    if st == _STATE_TRIAL:
        return (_STATE_TRIAL, attempt)
    if st == _STATE_COMMITTING:
        return (_STATE_TRIAL, 0)
    return (_LABEL_STABLE, 0)


def _rollback(done):
    """Best-effort restore of pairs already committed by ``commit()``."""
    for target, backup, had_target in done:
        try:
            _os.remove(target)
        except OSError:
            pass
        if had_target:
            try:
                _os.rename(backup, target)
            except OSError:
                pass
