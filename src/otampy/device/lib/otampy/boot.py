try:
    import uos as _os
except ImportError:
    import os as _os

from .core import _get_config, _resolve_path

# The host stages this one-shot RTC helper in every ``otampy upd`` manifest
# (unless ``--no-rtc``). It self-deletes on the next boot, so it must be placed
# but never retained as ``.bck`` or journalled -- otherwise ``restore.repair()``
# resurrects it from the backup the boot after (F-05).
_RTC_HELPER_FILE = "_otampy_set_rtc.py"

# Boot-time recovery window. Opened on every boot with no update pending, so
# a device whose main.py never reaches ota.poll() -- it raises on import,
# hangs, or was replaced by a fatal candidate that got confirmed -- is still
# reachable over the radio with no USB.
#
# The window is silent: no beacon. An unacknowledged Urst.send() is
# stop-and-wait reliable (connect + send_reliable, 4 attempts each at
# ACK_TIMEOUT_MS), so announcing the window would cost up to ~8s on every
# boot with no host listening. The host blind-retries instead.
_DEFAULT_BOOT_LISTEN_MS = 1000
_BOOT_LISTEN_POLL_MS = 10
_RECOVERY_REFUSED = b"ERROR:Recovery window"


def _apply_staged_rtc_update():
    """Run the one-shot RTC helper staged during host operations (unless --no-rtc is specified)."""
    try:
        __import__(_RTC_HELPER_FILE[:-3])
    except ImportError:
        pass


def _sleep_ms(ms):
    try:
        import utime

        utime.sleep_ms(ms)
    except ImportError:
        import time

        time.sleep(ms / 1000.0)


def _ticks_ms():
    try:
        import utime

        return utime.ticks_ms()
    except ImportError:
        import time

        return int(time.monotonic() * 1000)  # type: ignore


def _ticks_diff(new, old):
    try:
        import utime

        return utime.ticks_diff(new, old)
    except ImportError:
        return new - old


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
    core.logger.debug("Running OTA update loop")
    import binascii
    import gc
    import hashlib

    import machine

    from .restore import clear_journal, commit

    # Caching Attributes for speed. `reply`, not `send`: every call in this
    # loop answers the packet most recently read (§5.8.3) -- `READY` above,
    # sent unprompted to kick off the session, is the one exception and
    # correctly stays on `core.transport.send()` directly.
    send = core.transport.reply
    read = core.transport.read
    collect = gc.collect

    # Flat target/staging pairs avoid a tuple allocation for every manifest
    # entry while preserving the complete transaction for atomic commit.
    files = []
    delete_paths = []
    current_file = None
    current_hash = None
    hasher = None
    timeout_ms = _get_config(core.config, "OTA_TIMEOUT_MS", 5000)
    try:
        timeout_ms = int(timeout_ms)  # type: ignore
    except (TypeError, ValueError):
        timeout_ms = 5000
    if timeout_ms < 1:
        timeout_ms = 5000
    last_activity = _ticks_ms()

    while True:
        packet = read()
        if not packet:
            if _ticks_diff(_ticks_ms(), last_activity) >= timeout_ms:
                core.logger.warning("OTA update timed out; aborting session")
                if current_file is not None:
                    try:
                        current_file.close()
                    except OSError:
                        pass
                    current_file = None
                for index in range(1, len(files), 2):
                    try:
                        _os.remove(files[index])
                    except OSError:
                        pass
                # A power loss restarts this loader with an empty ``files``
                # list, even though the interrupted session's .ota files
                # still exist on disk. Clean those up too.
                _cleanup_orphaned_ota(core)
                send(b"UPDATE_ABORTED")
                break
            _sleep_ms(10)
            continue

        last_activity = _ticks_ms()

        packet = (
            str(packet).strip().encode()
            if not isinstance(packet, bytes)
            else packet.strip()
        )

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
            core.logger.debug("UPDATE START")
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

            # Discard the previous generation's journal + .bck set now: the
            # code currently running becomes this update's retained backup,
            # and the space check should not count the older generation.
            clear_journal(core)

            free_bytes = _get_free_space()
            delete_paths = []
            response = (
                b"SPACE_ERR"
                if free_bytes * 2 < total_bytes * 3
                else b"SPACE_OK"
            )
            packet = None
            parts = None
            collect()
            core.logger.debug(response.decode())
            send(response)

        elif cmd == b"DELETE":
            parts = packet.split(b":", 1)
            if len(parts) != 2:
                send(b"ERROR:Invalid delete")
                continue
            try:
                delete_paths.append(_resolve_path(parts[1].decode("utf-8")))
            except UnicodeError:
                send(b"ERROR:Invalid delete")
                continue
            packet = None
            parts = None
            collect()
            send(b"DELETE_OK")

        elif cmd == b"FILE_START":
            core.logger.debug("FILE START")
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
            core.logger.debug(staging_path)
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
            core.logger.debug("FILE END")
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

        elif cmd == b"UPDATE_ABORT":
            core.logger.debug("UPDATE ABORT")
            if current_file is not None:
                try:
                    current_file.close()
                except OSError:
                    pass
                current_file = None
            _cleanup_orphaned_ota(core)
            send(b"UPDATE_ABORTED")
            break

        elif cmd == b"UPDATE_COMMIT":
            core.logger.debug("UPDATE COMMIT")
            # Split the one-shot RTC helper out of the retained set: place it
            # with a plain rename so it runs once, but never back it up or
            # journal it (F-05).
            retained = []
            for index in range(0, len(files), 2):
                target = files[index]
                if target.rsplit("/", 1)[-1] == _RTC_HELPER_FILE:
                    try:
                        _os.remove(target)
                    except OSError:
                        pass
                    try:
                        _os.rename(files[index + 1], target)
                    except OSError:
                        pass
                else:
                    retained.append(target)
                    retained.append(files[index + 1])

            # All-or-nothing: renames each target to <target>.bck, stages the
            # new file in, and rolls the whole set back from .bck on any
            # failure. The retained .bck set plus the journal let boot.run()'s
            # repair() reverse an interrupted commit on the next boot.
            if commit(core, retained, delete_paths):
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


def _persist_replay_floor(core):
    """Record the replay counter before a window-commanded reset.

    The `_replay_guard` check sits here, not inside `authgate`, so a device
    with auth off never imports that module. `manager` keeps its own copy of
    this four-line guard deliberately: importing `manager` from the boot
    phase to share it would pull the entire runtime command surface in.
    """
    if getattr(core, "_replay_guard", None) is None:
        return
    from .authgate import persist_replay_floor

    persist_replay_floor(core)


def _run_boot_listen(core):
    """The boot-time recovery window. Never raises.

    Listens silently for ``OTA_BOOT_LISTEN_MS`` and serves exactly two
    commands, ``UPDATE_REQUEST`` and ``ROLLBACK``. Returns ``True`` when it
    handled a command that reset the board (so the caller returns -- a mocked
    ``machine.reset`` in tests does not actually reset), ``False`` when the
    window simply expired.

    A refusal does not consume the window: the deadline is **absolute** and
    is never extended by activity, unlike ``_run_default_update_loop``'s
    inactivity timeout, so a chatty peer cannot pin a device in here.

    Deliberately does not answer ``PING``. A device in the window is not
    running its application, and a ``PONG`` would report it healthy -- the
    absence of one is the signal that recovery is needed.
    """
    window_ms = _get_config(
        core.config, "OTA_BOOT_LISTEN_MS", _DEFAULT_BOOT_LISTEN_MS
    )
    try:
        window_ms = int(window_ms)  # type: ignore
    except (TypeError, ValueError):
        window_ms = _DEFAULT_BOOT_LISTEN_MS
    if window_ms <= 0:
        return False

    read = core.transport.read
    reply = core.transport.reply
    require_auth = _get_config(core.config, "OTA_REQUIRE_AUTH", False)
    started = _ticks_ms()

    while _ticks_diff(_ticks_ms(), started) < window_ms:
        packet = read()
        if not packet:
            _sleep_ms(_BOOT_LISTEN_POLL_MS)
            continue

        packet = (
            str(packet).strip().encode()
            if not isinstance(packet, bytes)
            else packet.strip()
        )
        if not packet:
            continue

        # ASCII protocol packets stay as bytes. Validate UTF-8 only when a
        # high-bit byte makes it relevant; a non-UTF-8 packet is dropped in
        # silence, as manager.poll drops one.
        decodable = True
        for value in packet:
            if value & 0x80:
                try:
                    packet.decode("utf-8")
                except UnicodeError:
                    decodable = False
                break
        if not decodable:
            core.logger.warning("Recovery window: ignoring non-UTF-8 packet")
            continue

        # The window enforces the same auth envelope the runtime command
        # surface does, so it is not a bypass. Imported lazily and only when
        # auth is configured, keeping the no-auth boot path unchanged.
        if require_auth:
            from .authgate import authenticate

            inner = authenticate(core, packet.decode("utf-8"))
            if inner is None:
                continue
            packet = inner.encode()

        if packet == b"UPDATE_REQUEST":
            flag = _get_config(core.config, "UPDATE_REQUEST_FLAG_FILE")
            if flag:
                try:
                    with open(flag, "w") as handle:
                        handle.write("1")
                except OSError as err:
                    core.logger.error(f"Failed to write flag-file: {err}")
            reply(b"REBOOTING")
            core.logger.info("Recovery window: update requested; resetting")
            _persist_replay_floor(core)
            import machine

            machine.reset()
            return True

        elif packet == b"ROLLBACK":
            from .restore import rollback_result

            response, restored = rollback_result(core)
            reply(response)
            if restored:
                core.logger.info(
                    f"Recovery window: rollback restored {restored} "
                    "file(s); resetting"
                )
                _persist_replay_floor(core)
                import machine

                machine.reset()
                return True

        else:
            reply(_RECOVERY_REFUSED)

    return False


def _canonical(path):
    # Collapse the "./" / "/./" traversal artefacts so a swept item's path
    # compares equal to the "/dir/file" form read_journal() stores. Without
    # this, "./main.py.bck" (host) / "/./main.py.bck" (MicroPython) never
    # matched the journal's "/main.py.bck" and retained backups were deleted
    # on the first boot after a commit (F-04).
    path = path.replace("/./", "/")
    if path.startswith("./"):
        path = path[1:]
    if not path.startswith("/"):
        path = "/" + path
    return path


def _cleanup_orphaned_ota(core, path=".", kept_backups=None):
    if kept_backups is None:
        # Backups still referenced by the retain-previous journal must be
        # kept; every other <x>.bck is an orphan from a crashed commit whose
        # journal never landed.
        from .restore import _BACKUP_SUFFIX, read_journal

        kept_backups = {
            _canonical(p + _BACKUP_SUFFIX) for p in read_journal(core)[2]
        }
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
                    _cleanup_orphaned_ota(core, item_path, kept_backups)
                elif item.endswith(".ota") or (
                    item.endswith(".bck")
                    and _canonical(resolved_item) not in kept_backups
                ):
                    if log_level_debug:
                        logger_debug(f"Removing orphaned file: {resolved_item}")
                    remove_func(resolved_item)
            except OSError:
                pass
    except OSError:
        pass


def run(core, callback=None):
    """
    Check if the update request flag-file exists, execute the callback to
    perform the update, and remove the flag-file.
    """
    _apply_staged_rtc_update()

    # Finish or reverse an interrupted retain-previous commit before anything
    # else touches the filesystem -- runs on every boot, flagged or not.
    # Local import so it stays GC-eligible alongside `boot` itself.
    from .restore import _ROLLED_BACK, repair, trial

    repair(core)

    # Count this boot into any unconfirmed candidate. Past OTA_TRIAL_BOOTS
    # reboots trial() has already restored the previous generation, so all
    # that is left is to reset onto it. `return` because a mocked
    # `machine.reset` in tests does not actually reset.
    if trial(core) == _ROLLED_BACK:
        core.logger.warning(
            "Trial-boot limit exceeded; previous generation restored, resetting"
        )
        import machine

        machine.reset()
        return

    core.logger.debug("Checking for update flag-file...")
    flag = _get_config(core.config, "UPDATE_REQUEST_FLAG_FILE")

    if not flag:
        core.logger.error("Missing filename for update request flag-file")
        return

    # Check if the flag-file exists
    has_flag = False
    try:
        _os.stat(flag)
        has_flag = True
    except OSError:
        pass

    if has_flag:
        core.logger.debug("FOUND update flag-file")
        core.transport.send(b"READY")

        if callback is not None:
            # Handle variable argument callback cleanly
            try:
                core.logger.debug(f"Executing callback: {callback.__name__}")
                callback(flag)
            except TypeError:
                core.logger.debug(
                    f"Executing callback with flag argument: {callback.__name__}"
                )
                callback()
        else:
            _run_default_update_loop(core)

        # Remove the flag-file
        try:
            core.logger.debug(f"Removing update request flag-file: {flag}")
            _os.remove(flag)
        except OSError:
            try:
                getattr(_os, "unlink", lambda _p: None)(flag)
            except Exception:
                core.logger.debug(f"Could not remove update flag-file: {flag}")
    else:
        core.logger.debug(f"{flag} not found")
        core.logger.debug("Cleanup started...")
        _cleanup_orphaned_ota(core)
        core.logger.debug("Cleanup complete")
