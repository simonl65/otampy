import machine

try:
    import uos as _os
except ImportError:
    import os as _os


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
    elif cmd == "BL":
        core.transport.send(b"BL_OK")
        machine.bootloader()
    elif cmd == "RB":
        core.transport.send(b"RB_OK")
        machine.reset()
    elif cmd == "SR":
        core.transport.send(b"SR_OK")
        machine.soft_reset()
    elif cmd == "UPDATE_REQUEST":
        if callback is not None:
            callback()
        flag = core.config.get("UPDATE_REQUEST_FLAG_FILE")
        if flag:
            try:
                with open(flag, "w") as f:
                    f.write("1")
            except OSError as e:
                core.logger.error(f"Failed to write flag file: {e}")
        core.transport.send(b"REBOOTING")
        machine.reset()
    elif cmd == "LS":
        path = parts[1] if len(parts) > 1 and parts[1] else "."
        try:
            items = []
            for item in _os.listdir(path):
                full_path = path.rstrip("/") + "/" + item
                try:
                    stat = _os.stat(full_path)
                    is_dir = stat[0] & 0x4000
                    if is_dir:
                        items.append(item + "/")
                    else:
                        items.append(item)
                except OSError:
                    items.append(item)
            items_str = ",".join(items)
            core.transport.send(f"LS_OK:{items_str}".encode())
        except OSError as e:
            core.transport.send(f"ERROR:{e}".encode())
    elif cmd == "CAT":
        if len(parts) < 2 or not parts[1]:
            core.transport.send(b"ERROR:Missing filename")
            return
        filename = parts[1]
        try:
            with open(filename) as f:
                content = f.read()
            core.transport.send(f"CAT_OK:{content}".encode())
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
        except OSError as e:
            core.transport.send(f"ERROR:{e}".encode())
    else:
        core.logger.warning(f"Unknown command received: {cmd}")
