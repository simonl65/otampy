import machine

try:
    import uos as _os
except ImportError:
    import os as _os

from urst import constants as _urst_constants  # type: ignore

from .core import _get_config

_MAX_FRAGMENT_DATA = _urst_constants.MAX_PAYLOAD_SIZE - 6
_MAX_RESPONSE_SIZE = _MAX_FRAGMENT_DATA * 255
_RTC_HELPER_FILE = "_otampy_set_rtc.py"

# Authenticated command envelope: AUTH:<counter>:<hex-mac>:<command>.
# Off unless OTA_REQUIRE_AUTH is set, so existing deployments are
# unaffected and the auth modules are never even imported.
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


def _authenticate(core, cmd_str):
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
        core.logger.warning(
            "Rejected a command with a malformed auth envelope"
        )
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


def _persist_replay_floor(core):
    """Best-effort: record the replay counter before the board resets.

    Only meaningful when auth is on -- no guard exists otherwise. Never
    raises and never blocks the reset: losing the floor costs precision,
    not safety, because the host's wall-clock-seeded counter re-floors
    last_seen on its first command after the reboot.
    """
    guard = getattr(core, "_replay_guard", None)
    if guard is None:
        return
    try:
        if not guard.persist_floor(_replay_floor_path(core)):
            core.logger.error("Failed to persist the command replay floor")
    except Exception as e:  # noqa: BLE001 -- the reset must happen regardless
        core.logger.error(f"Failed to persist the command replay floor: {e}")


def _do_callback(core, callback=None):
    if callback is not None:
        try:
            core.logger.debug("Calling application callback")
            callback()
        except Exception as e:
            core.logger.error(f"Error in application callback: {e}")


def _stage_rtc_update(core, parts):
    if len(parts) != 9:
        core.transport.reply(b"RTC_STAGE_ERR")
        return
    try:
        time_tuple = tuple(int(value) for value in parts[1:])
    except ValueError:
        core.transport.reply(b"RTC_STAGE_ERR")
        return
    try:
        with open(_RTC_HELPER_FILE, "w") as helper:
            helper.write("import machine\nimport os\ntry:\n")
            helper.write(f" machine.RTC().datetime({time_tuple!r})\n")
            helper.write("except Exception:\n pass\nfinally:\n")
            helper.write(
                f" try:\n  os.remove({_RTC_HELPER_FILE!r})\n except OSError:\n  pass\n"
            )
    except OSError as error:
        core.logger.error(f"Failed to stage RTC update: {error}")
        core.transport.reply(b"RTC_STAGE_ERR")
        return
    core.transport.reply(b"RTC_STAGE_OK")


def _call_heartbeat(heartbeat):
    if heartbeat is None:
        return
    try:
        heartbeat()
    except Exception:
        # A caller's heartbeat (e.g. feeding a hardware watchdog) must
        # never be able to abort an in-progress transfer -- the transfer
        # itself already has its own error handling below.
        pass


def _send_response(transport, total_size, parts, heartbeat=None):
    if total_size > _MAX_RESPONSE_SIZE:
        transport.reply(b"ERROR:Response too large")
        return

    protocol = getattr(transport, "protocol", None)
    if (
        total_size <= _MAX_FRAGMENT_DATA
        or protocol is None
        or not hasattr(transport, "_msg_id")
    ):
        response = bytearray()
        for part in parts:
            response.extend(part)
        transport.reply(bytes(response))
        return

    # Replying with an already-fragmented payload bypasses Urst.send()'s
    # own fragmentation (to keep gc.collect() calls between fragments for
    # low-memory devices), so it must independently echo the request's
    # Request ID (§5.8.3) and send ABORT on retry exhaustion (§5.7.2) --
    # neither of those come for free outside Urst.send().
    #
    # `heartbeat`, if given, is called once per fragment sent (same
    # cadence as `collect()` above) -- this whole loop runs inside one
    # `poll()` call, and each fragment is its own reliable send-and-wait
    # for an ACK, so a response large enough to need many fragments can
    # legitimately take far longer than a single `poll()` call normally
    # would. A caller feeding a hardware watchdog only once per `poll()`
    # call (i.e. once per completed round of its own main loop) would
    # otherwise see no progress for the whole duration of one large CAT/LS
    # response and could mistake it for a hang.
    request_id = transport.last_request_id
    total_fragments = (
        total_size + _MAX_FRAGMENT_DATA - 1
    ) // _MAX_FRAGMENT_DATA
    import gc

    collect = gc.collect
    message_id = transport._msg_id
    transport._msg_id = (message_id + 1) & 0xFF
    fragment = bytearray()
    fragment_number = 0

    for part_number, part in enumerate(parts):
        offset = 0
        while offset < len(part):
            remaining = _MAX_FRAGMENT_DATA - len(fragment)
            end = offset + remaining
            fragment.extend(part[offset:end])
            offset = end
            if len(fragment) == _MAX_FRAGMENT_DATA:
                header = bytes(
                    (
                        message_id,
                        fragment_number,
                        total_fragments,
                        len(fragment),
                    )
                )
                if not protocol.send_reliable(
                    _urst_constants.FRAME_FRAG,
                    header + bytes(fragment),
                    request_id,
                ):
                    if not protocol.session_reset_during_send:
                        protocol.send_abort(message_id, request_id)
                        transport.reply(b"ERROR:Fragment transfer failed")
                    # else: a CONNECT reset the peer's session mid-send
                    # (US-003, urst-mpy's send_reliable() already gave up
                    # without retrying). Both ABORT and this reply would
                    # reference a message the new session never asked
                    # about, becoming the next stale frame -- exactly the
                    # failure this suppression exists to stop.
                    return
                fragment_number += 1
                fragment = bytearray()
                collect()
                _call_heartbeat(heartbeat)
        if part_number & 7 == 7:
            collect()

    if fragment:
        header = bytes(
            (
                message_id,
                fragment_number,
                total_fragments,
                len(fragment),
            )
        )
        if not protocol.send_reliable(
            _urst_constants.FRAME_FRAG,
            header + bytes(fragment),
            request_id,
        ):
            if not protocol.session_reset_during_send:
                protocol.send_abort(message_id, request_id)
                transport.reply(b"ERROR:Fragment transfer failed")
            # else: see the matching guard above -- a CONNECT already
            # reset the peer's session, so neither ABORT nor this reply
            # has anywhere valid to land.
            return
        fragment = None
        collect()
        _call_heartbeat(heartbeat)


def _file_parts(source, size):
    """Yield one fixed-size CAT snapshot without buffering the whole file."""
    yield b"CAT_OK:"
    remaining = size
    while remaining:
        chunk = source.read(min(_MAX_FRAGMENT_DATA, remaining))
        if not chunk:
            return
        yield chunk
        remaining -= len(chunk)


def _directory_entries(path):
    try:
        entries = _os.ilistdir(path)
        detailed = True
    except AttributeError:
        entries = _os.listdir(path)
        detailed = False

    for entry in entries:
        if detailed:
            item = entry[0]
            item_is_dir = entry[1] & 0x4000
        else:
            item = entry
            full_path = path.rstrip("/") + "/" + item
            try:
                item_is_dir = _os.stat(full_path)[0] & 0x4000
            except OSError:
                item_is_dir = False
        if item_is_dir:
            item += "/"  # type: ignore
        yield item.encode()  # type: ignore


def _directory_size(path):
    import gc

    total_size = len(b"LS_OK:")
    for entry_count, entry in enumerate(_directory_entries(path)):
        total_size += len(entry)
        if entry_count:
            total_size += 1
        if entry_count & 7 == 7:
            gc.collect()
    gc.collect()
    return total_size


def _directory_parts(path):
    yield b"LS_OK:"
    first = True
    for entry in _directory_entries(path):
        if first:
            first = False
        else:
            yield b","
        yield entry


def poll(core, callback=None, heartbeat=None):
    """
    Check the transport (UART) for any pending commands and dispatch them.

    `heartbeat`, if given, is called periodically during a large CAT/LS
    response's fragment transfer -- see `_send_response`'s own comment.
    Distinct from `callback`, which is a one-shot hook called once, right
    before a reboot (RB/UPDATE_REQUEST): `heartbeat` fires zero or more
    times per `poll()` call and must be safe to call that way (e.g.
    feeding a hardware watchdog), not "about to reset" cleanup.
    """
    packet = core.transport.read()
    if not packet:
        return

    # Decode if bytes
    if isinstance(packet, bytes):
        try:
            cmd_str = packet.decode("utf-8").strip()
        except UnicodeError:
            core.logger.warning("Received invalid non-UTF-8 packet")
            return
    else:
        cmd_str = str(packet).strip()

    if not cmd_str:
        return

    # Authenticated command surface (opt-in). When OTA_REQUIRE_AUTH is
    # set, every command must arrive inside a verified AUTH: envelope;
    # what continues below is the unwrapped inner command, so each
    # command's own grammar is untouched.
    if _get_config(core.config, "OTA_REQUIRE_AUTH", False):
        cmd_str = _authenticate(core, cmd_str)
        if cmd_str is None:
            return

    # Parse command and optional arguments
    parts = cmd_str.split(":")
    cmd = parts[0]

    if cmd == "PING":
        core.transport.reply(b"PONG")
    elif cmd == "MPY":
        import sys

        value = getattr(sys.implementation, "_mpy", None)
        bits = 0
        maximum = sys.maxsize
        while maximum:
            bits += 1
            maximum >>= 1
        if value is None:
            core.transport.reply(b"ERROR:No _mpy support")
        else:
            core.transport.reply(f"MPY_OK:{value}:{bits}".encode())
    elif cmd == "RTC":
        core.transport.reply(
            b"RTC_OK:" + repr(machine.RTC().datetime()).encode()
        )
    elif cmd == "RTC_STAGE":
        _stage_rtc_update(core, parts)
    elif cmd == "RB":
        core.transport.reply(b"RB_OK")
        core.logger.info("Reboot commanded (RB)")
        _do_callback(core, callback)
        _persist_replay_floor(core)
        machine.reset()
    elif cmd == "SR":
        core.transport.reply(b"SR_OK")
        core.logger.info("Soft-reset commanded (SR)")
        _persist_replay_floor(core)
        machine.soft_reset()
    elif cmd == "UPDATE_REQUEST":
        core.logger.debug("UPDATE REQUESTED")
        _do_callback(core, callback)
        flag = _get_config(core.config, "UPDATE_REQUEST_FLAG_FILE")
        if flag:
            try:
                with open(flag, "w") as f:
                    f.write("1")
            except OSError as e:
                core.logger.error(f"Failed to write flag-file: {e}")
        core.transport.reply(b"REBOOTING")
        core.logger.info("Shutdown started: OTA update requested")
        _persist_replay_floor(core)
        machine.reset()
    elif cmd == "LS":
        path = parts[1] if len(parts) > 1 and parts[1] else "."
        try:
            try:
                stat = _os.stat(path)
                is_dir = stat[0] & 0x4000
            except OSError:
                is_dir = True

            if not is_dir:
                name = path.split("/")[-1]
                core.transport.reply(f"LS_OK:{name}".encode())
            else:
                total_size = _directory_size(path)
                _send_response(
                    core.transport,
                    total_size,
                    _directory_parts(path),
                    heartbeat=heartbeat,
                )
        except OSError as e:
            core.transport.reply(f"ERROR:{e}".encode())
    elif cmd == "CAT":
        if len(parts) < 2 or not parts[1]:
            core.transport.reply(b"ERROR:Missing filename")
            return
        filename = parts[1]
        try:
            try:
                stat = _os.stat(filename)
                is_dir = stat[0] & 0x4000
            except OSError:
                is_dir = False

            if is_dir:
                core.transport.reply(b"ERROR:EISDIR")
            else:
                size = _os.stat(filename)[6]
                with open(filename, "rb") as source:
                    _send_response(
                        core.transport,
                        len(b"CAT_OK:") + size,
                        _file_parts(source, size),
                        heartbeat=heartbeat,
                    )
        except OSError as e:
            core.transport.reply(f"ERROR:{e}".encode())
    elif cmd == "RM":
        if len(parts) < 2 or not parts[1]:
            core.transport.reply(b"ERROR:Missing filename")
            return
        filename = parts[1]
        try:
            _os.remove(filename)
            core.transport.reply(b"RM_OK")
        except OSError as remove_error:
            try:
                is_dir = _os.stat(filename)[0] & 0x4000
                if not is_dir:
                    raise remove_error
                _os.rmdir(filename)
                core.transport.reply(b"RM_OK")
            except OSError as e:
                core.transport.reply(f"ERROR:{e}".encode())
    elif cmd.startswith("CP_"):
        from .filecopy import handle

        handle(core, cmd_str)
    elif cmd == "MEM":
        try:
            import gc

            gc.collect()
            ram_free = gc.mem_free()
            ram_alloc = gc.mem_alloc()
        except (ImportError, AttributeError):
            ram_free = 0
            ram_alloc = 0

        try:
            stat = _os.statvfs("/")
            flash_free = stat[4] * stat[0]
            flash_total = stat[2] * stat[0]
        except (AttributeError, OSError):
            flash_free = 0
            flash_total = 0

        core.transport.reply(
            f"MEM_OK:{ram_free},{ram_alloc},{flash_free},{flash_total}".encode()
        )
    else:
        core.logger.warning(f"Unknown command received: {cmd}")
