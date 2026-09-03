"""
replay.py -- device-side replay guard for authenticated channel-0 commands.

The host issues a strictly-increasing counter
(``max(persisted + 1, unix_seconds)``) and includes it in the signed
bytes, so it cannot be edited in flight. This module remembers the
highest counter already accepted.

Two layers:

* **RAM** (``ReplayGuard.last_seen``) covers replays while the device is
  up. The test is ``counter > last_seen``, never ``== last_seen + 1``:
  the host issues a fresh counter per retry attempt and seeds from the
  wall clock, so gaps are normal and must not wedge the guard.
* **Flash** (``persist_floor`` / ``load_floor``) covers the one case RAM
  cannot -- a reboot commanded over the link, where a captured ``RB``
  could otherwise be replayed once the device came back. The write
  happens only on the three commands that reset the board, immediately
  before the reset.

The floor is a precision refinement, not load-bearing: if it is missing
or corrupt, ``load_floor`` returns ``0`` and the host's wall-clock-seeded
counter re-floors ``last_seen`` on its first command. That is why every
failure path here degrades to ``0`` or ``False`` and nothing raises --
this runs under ``manager.poll()``, inside the application's main loop,
and the ``persist_floor`` caller is about to ``machine.reset()``.
"""

# A stored value outside the wire's range is corruption, not a counter.
# Trusting one would reject every genuine command until the file was
# deleted by hand.
_U32_MAX = 0xFFFFFFFF


def load_floor(path):
    """Highest counter accepted before the last reset, or ``0``.

    Returns ``0`` for a missing file, unreadable flash, empty or
    unparseable contents, or a value outside the u32 wire range. Never
    raises.
    """
    if not path:
        return 0
    try:
        with open(path) as f:
            value = int(f.read().strip())
    except (OSError, ValueError):
        return 0
    if value < 0 or value > _U32_MAX:
        return 0
    return value


class ReplayGuard:
    """Remembers the highest command counter already accepted."""

    def __init__(self, floor=0):
        self.last_seen = floor

    def accept(self, counter):
        """``True`` if ``counter`` is fresh, advancing the guard.

        A rejected counter must **not** advance ``last_seen`` -- otherwise
        one forged high counter would lock the real host out until the
        next reboot. Verification therefore has to happen before this is
        called, so a forged frame never reaches it at all.
        """
        if counter > self.last_seen:
            self.last_seen = counter
            return True
        return False

    def persist_floor(self, path):
        """Write ``last_seen`` as the boot floor. ``True`` if it stuck.

        Uses the same write-then-close pattern as ``manager.py``'s
        update-request flag file: the close commits to littlefs, and that
        pattern has survived genuine power-cycles in this codebase. A
        failure is reported, never raised -- the caller is about to reset
        the board and must do so regardless.
        """
        if not path:
            return False
        try:
            with open(path, "w") as f:
                f.write(str(self.last_seen))
        except OSError:
            return False
        return True
