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
_COMMIT_IN_PROGRESS = "committing"


def _journal_path(core):
    return _resolve_path(
        _get_config(core.config, "OTA_JOURNAL_FILE", _DEFAULT_JOURNAL)
    )


def read_journal(core):
    """Return ``(attempt, in_progress, paths)``. Never raises.

    A missing or empty journal is ``(0, False, [])``. A first line that is
    neither the ``committing`` sentinel nor a base-10 integer is treated as
    ``in_progress`` -- fail safe, meaning "restore everything".
    """
    try:
        with open(_journal_path(core)) as handle:
            lines = handle.read().split("\n")
    except OSError:
        return (_ATTEMPT_LINE_DEFAULT, False, [])

    if not lines or not lines[0]:
        return (_ATTEMPT_LINE_DEFAULT, False, [])

    paths = [line for line in lines[1:] if line]

    first = lines[0]
    if first == _COMMIT_IN_PROGRESS:
        return (_ATTEMPT_LINE_DEFAULT, True, paths)
    try:
        return (int(first), False, paths)
    except ValueError:
        return (_ATTEMPT_LINE_DEFAULT, True, paths)


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
    write_journal(core, _COMMIT_IN_PROGRESS, targets)

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
