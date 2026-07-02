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
    import gc
    import hashlib

    import machine

    # Caching Attributes for speed
    send = core.transport.send
    read = core.transport.read
    collect = gc.collect

    # Flat target/staging pairs avoid a tuple allocation for every manifest
    # entry while preserving the complete transaction for atomic commit.
    files = []
    current_file = None
    current_hash = None
    hasher = None

    while True:
        packet = read()
        if not packet:
            _sleep_ms(10)
            continue

        if not isinstance(packet, bytes):
            packet = str(packet).strip().encode()
        else:
            packet = packet.strip()

        if not packet:
            continue

        # ASCII protocol packets stay as bytes. Validate UTF-8 only when a
        # high-bit byte makes the old decode error behaviour relevant.
        for value in packet:
            if value & 0x80:
                try:
                    packet.decode("utf-8")
                except UnicodeError:
                    send(b"ERROR:Invalid UTF-8")
                    packet = None
                    collect()
                    break
                break
        if packet is None:
            continue

        separator = packet.find(b":")
        cmd = packet if separator < 0 else packet[:separator]

        if cmd == b"UPDATE_START":
            parts = packet.split(b":", 2)
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
            response = (
                b"SPACE_ERR"
                if free_bytes * 2 < total_bytes * 3
                else b"SPACE_OK"
            )
            packet = None
            parts = None
            collect()
            send(response)

        elif cmd == b"FILE_START":
            parts = packet.split(b":", 3)
            if len(parts) < 4:
                send(b"ERROR:Invalid file start")
                continue
            try:
                path = parts[1].decode("utf-8")
                int(parts[2])
            except (UnicodeError, ValueError):
                send(b"ERROR:Invalid file size")
                continue
            sha256 = parts[3]

            target_path = _resolve_path(path)
            staging_path = target_path + ".ota"
            try:
                _make_dirs(staging_path)
                """ SIM115:
                We explicitly _cannot_ use a context manager here because the
                  file is opened during a FILE_START packet and must remain
                  open across multiple subsequent CHUNK packet processing
                  iterations until closed by a FILE_END packet.
                """
                f = open(staging_path, "wb")  # noqa: SIM115
                current_file = f
                current_hash = sha256
                hasher = hashlib.sha256()
                files.append(target_path)
                files.append(staging_path)
                packet = None
                parts = None
                path = None
                sha256 = None
                target_path = None
                staging_path = None
                collect()
                send(b"FILE_OK")
            except OSError as e:
                send(f"FILE_ERR:{e}".encode())

        elif cmd == b"CHUNK":
            parts = packet.split(b":", 2)
            if len(parts) < 3:
                send(b"ERROR:Invalid chunk packet")
                continue
            seq = parts[1]
            b64_data = parts[2]

            if current_file is None:
                send(b"ERROR:No active file session")
                continue

            decoded = None
            try:
                decoded = binascii.a2b_base64(b64_data)
                current_file.write(decoded)
                hasher.update(decoded)  # type: ignore
                response = b"CHUNK_ACK:" + seq
                packet = None
                parts = None
                seq = None
                b64_data = None
                decoded = None
                collect()
                send(response)
            except Exception as e:
                send(f"CHUNK_ERR:{e}".encode())

        elif cmd == b"FILE_END":
            if current_file is None:
                send(b"ERROR:No active file session")
                continue

            current_file.close()
            current_file = None

            digest = hasher.digest()  # type: ignore
            hex_hash = binascii.hexlify(digest)

            if hex_hash == current_hash:
                response = b"FILE_OK"
            else:
                staging_path = files[-1]
                try:
                    _os.remove(staging_path)
                except OSError:
                    pass
                files.pop()
                files.pop()
                response = b"FILE_ERR:Checksum mismatch"
            packet = None
            current_hash = None
            hasher = None
            digest = None
            hex_hash = None
            collect()
            send(response)

        elif cmd == b"UPDATE_COMMIT":
            success = True
            for index in range(0, len(files), 2):
                target = files[index]
                staging = files[index + 1]
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
        core.logger.debug(f"No update request flag found: {flag}")
        _cleanup_orphaned_ota(core)
