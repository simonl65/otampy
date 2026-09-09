"""Authenticated command envelope: AUTH:<counter>:<hex-mac>:<command>.

Off unless OTA_REQUIRE_AUTH is set, so existing deployments are unaffected
and this module is never even imported. Both the runtime command surface
(`manager.poll`) and the boot-time recovery window (`boot._run_boot_listen`)
gate on it, which is why it lives here rather than in `manager` -- the
window must not drag the whole runtime command surface into the boot phase.
"""

from .core import _get_config

_AUTH_PREFIX = "AUTH"
_AUTH_FIELDS = 4
_REPLAY_FLOOR_FILE = "otampy-replay-floor"
_UNAUTHENTICATED = b"ERROR:Unauthenticated"
_REPLAYED = b"ERROR:Replayed"


def _replay_floor_path(core):
    return _get_config(core.config, "OTA_REPLAY_FLOOR_FILE", _REPLAY_FLOOR_FILE)


def _auth_blocks(core):
    """Cached HMAC key blocks, or False if no usable key is configured.

    Derived once and kept on `core` -- the same flat-attribute approach
    filecopy uses for `_copy_state`. Deriving them per command would put
    two 64-byte allocations on every command.
    """
    blocks = getattr(core, "_auth_blocks", None)
    if blocks is None:
        from .auth import derive_key_blocks, key_from_hex

        key = key_from_hex(_get_config(core.config, "COMMAND_AUTH_KEY"))
        if key is None:
            core.logger.error(
                "OTA_REQUIRE_AUTH is set but COMMAND_AUTH_KEY is missing or "
                "malformed (needs 64 hex chars) -- rejecting every command"
            )
            blocks = False
        else:
            blocks = derive_key_blocks(key)
        core._auth_blocks = blocks
    return blocks


def _replay_guard(core):
    guard = getattr(core, "_replay_guard", None)
    if guard is None:
        from .replay import ReplayGuard, load_floor

        guard = ReplayGuard(load_floor(_replay_floor_path(core)))
        core._replay_guard = guard
    return guard


def authenticate(core, cmd_str):
    """Unwrap and verify an `AUTH:` envelope.

    Returns the inner command string, or None if the command must be
    dropped. Never raises: the caller is the application's main loop.
    """
    blocks = _auth_blocks(core)
    if not blocks:
        core.transport.reply(_UNAUTHENTICATED)
        return None

    fields = cmd_str.split(":", 3)
    if (
        len(fields) != _AUTH_FIELDS
        or fields[0] != _AUTH_PREFIX
        or not fields[3]
    ):
        core.logger.warning("Rejected a command with no auth envelope")
        core.transport.reply(_UNAUTHENTICATED)
        return None

    import binascii

    from .auth import signed_bytes, verify

    try:
        counter = int(fields[1])
        mac = binascii.unhexlify(fields[2])
    except ValueError:
        core.logger.warning("Rejected a command with a malformed auth envelope")
        core.transport.reply(_UNAUTHENTICATED)
        return None

    inner = fields[3]
    if not verify(blocks, signed_bytes(counter, inner.encode()), mac):
        core.logger.warning("Rejected a command with a bad MAC")
        core.transport.reply(_UNAUTHENTICATED)
        return None

    # Verification must come first. A forged frame that reached the replay
    # guard could poison last_seen with a huge counter and lock the real
    # host out until the next reboot.
    if not _replay_guard(core).accept(counter):
        core.logger.warning(f"Rejected a replayed command counter: {counter}")
        core.transport.reply(_REPLAYED)
        return None

    return inner


def persist_replay_floor(core):
    """Best-effort: record the replay counter before the board resets.

    Only meaningful when auth is on -- no guard exists otherwise. Never
    raises and never blocks the reset: losing the floor costs precision,
    not safety, because the host's wall-clock-seeded counter re-floors
    last_seen on its first command after the reboot.

    Callers keep the `core._replay_guard is not None` check at their own
    call site so a no-auth device never imports this module at all; the
    guard is repeated here because the check and the import are separable.
    """
    guard = getattr(core, "_replay_guard", None)
    if guard is None:
        return
    try:
        if not guard.persist_floor(_replay_floor_path(core)):
            core.logger.error("Failed to persist the command replay floor")
    except Exception as e:  # noqa: BLE001 -- the reset must happen regardless
        core.logger.error(f"Failed to persist the command replay floor: {e}")
