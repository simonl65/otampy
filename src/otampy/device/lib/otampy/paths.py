"""
paths.py -- target-path constraints for CP_START / CAT / RM.

``CP_START:<target>:<size>:<sha256>`` took its target straight from the
command with no directory restriction and no ``..`` rejection, so a
crafted ``CP_START:main.py:...`` (or ``boot.py``, or any ``lib/`` path)
overwrote device code on the next reboot -- persistent remote code
execution for anyone who could reach the link.

Two independent rules, deliberately:

* ``..`` is **always** rejected. There is no legitimate traversal on a
  MicroPython filesystem rooted at ``/``, and it is the traversal
  primitive itself.
* A prefix allowlist applies only when ``OTA_ALLOWED_PATH_PREFIXES`` is
  configured. Left unset, every path that is not a traversal is allowed,
  so existing deployments behave exactly as before.

Nothing here raises -- callers sit under ``manager.poll()``.
"""

from .core import _get_config

CONFIG_KEY = "OTA_ALLOWED_PATH_PREFIXES"
FORBIDDEN_REPLY = b"ERROR:Forbidden path"


def normalise(path):
    """A canonical form of ``path``, or ``None`` if it escapes the root.

    Leading ``/`` is dropped because the device's working directory *is*
    the root, so ``/main.py`` and ``main.py`` are the same file and must
    compare equal. Empty and ``.`` segments collapse. Any ``..`` segment
    makes the whole path unusable -- resolving it would be the bug.
    """
    if not path:
        return None
    try:
        segments = path.split("/")
    except AttributeError:  # not a string
        return None
    parts = []
    for segment in segments:
        if not segment or segment == ".":
            continue
        if segment == "..":
            return None
        parts.append(segment)
    return "/".join(parts)


def _as_prefix_list(prefixes):
    if not prefixes:
        return ()
    if isinstance(prefixes, str):
        return tuple(p for p in prefixes.split(",") if p.strip())
    return tuple(prefixes)


def _within(path, prefix):
    """True if ``path`` is ``prefix`` itself or sits underneath it.

    The boundary check matters: a plain ``startswith`` would let the
    prefix ``data`` admit ``database.db``.
    """
    if not prefix:  # a prefix of "/" normalises to "" -- the whole root
        return True
    return path == prefix or path.startswith(prefix + "/")


def is_allowed(path, prefixes=None):
    """True if ``path`` may be read or written by a remote command."""
    normalised = normalise(path)
    if not normalised:
        return False
    allowed = _as_prefix_list(prefixes)
    if not allowed:
        return True
    for prefix in allowed:
        candidate = normalise(prefix.strip())
        if candidate is not None and _within(normalised, candidate):
            return True
    return False


def allowed_for(core, path):
    """``is_allowed`` against this device's configured prefixes."""
    return is_allowed(path, _get_config(core.config, CONFIG_KEY))
