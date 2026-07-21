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


def _do_callback(core, callback=None):
    if callback is not None:
        try:
            core.logger.debug("Calling application callback")
            callback()
        except Exception as e:
            core.logger.error(f"Error in application callback: {e}")


def _stage_rtc_update(core, parts):
    if len(parts) != 9:
        core.transport.send(b"RTC_STAGE_ERR")
        return
    try:
        time_tuple = tuple(int(value) for value in parts[1:])
    except ValueError:
        core.transport.send(b"RTC_STAGE_ERR")
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
        core.transport.send(b"RTC_STAGE_ERR")
        return
    core.transport.send(b"RTC_STAGE_OK")


def _send_response(transport, total_size, parts):
    if total_size > _MAX_RESPONSE_SIZE:
        transport.send(b"ERROR:Response too large")
        return

    protocol = getattr(transport, "protocol", None)
    if total_size <= _MAX_FRAGMENT_DATA or protocol is None or not hasattr(transport, "_msg_id"):
        response = bytearray()
        for part in parts:
            response.extend(part)
        transport.send(bytes(response))
        return

    total_fragments = (total_size + _MAX_FRAGMENT_DATA - 1) // _MAX_FRAGMENT_DATA
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
                ):
                    return
                fragment_number += 1
                fragment = bytearray()
                collect()
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
        protocol.send_reliable(
            _urst_constants.FRAME_FRAG,
            header + bytes(fragment),
        )
        fragment = None
        collect()


def _file_parts(source):
    yield b"CAT_OK:"
    while True:
        chunk = source.read(_MAX_FRAGMENT_DATA)
        if not chunk:
            return
        yield chunk


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


def poll(core, callback=None):
    """
    Check the transport (UART) for any pending commands and dispatch them.
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

    # Parse command and optional arguments
    parts = cmd_str.split(":")
    cmd = parts[0]

    if cmd == "PING":
        core.transport.send(b"PONG")
    elif cmd == "RTC":
        core.transport.send(b"RTC_OK:" + repr(machine.RTC().datetime()).encode())
    elif cmd == "RTC_STAGE":
        _stage_rtc_update(core, parts)
    elif cmd == "RB":
        core.transport.send(b"RB_OK")
        core.logger.info("Reboot commanded (RB)")
        _do_callback(core, callback)
        machine.reset()
    elif cmd == "SR":
        core.transport.send(b"SR_OK")
        core.logger.info("Soft-reset commanded (SR)")
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
                core.logger.error(f"Failed to write flag file: {e}")
        core.transport.send(b"REBOOTING")
        core.logger.info("Shutdown started: OTA update requested (rebooting into boot.py)")
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
                core.transport.send(f"LS_OK:{name}".encode())
            else:
                total_size = _directory_size(path)
                _send_response(
                    core.transport,
                    total_size,
                    _directory_parts(path),
                )
        except OSError as e:
            core.transport.send(f"ERROR:{e}".encode())
    elif cmd == "CAT":
        if len(parts) < 2 or not parts[1]:
            core.transport.send(b"ERROR:Missing filename")
            return
        filename = parts[1]
        try:
            try:
                stat = _os.stat(filename)
                is_dir = stat[0] & 0x4000
            except OSError:
                is_dir = False

            if is_dir:
                core.transport.send(b"ERROR:EISDIR")
            else:
                size = _os.stat(filename)[6]
                with open(filename, "rb") as source:
                    _send_response(
                        core.transport,
                        len(b"CAT_OK:") + size,
                        _file_parts(source),
                    )
        except OSError as e:
            core.transport.send(f"ERROR:{e}".encode())
    elif cmd == "RM":
        if len(parts) < 2 or not parts[1]:
            core.transport.send(b"ERROR:Missing filename")
            return
        filename = parts[1]
        try:
            _os.remove(filename)
            core.transport.send(b"RM_OK")
        except OSError as remove_error:
            try:
                is_dir = _os.stat(filename)[0] & 0x4000
                if not is_dir:
                    raise remove_error
                _os.rmdir(filename)
                core.transport.send(b"RM_OK")
            except OSError as e:
                core.transport.send(f"ERROR:{e}".encode())
    elif cmd.startswith("CP_"):
        from .filecopy import handle

        handle(core, cmd_str)
    elif cmd == "MEM":
        try:
            import gc

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

        core.transport.send(f"MEM_OK:{ram_free},{ram_alloc},{flash_free},{flash_total}".encode())
    else:
        core.logger.warning(f"Unknown command received: {cmd}")
