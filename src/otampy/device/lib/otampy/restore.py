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
