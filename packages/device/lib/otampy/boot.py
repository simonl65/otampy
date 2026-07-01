try:
    import uos as _os
except ImportError:
    import os as _os

from .core import _get_config


def _sleep_ms(ms):
    try:
        import utime

        utime.sleep_ms(ms)
    except ImportError:
        import time

        time.sleep(ms / 1000.0)


def _resolve_path(path):
    if path.startswith("/"):
        return path
    import sys

    if sys.implementation.name != "micropython":
        return path
    return "/" + path


def _get_free_space():
    try:
        stat = _os.statvfs("/")
        return stat[0] * stat[3]
    except (OSError, AttributeError):
        return 1024 * 1024 * 1024  # 1 GB fallback


def _make_dirs(path):
    parts = path.split("/")
    current = ""
    for part in parts[:-1]:
        if not part:
            current += "/"
            continue
        current = current.rstrip("/") + "/" + part
        try:
            _os.mkdir(current)
        except OSError:
            pass


def _run_default_update_loop(core):
    import binascii
    import hashlib

    import machine

    # Caching Attributes for speed
    send = core.transport.send
    read = core.transport.read

    session = {
        "files": [],  # list of (target_path, staging_path)
        "current_file": None,
        "current_hash": None,
        "current_size": 0,
        "written_bytes": 0,
        "hasher": None,
    }

    while True:
        packet = read()
        if not packet:
            _sleep_ms(10)
            continue

        if isinstance(packet, bytes):
            try:
                cmd_str = packet.decode("utf-8").strip()
            except UnicodeError:
                send(b"ERROR:Invalid UTF-8")
                continue
        else:
            cmd_str = str(packet).strip()

        if not cmd_str:
            continue

        parts = cmd_str.split(":")
        cmd = parts[0]

        if cmd == "UPDATE_START":
            if len(parts) < 3:
                send(b"ERROR:Invalid manifest")
                continue
            try:
                _file_count = int(parts[1])
                total_bytes = int(parts[2])
            except ValueError:
                send(b"ERROR:Invalid numbers")
                continue

            free_bytes = _get_free_space()
            if free_bytes < total_bytes * 1.5:
                send(b"SPACE_ERR")
            else:
                send(b"SPACE_OK")

        elif cmd == "FILE_START":
            if len(parts) < 4:
                send(b"ERROR:Invalid file start")
                continue
            path = parts[1]
            try:
                size = int(parts[2])
            except ValueError:
                send(b"ERROR:Invalid file size")
                continue
            sha256 = parts[3]

            staging_path = _resolve_path(path) + ".ota"
            try:
                _make_dirs(staging_path)
                """ SIM115:
                We explicitly _cannot_ use a context manager here because the
                  file is opened during a FILE_START packet and must remain
                  open across multiple subsequent CHUNK packet processing
                  iterations until closed by a FILE_END packet.
                """
                f = open(staging_path, "wb")  # noqa: SIM115
                session["current_file"] = f
                session["current_hash"] = sha256
                session["current_size"] = size
                session["written_bytes"] = 0
                session["hasher"] = hashlib.sha256()
                session["files"].append((_resolve_path(path), staging_path))
                send(b"FILE_OK")
            except OSError as e:
                send(f"FILE_ERR:{e}".encode())

        elif cmd == "CHUNK":
            if len(parts) < 3:
                send(b"ERROR:Invalid chunk packet")
                continue
            seq = parts[1]
            b64_data = parts[2]

            if not session["current_file"]:
                send(b"ERROR:No active file session")
                continue

            try:
                decoded = binascii.a2b_base64(b64_data)
                session["current_file"].write(decoded)
                session["hasher"].update(decoded)
                session["written_bytes"] += len(decoded)
                send(f"CHUNK_ACK:{seq}".encode())
            except Exception as e:
                send(f"CHUNK_ERR:{e}".encode())

        elif cmd == "FILE_END":
            if not session["current_file"]:
                send(b"ERROR:No active file session")
                continue

            session["current_file"].close()
            session["current_file"] = None

            digest = session["hasher"].digest()
            hex_hash = binascii.hexlify(digest).decode("utf-8")

            if hex_hash == session["current_hash"]:
                send(b"FILE_OK")
            else:
                try:
                    _os.remove(session["files"][-1][1])
                except OSError:
                    pass
                session["files"].pop()
                send(b"FILE_ERR:Checksum mismatch")

        elif cmd == "UPDATE_COMMIT":
            success = True
            for target, staging in session["files"]:
                try:
                    try:
                        _os.remove(target)
                    except OSError:
                        pass
                    _os.rename(staging, target)
                except OSError as e:
                    core.logger.error(f"Commit failed for {target}: {e}")
                    success = False
                    break

            if success:
                send(b"COMMIT_OK")
            else:
                send(b"COMMIT_ERR")

            flag_file = _get_config(
                core.config,
                "UPDATE_REQUEST_FLAG_FILE",
            )
            if flag_file:
                try:
                    _os.remove(flag_file)
                except OSError:
                    pass
            try:
                machine.reset()
            except Exception:
                pass
            break


def _cleanup_orphaned_ota(core, path="."):
    resolved_path = _resolve_path(path)
    try:
        # Cache standard methods & check logger levels
        listdir = _os.listdir
        stat_func = _os.stat
        remove_func = _os.remove
        logger_debug = core.logger.debug
        log_level_debug = getattr(core.logger, "min_level", 0) <= 0

        for item in listdir(resolved_path):
            item_path = path.rstrip("/") + "/" + item
            resolved_item = _resolve_path(item_path)
            try:
                stat = stat_func(resolved_item)
                is_dir = stat[0] & 0x4000
                if is_dir:
                    _cleanup_orphaned_ota(core, item_path)
                elif item.endswith(".ota"):
                    if log_level_debug:
                        logger_debug(
                            f"Removing orphaned staging file: {resolved_item}"
                        )
                    remove_func(resolved_item)
            except OSError:
                pass
    except OSError:
        pass


def run(core, callback=None):
    """
    Check if the update request flag file exists, execute the callback to
    perform the update, and remove the flag file.
    """
    core.logger.debug("Checking for update request flag file...")
    flag = _get_config(core.config, "UPDATE_REQUEST_FLAG_FILE")

    if not flag:
        core.logger.error("Missing filename for update request flag file")
        return

    # Check if the flag file exists
    has_flag = False
    try:
        _os.stat(flag)
        has_flag = True
    except OSError:
        pass

    if has_flag:
        core.logger.debug(f"Update request flag found: {flag}")
        core.transport.send(b"READY")

        if callback is not None:
            # Handle variable argument callback cleanly
            try:
                callback(flag)
            except TypeError:
                callback()
        else:
            _run_default_update_loop(core)

        # Remove the flag file
        try:
            _os.remove(flag)
        except OSError:
            try:
                getattr(_os, "unlink", lambda _p: None)(flag)
            except Exception:
                core.logger.debug(f"Could not remove update flag: {flag}")
    else:
        _cleanup_orphaned_ota(core)
