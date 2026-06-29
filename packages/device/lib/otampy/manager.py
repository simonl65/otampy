import machine


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
    else:
        core.logger.warning(f"Unknown command received: {cmd}")
