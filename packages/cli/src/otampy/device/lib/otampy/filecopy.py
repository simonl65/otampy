try:
    import uos as _os
except ImportError:
    import os as _os


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


def _clear_state(core, remove_staging=True):
    state = getattr(core, "_copy_state", None)
    if state is None:
        return
    output = state[0]
    if output is not None:
        try:
            output.close()
        except OSError:
            pass
    if remove_staging:
        try:
            _os.remove(state[2])
        except OSError:
            pass
    del core._copy_state


def _commit(target, staging):
    replace = getattr(_os, "replace", None)
    if replace is not None:
        replace(staging, target)
        return

    backup = target + ".bak"
    try:
        _os.remove(backup)
    except OSError:
        pass

    had_target = True
    try:
        _os.rename(target, backup)
    except OSError:
        had_target = False

    try:
        _os.rename(staging, target)
    except OSError:
        if had_target:
            try:
                _os.rename(backup, target)
            except OSError:
                pass
        raise

    if had_target:
        try:
            _os.remove(backup)
        except OSError:
            pass


def _start(core, command):
    _clear_state(core)
    fields = command.split(":", 3)
    if len(fields) < 4 or not fields[1]:
        core.transport.send(b"ERROR:Invalid copy start")
        return
    try:
        size = int(fields[2])
        if size < 0 or len(fields[3]) != 64:
            raise ValueError
    except ValueError:
        core.transport.send(b"ERROR:Invalid copy metadata")
        return

    target = fields[1]
    staging = target + ".cp"
    try:
        try:
            stat = _os.statvfs("/")
            if stat[4] * stat[0] < size:
                core.transport.send(b"ERROR:Insufficient storage")
                return
        except (AttributeError, OSError):
            pass
        _make_dirs(staging)
        try:
            _os.remove(staging)
        except OSError:
            pass
        import hashlib

        output = open(staging, "wb")  # noqa: SIM115
        # Flat, temporary state avoids permanent per-instance RAM and a
        # dictionary allocation while a streamed copy is in progress.
        core._copy_state = [
            output,
            target,
            staging,
            fields[3],
            hashlib.sha256(),
            size,
            0,
            0,
        ]
        core.transport.send(b"CP_READY")
    except OSError as e:
        _clear_state(core)
        core.transport.send(f"ERROR:{e}".encode())


def _chunk(core, command):
    state = getattr(core, "_copy_state", None)
    fields = command.split(":", 2)
    if state is None:
        core.transport.send(b"ERROR:No active copy")
        return
    if len(fields) < 3:
        _clear_state(core)
        core.transport.send(b"ERROR:Invalid copy chunk")
        return
    try:
        sequence = int(fields[1])
        if sequence != state[7]:
            raise ValueError("Unexpected chunk sequence")
        import binascii

        data = binascii.a2b_base64(fields[2].encode())
        if state[6] + len(data) > state[5]:
            raise ValueError("Copy exceeds declared size")
        state[0].write(data)
        state[4].update(data)
        state[6] += len(data)
        state[7] += 1
        core.transport.send(f"CP_ACK:{sequence}".encode())
    except (OSError, ValueError) as e:
        _clear_state(core)
        core.transport.send(f"ERROR:{e}".encode())


def _end(core):
    state = getattr(core, "_copy_state", None)
    if state is None:
        core.transport.send(b"ERROR:No active copy")
        return
    try:
        state[0].close()
        state[0] = None
        import binascii

        digest = binascii.hexlify(state[4].digest()).decode()
        if state[6] != state[5]:
            raise ValueError("Copy size mismatch")
        if digest != state[3]:
            raise ValueError("Copy checksum mismatch")
        _commit(state[1], state[2])
        _clear_state(core, remove_staging=False)
        core.transport.send(b"CP_OK")
    except (OSError, ValueError) as e:
        _clear_state(core)
        core.transport.send(f"ERROR:{e}".encode())


def handle(core, command):
    cmd = command.split(":", 1)[0]
    if cmd == "CP_START":
        _start(core, command)
    elif cmd == "CP_CHUNK":
        _chunk(core, command)
    elif cmd == "CP_END":
        _end(core)
    elif cmd == "CP_ABORT":
        _clear_state(core)
        core.transport.send(b"CP_ABORTED")
    else:
        core.transport.send(b"ERROR:Unknown copy command")
