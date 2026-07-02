from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.console import Console

import otampy.deploy as deploy

if TYPE_CHECKING:
    from urst import Urst

logger = logging.getLogger(__name__)


class DeviceError(Exception):
    """Exception raised for device errors."""

    def __init__(self, error_msg: str, command: bytes = b""):
        self.error_msg = error_msg
        self.command = command
        super().__init__(error_msg)


def _console() -> Console:
    return Console(highlight=False)


# from .shared.protocol import OTA_COMMANDS
# # Sanity-check the protocol at import time so maintainers see mismatches
# try:
#     logger.debug("Loaded OTA_COMMANDS: %s", OTA_COMMANDS)
# except Exception:
#     pass


class AliasedGroup(click.Group):
    """A Click Group that supports convenient aliases for its subcommands."""

    def get_command(
        self, ctx: click.Context, cmd_name: str
    ) -> click.Command | None:
        normalized_name = cmd_name.lower()
        # First try to get the command exactly, case-insensitive
        rv = click.Group.get_command(self, ctx, normalized_name)
        if rv is not None:
            return rv
        # Map aliases to the target subcommand names
        aliases = {
            "reboot": "rb",
            "reset": "sr",
            "softreset": "sr",
            "remove": "rm",
            "update": "upd",
            "memory": "mem",
        }
        if normalized_name in aliases:
            return click.Group.get_command(self, ctx, aliases[normalized_name])
        return None

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted(click.Group.list_commands(self, ctx))


def get_default_port() -> str | None:
    import os

    if "OTAMPY_PORT" in os.environ:  # type: ignore
        return os.environ["OTAMPY_PORT"]  # type: ignore
    # Check session config (by parent shell PID)
    import tempfile

    session_file = (
        Path(tempfile.gettempdir()) / f"otampy_session_{os.getppid()}.txt"
    )
    if session_file.is_file():
        try:
            return session_file.read_text().strip()
        except Exception:
            pass

    # Check permanent config
    config_path = Path.home() / ".config" / "otampy" / "config.json"
    if config_path.is_file():
        import json

        try:
            with open(config_path) as f:
                data = json.load(f)
                return data.get("default_port")
        except Exception:
            pass
    return None


def set_default_port(port: str | None, session: bool = False) -> None:
    if session:
        import os
        import tempfile

        session_file = (
            Path(tempfile.gettempdir()) / f"otampy_session_{os.getppid()}.txt"
        )
        if port is None:
            if session_file.is_file():
                try:
                    session_file.unlink()
                except Exception:
                    pass
        else:
            try:
                session_file.write_text(port)
            except Exception as e:
                raise click.ClickException(
                    f"Failed to save session port: {e}"
                ) from e
        return

    import json

    config_dir = Path.home() / ".config" / "otampy"
    config_path = config_dir / "config.json"

    if port is None:
        if config_path.is_file():
            try:
                config_path.unlink()
            except Exception:
                pass
        return

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        data = {}
        if config_path.is_file():
            try:
                with open(config_path) as f:
                    data = json.load(f)
            except Exception:
                pass
        data["default_port"] = port
        with open(config_path, "w") as f:
            json.dump(data, f, indent=4)  # type: ignore
    except Exception as e:
        raise click.ClickException(f"Failed to save default port: {e}") from e


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(cls=AliasedGroup, context_settings=CONTEXT_SETTINGS)
@click.option(
    "-p",
    "--port",
    default=get_default_port,
    help="Serial port to connect to, for example /dev/ttyACM0 or COM3.",
)
@click.option(
    "-b",
    "--baud",
    default=57600,
    type=int,
    help="Baud rate to use for communication (default: 57600).",
)
@click.pass_context
def cli(ctx: click.Context, port: str | None, baud: int) -> None:
    """OTAmpy CLI - Over the air (OTA) file management for MicroPython devices."""
    ctx.ensure_object(dict)
    ctx.obj["port"] = port
    ctx.obj["baud"] = baud


def _friendly_error(err_msg: str, command: bytes) -> str:
    err_msg_lower = err_msg.lower()
    target = ""
    is_directory_err = (
        "eisdir" in err_msg_lower
        or "errno 21" in err_msg_lower
        or err_msg == "21"
    )
    try:
        cmd_str = command.decode("utf-8", errors="replace")
        parts = cmd_str.split(":", 1)
        if len(parts) > 1:
            name = parts[1]
            if is_directory_err and not name.endswith("/"):
                name += "/"
            target = f": '{name}'"
    except Exception:
        pass

    if (
        "enoent" in err_msg_lower
        or "errno 2" in err_msg_lower
        or err_msg == "2"
    ):
        return f"No such file or directory{target}"
    if (
        "eacces" in err_msg_lower
        or "errno 13" in err_msg_lower
        or err_msg == "13"
    ):
        return f"Permission denied{target}"
    if (
        "enospc" in err_msg_lower
        or "errno 28" in err_msg_lower
        or err_msg == "28"
    ):
        return "No space left on device"
    if (
        "eexist" in err_msg_lower
        or "errno 17" in err_msg_lower
        or err_msg == "17"
    ):
        return f"File or directory already exists{target}"
    if (
        "eisdir" in err_msg_lower
        or "errno 21" in err_msg_lower
        or err_msg == "21"
    ):
        return f"Is a directory{target}"
    if (
        "enotdir" in err_msg_lower
        or "errno 20" in err_msg_lower
        or err_msg == "20"
    ):
        return f"Not a directory{target}"
    if (
        "enotempty" in err_msg_lower
        or "errno 39" in err_msg_lower
        or err_msg == "39"
    ):
        return f"Directory not empty{target}"
    return err_msg


def _query(
    ctx: click.Context,
    command: bytes,
    expected_prefix: bytes,
    transport: Urst | None = None,
) -> tuple[bytes, Urst | None]:
    """Query device. If transport is provided, reuse it; otherwise create new.

    Returns: (response_data, transport_to_close_or_none)
    If transport was provided, returns (data, None) - caller manages connection.
    If transport was created, returns (data, transport) - caller should close it.
    """
    port = ctx.obj.get("port")
    baud = ctx.obj.get("baud")
    if not port:
        raise click.ClickException(
            "Error: Missing serial port. Specify with --port or -p option."
        )

    import time

    import serial
    from urst import Urst

    # If transport provided, use it directly (single attempt)
    if transport is not None:
        if not transport.send(command):
            raise click.ClickException("Failed to send command over transport.")

        response = transport.read()
        if not response:
            raise click.ClickException(
                f"Timeout waiting for response to command: {command.decode()}"
            )

        # Check for device error response
        if response.startswith(b"ERROR:"):
            err_msg = response[6:].decode("utf-8", errors="replace")
            raise DeviceError(err_msg, command)

        if not response.startswith(expected_prefix):
            resp_str = (
                response.decode("utf-8", errors="replace")
                if isinstance(response, bytes)
                else str(response)
            )
            raise click.ClickException(
                f"Unexpected response to command '{command.decode()}'. "
                f"Expected prefix '{expected_prefix.decode()}', got '{resp_str}'"
            )

        # Return payload after prefix and potential colon separator
        prefix_len = len(expected_prefix)
        if (
            len(response) > prefix_len
            and response[prefix_len : prefix_len + 1] == b":"
        ):
            res = response[prefix_len + 1 :]
        else:
            res = response[prefix_len:]

        return res, None

    # Create new transport with retry logic
    last_err = None

    for attempt in range(3):
        ser = None
        try:
            ser = serial.Serial(port, baudrate=baud, timeout=2.0)
            try:
                ser.dtr = False
                ser.rts = False
            except Exception:
                pass
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            new_transport = Urst(ser)

            # Clear any unsolicited messages (e.g. boot notifications) from the receive queue
            try:
                new_transport.protocol._recv_queue.clear()
            except Exception:
                pass

            # Attempt transmission & handshake inside retry loop to handle slow wireless connection wakeups
            if not new_transport.send(command):
                raise click.ClickException(
                    "Failed to send command over transport."
                )

            response = new_transport.read()
            if not response:
                raise click.ClickException(
                    f"Timeout waiting for response to command: {command.decode()}"
                )

            # Check for device error response
            if response.startswith(b"ERROR:"):
                err_msg = response[6:].decode("utf-8", errors="replace")
                ser.close()
                raise DeviceError(err_msg, command)

            if not response.startswith(expected_prefix):
                resp_str = (
                    response.decode("utf-8", errors="replace")
                    if isinstance(response, bytes)
                    else str(response)
                )
                ser.close()
                raise click.ClickException(
                    f"Unexpected response to command '{command.decode()}'. "
                    f"Expected prefix '{expected_prefix.decode()}', got '{resp_str}'"
                )

            # Return payload after prefix and potential colon separator
            prefix_len = len(expected_prefix)
            if (
                len(response) > prefix_len
                and response[prefix_len : prefix_len + 1] == b":"
            ):
                res = response[prefix_len + 1 :]
            else:
                res = response[prefix_len:]

            ser.close()
            return res, None

        except DeviceError:
            # Re-raise DeviceError without catching it in the broader exception handler
            raise
        except Exception as e:
            if ser:
                try:
                    ser.close()
                except Exception:
                    pass
            last_err = e
            if attempt < 1:
                time.sleep(0.25 * (2**attempt))

    raise click.ClickException(str(last_err))


def _handle_device_error(device_error: DeviceError) -> None:
    """Display a friendly error message and exit."""
    friendly = _friendly_error(device_error.error_msg, device_error.command)
    _console().print(f"[red]Error: {friendly}[/red]")
    raise SystemExit(1)


def _send_command(
    ctx: click.Context, command: bytes, expected_response: bytes
) -> None:
    """Send command and verify response (backward compatible)."""
    _query(ctx, command, expected_response)


@cli.command(name="ping")
@click.pass_context
def ping(ctx: click.Context) -> None:
    """Connection health check with the device."""
    _console().print("[yellow]Sending PING to device...[/yellow]")
    try:
        _send_command(ctx, b"PING", b"PONG")
    except DeviceError as e:
        _handle_device_error(e)
    _console().print("[green]Success: Received PONG from device.[/green]")


@cli.command(name="rb")
@click.pass_context
def reboot(ctx: click.Context) -> None:
    """Hard reboots the device."""
    if not click.confirm(
        click.style(
            "Are you sure you want to hard reboot the device?", fg="red"
        ),
        default=False,
    ):
        _console().print("[yellow]Aborted.[/yellow]")
        return
    _console().print("[yellow]Hard rebooting the device...[/yellow]")
    try:
        _send_command(ctx, b"RB", b"RB_OK")
    except DeviceError as e:
        _handle_device_error(e)


@cli.command(name="sr")
@click.pass_context
def soft_reset(ctx: click.Context) -> None:
    """Soft resets the device."""
    if not click.confirm(
        click.style(
            "Are you sure you want to soft reset the device?", fg="red"
        ),
        default=False,
    ):
        _console().print("[yellow]Aborted.[/yellow]")
        return
    _console().print("[yellow]Soft resetting the device...[/yellow]")
    try:
        _send_command(ctx, b"SR", b"SR_OK")
    except DeviceError as e:
        _handle_device_error(e)


@cli.command(name="ls")
@click.argument("path", required=False)
@click.pass_context
def list_dir(ctx: click.Context, path: str | None) -> None:
    """Lists content of current (or specified) folder on device."""
    if path:
        _console().print(f"[green]Listing content of {path}...[/green]")
        cmd = f"LS:{path}".encode()
    else:
        _console().print(
            "[green]Listing content of current directory...[/green]"
        )
        cmd = b"LS"

    try:
        resp, _ = _query(ctx, cmd, b"LS_OK")
    except DeviceError as e:
        _handle_device_error(e)
    items_str = resp.decode("utf-8", errors="replace")  # type: ignore
    if items_str:
        items = items_str.split(",")
        for item in items:
            _console().print(item)


@cli.command(name="cat")
@click.argument("file", required=True)
@click.pass_context
def cat(ctx: click.Context, file: str) -> None:
    """Shows content of specified file on device."""
    _console().print(
        f"[green]Showing content of specified file: {file}[/green]"
    )
    try:
        resp, _ = _query(ctx, f"CAT:{file}".encode(), b"CAT_OK")
    except DeviceError as e:
        _handle_device_error(e)
    content = resp.decode("utf-8", errors="replace")  # type: ignore
    _console().print(content)


def _recursive_rm_with_connection(ctx: click.Context, path: str) -> None:
    """Recursively remove directory using a persistent connection."""
    import serial
    from urst import Urst

    port = ctx.obj.get("port")
    baud = ctx.obj.get("baud")
    if not port:
        raise click.ClickException(
            "Error: Missing serial port. Specify with --port or -p option."
        )

    ser = None
    try:
        # Establish persistent connection
        ser = serial.Serial(port, baudrate=baud, timeout=2.0)
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        transport = Urst(ser)

        try:
            transport.protocol._recv_queue.clear()
        except Exception:
            pass

        # List directory contents
        resp, _ = _query(
            ctx, f"LS:{path}".encode(), b"LS_OK", transport=transport
        )
        items_str = resp.decode("utf-8", errors="replace")
        if items_str:
            items = items_str.split(",")
            for item in items:
                item = item.strip()
                if not item:
                    continue
                item_path = f"{path.rstrip('/')}/{item}"
                _console().print(f"  Removing: {item_path}")
                try:
                    _query(
                        ctx,
                        f"RM:{item_path}".encode(),
                        b"RM_OK",
                        transport=transport,
                    )
                except DeviceError as e:
                    # If it's a directory, recurse into it
                    friendly = _friendly_error(e.error_msg, e.command)
                    if "directory not empty" in friendly.lower():
                        _recursive_rm_with_connection(ctx, item_path)
                        # Try to remove the now-empty directory with same transport
                        try:
                            _query(
                                ctx,
                                f"RM:{item_path}".encode(),
                                b"RM_OK",
                                transport=transport,
                            )
                        except DeviceError:
                            # If still fails, move on to next item
                            pass
                    else:
                        raise
        # Finally remove the now-empty directory
        _query(ctx, f"RM:{path}".encode(), b"RM_OK", transport=transport)
    except DeviceError as e:
        friendly = _friendly_error(e.error_msg, e.command)
        _console().print(f"[red]Error: {friendly}[/red]")
        raise SystemExit(1) from None
    finally:
        if ser:
            try:
                ser.close()
            except Exception:
                pass


@cli.command(name="rm")
@click.argument("file", required=True)
@click.pass_context
def remove(ctx: click.Context, file: str) -> None:
    """Remove specified file or directory from device."""
    if not click.confirm(
        click.style(
            f"Are you sure you want to remove '{file}' from the device?",
            fg="red",
        ),
        default=False,
    ):
        _console().print("[yellow]Aborted.[/yellow]")
        return
    _console().print(f"[red]Removing file: {file}[/red]")
    try:
        _send_command(ctx, f"RM:{file}".encode(), b"RM_OK")
    except DeviceError as e:
        friendly = _friendly_error(e.error_msg, e.command)
        if "directory not empty" in friendly.lower():
            _console().print(f"[yellow]{friendly}[/yellow]")
            if click.confirm(
                "Directory is not empty. Remove all contents recursively?",
                default=False,
            ):
                _console().print(
                    "[yellow]Recursively removing directory on device...[/yellow]"
                )
                _recursive_rm_with_connection(ctx, file)
                _console().print(
                    "[green]Directory removed successfully.[/green]"
                )
            else:
                _console().print("[yellow]Aborted.[/yellow]")
        else:
            _console().print(f"[red]Error: {friendly}[/red]")
            raise SystemExit(1) from None


@cli.command(name="mem")
@click.pass_context
def memory_info(ctx: click.Context) -> None:
    """Queries and displays device memory (RAM and Storage/Flash) info."""
    _console().print("[yellow]Querying device memory info...[/yellow]")
    try:
        resp, _ = _query(ctx, b"MEM", b"MEM_OK")
    except DeviceError as e:
        _handle_device_error(e)
    payload = resp.decode("utf-8", errors="replace")  # type: ignore

    try:
        parts = payload.split(",")
        ram_free = int(parts[0])
        ram_alloc = int(parts[1])
        flash_free = int(parts[2])
        flash_total = int(parts[3])
    except (ValueError, IndexError) as e:
        raise click.ClickException(
            f"Invalid memory response from device: {payload}"
        ) from e

    ram_total = ram_free + ram_alloc
    ram_free_pct = (ram_free / ram_total * 100) if ram_total > 0 else 0
    ram_alloc_pct = (ram_alloc / ram_total * 100) if ram_total > 0 else 0

    flash_used = flash_total - flash_free
    flash_free_pct = (flash_free / flash_total * 100) if flash_total > 0 else 0
    flash_used_pct = (flash_used / flash_total * 100) if flash_total > 0 else 0

    def format_size(size_bytes: int) -> str:
        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        return f"{size_bytes / 1024:.1f} KB"

    _console().print()
    _console().print("[bold cyan]Memory Information:[/bold cyan]")
    _console().print()
    _console().print("[bold]RAM (Random Access Memory):[/bold]")
    _console().print(
        f"  Free:      {format_size(ram_free):<9} / {format_size(ram_total)} ({ram_free_pct:.1f}%)"
    )
    _console().print(
        f"  Allocated: {format_size(ram_alloc):<9} ({ram_alloc_pct:.1f}%)"
    )
    _console().print()
    _console().print("[bold]Flash (Storage):[/bold]")
    _console().print(
        f"  Free:      {format_size(flash_free):<9} / {format_size(flash_total)} ({flash_free_pct:.1f}%)"
    )
    _console().print(
        f"  Used:      {format_size(flash_used):<9} ({flash_used_pct:.1f}%)"
    )


def _get_files_to_send(args: tuple[str, ...]) -> list[tuple[str, Path]]:
    from pathlib import Path

    res = []

    if args:
        for arg in args:
            if ":" in arg:
                parts = arg.split(":")
                if (
                    len(parts[0]) == 1
                    and parts[0].isalpha()
                    and len(parts) > 1
                    and parts[1].startswith(("\\", "/"))
                ):
                    if len(parts) > 2:
                        src_str = parts[0] + ":" + parts[1]
                        target_str = parts[2]
                    else:
                        src_str = arg
                        target_str = None
                else:
                    src_str = parts[0]
                    target_str = parts[1] if len(parts) > 1 else None
            else:
                src_str = arg
                target_str = None

            p = Path(src_str)
            if p.is_file():
                if target_str is not None:
                    if target_str.endswith("/") or target_str.endswith("\\"):
                        target_path = target_str.rstrip("/\\") + "/" + p.name
                    else:
                        target_path = target_str
                else:
                    try:
                        target_path = str(p.relative_to(Path.cwd()))
                    except ValueError:
                        target_path = str(p)
                res.append((target_path.replace("\\", "/"), p))
            elif p.is_dir():
                for f in p.rglob("*.py"):
                    rel = f.relative_to(p)
                    if target_str is not None:
                        target_path = target_str.rstrip("/\\") + "/" + str(rel)
                    else:
                        try:
                            target_path = str(f.relative_to(Path.cwd()))
                        except ValueError:
                            target_path = str(f)
                    res.append((target_path.replace("\\", "/"), f))
    else:
        p_main = Path("main.py")
        if p_main.is_file():
            res.append((str(p_main).replace("\\", "/"), p_main))
        p_lib = Path("lib")
        if p_lib.is_dir():
            for f in p_lib.rglob("*.py"):
                try:
                    rel_path = str(f.relative_to(Path.cwd()))
                except ValueError:
                    rel_path = str(f)
                res.append((rel_path.replace("\\", "/"), f))

    # Validate for conflicts
    import click

    target_paths = [t for t, _ in res]
    for i, t1 in enumerate(target_paths):
        for j, t2 in enumerate(target_paths):
            if i != j:
                if t1 == t2:
                    raise click.ClickException(
                        f"Conflict: Multiple files mapped to the same destination '{t1}'"
                    )
                if t2.startswith(t1 + "/"):
                    raise click.ClickException(
                        f"Conflict: Destination '{t1}' is mapped as a file, "
                        f"but also used as a directory for '{t2}'"
                    )

    return res


@cli.command(name="upd")
@click.argument("args", nargs=-1)
@click.pass_context
def update(ctx: click.Context, args: tuple[str, ...]) -> None:
    """Updates application firmware on device."""
    # 0. Scan and collect files to send locally before touching device
    files_to_send = _get_files_to_send(args)
    if not files_to_send:
        _console().print("[yellow]No files found to transfer.[/yellow]")
        return

    import hashlib

    # Calculate total manifest size
    total_bytes = 0
    manifest = []
    for target_path, local_path in files_to_send:
        try:
            with open(local_path, "rb") as f:
                content = f.read()
            size = len(content)
            sha256 = hashlib.sha256(content).hexdigest()
            total_bytes += size
            manifest.append((target_path, local_path, size, sha256, content))
        except OSError as e:
            raise click.ClickException(
                f"Failed to read local file {local_path}: {e}"
            ) from e

    _console().print("[yellow]Initiating update handshake...[/yellow]")

    # 1. Send UPDATE_REQUEST to device runtime (main.py)
    _send_command(ctx, b"UPDATE_REQUEST", b"REBOOTING")
    _console().print(
        "[yellow]Device acknowledged update request. Rebooting...[/yellow]"
    )

    # 2. Wait for device to boot up and broadcast READY
    port = ctx.obj.get("port")
    baud = ctx.obj.get("baud")
    if not port:
        raise click.ClickException(
            "Error: Missing serial port. Specify with --port or -p option."
        )

    import binascii
    import time

    import serial
    from urst import Urst

    time.sleep(0.5)

    start_time = time.time()
    timeout = 10.0
    transport = None
    ser = None

    while time.time() - start_time < timeout:
        try:
            if ser is None:
                ser = serial.Serial(port, baudrate=baud, timeout=1.0)
                try:
                    ser.dtr = False
                    ser.rts = False
                except Exception:
                    pass
                ser.reset_input_buffer()
                ser.reset_output_buffer()
                transport = Urst(ser)

            resp = transport.read()  # type: ignore
            if resp == b"READY":
                break
        except Exception:
            if ser:
                ser.close()
                ser = None
                transport = None
            time.sleep(0.2)

    if not transport or not ser:
        raise click.ClickException(
            "Timeout waiting for device READY broadcast."
        )

    _console().print("[green]Device is READY. Handshake complete.[/green]")

    # 4. Start update session: UPDATE_START
    _console().print(
        f"Sending manifest ({len(manifest)} files, {total_bytes} bytes)..."
    )
    try:
        transport.send(f"UPDATE_START:{len(manifest)}:{total_bytes}".encode())
        resp = transport.read()
        if resp != b"SPACE_OK":
            raise click.ClickException(
                f"Device rejected manifest. Response: {resp.decode('utf-8', errors='replace') if resp else 'None'}"
            )

        # 5. Send files sequentially
        chunk_size = 256
        for target_path, _local_path, size, sha256, content in manifest:
            _console().print(f"Transferring {target_path} ({size} bytes)...")

            # Send FILE_START
            transport.send(f"FILE_START:{target_path}:{size}:{sha256}".encode())
            resp = transport.read()
            if resp != b"FILE_OK":
                raise click.ClickException(
                    f"Device failed to initialize file transfer for {target_path}: "
                    f"{resp.decode('utf-8', errors='replace') if resp else 'None'}"
                )

            # Send chunks
            num_chunks = (size + chunk_size - 1) // chunk_size
            for i in range(num_chunks):
                chunk_data = content[i * chunk_size : (i + 1) * chunk_size]
                b64_chunk = (
                    binascii.b2a_base64(chunk_data).strip().decode("utf-8")
                )

                transport.send(f"CHUNK:{i}:{b64_chunk}".encode())
                resp = transport.read()
                if resp != f"CHUNK_ACK:{i}".encode():
                    raise click.ClickException(
                        f"Chunk {i} transmission failed for {target_path}: "
                        f"{resp.decode('utf-8', errors='replace') if resp else 'None'}"
                    )

            # Send FILE_END
            transport.send(b"FILE_END")
            resp = transport.read()
            if resp != b"FILE_OK":
                raise click.ClickException(
                    f"Device verification failed for {target_path}: "
                    f"{resp.decode('utf-8', errors='replace') if resp else 'None'}"
                )

        # 6. Commit transaction: UPDATE_COMMIT
        _console().print("Committing update transaction...")
        transport.send(b"UPDATE_COMMIT")
        resp = transport.read()
        if resp != b"COMMIT_OK":
            raise click.ClickException(
                f"Device commit failed: {resp.decode('utf-8', errors='replace') if resp else 'None'}"
            )

        _console().print(
            "[green]Update completed successfully! Device is rebooting.[/green]"
        )
    finally:
        ser.close()


@cli.command(name="ports")
@click.option("--set", "set_port", help="Set the default port permanently.")
@click.option("--clear", is_flag=True, help="Clear the default port settings.")
@click.option("--show", is_flag=True, help="Show the current default port.")
def ports_cmd(set_port: str | None, clear: bool, show: bool) -> None:
    """List available serial ports and manage the default port."""
    import serial.tools.list_ports

    if show:
        p = get_default_port()
        if p:
            _console().print(f"Current default port: [green]{p}[/green]")
        else:
            _console().print("No default port set.")
        return

    if clear:
        set_default_port(None)
        set_default_port(None, session=True)
        _console().print("[green]Default ports cleared.[/green]")
        return

    if set_port:
        set_default_port(set_port)
        _console().print(
            f"[green]Permanent default port set to: {set_port}[/green]"
        )
        return

    # Interactive / Listing mode
    ports = [p for p in serial.tools.list_ports.comports() if p.hwid != "n/a"]
    if not ports:
        _console().print("No available serial ports found.")
        return

    _console().print("[bold]Available serial ports:[/bold]")
    current_default = get_default_port()

    for idx, port_info in enumerate(ports, 1):
        is_default = (
            " [green][default][/green]"
            if port_info.device == current_default
            else ""
        )
        desc = (
            f" ({port_info.description})"
            if port_info.description and port_info.description != "n/a"
            else ""
        )
        _console().print(
            f"  [bold]{idx}[/bold]: [cyan]{port_info.device}[/cyan]{desc}{is_default}"
        )

    # Ask the user to select a port
    selection = click.prompt(
        "\nSelect a port number to set as default (or press Enter to cancel)",
        default="",
        show_default=False,
    )
    if not selection.strip():
        _console().print("Cancelled.")
        return

    try:
        port_idx = int(selection) - 1
        if port_idx < 0 or port_idx >= len(ports):
            raise ValueError()
    except ValueError as e:
        raise click.ClickException("Invalid selection.") from e

    selected_port = ports[port_idx].device

    # Ask if session or permanent
    choice = click.prompt(
        f"Set {selected_port} as default? (p=permanent, s=session command, c=cancel) [p/s/c]",
        default="s",
    ).lower()

    if choice == "p":
        set_default_port(selected_port)
        _console().print(
            f"[green]Permanent default port set to: {selected_port}[/green]"
        )
    elif choice == "s":
        set_default_port(selected_port, session=True)
        _console().print(
            f"[green]Session default port set to: {selected_port}[/green]"
        )
    else:
        _console().print("Cancelled.")


@cli.command(name="deploy")
@click.option(
    "-p",
    "--port",
    help="Serial port to connect to, for example /dev/ttyACM0 or COM3.",
    default=get_default_port,
)
@click.option(
    "--mpremote",
    default="mpremote",
    help="mpremote executable to use.",
)
@click.option(
    "--no-mip",
    is_flag=True,
    help="Skip installing MicroPython dependencies with mip.",
)
@click.option(
    "--with-logger",
    is_flag=True,
    help="Install log-to-file for development logging.",
)
@click.option(
    "--no-reset",
    is_flag=True,
    help="Skip resetting the device after deployment.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print mpremote commands without running them.",
)
def deploy_cmd(
    port: str | None,
    mpremote: str,
    no_mip: bool,
    with_logger: bool,
    no_reset: bool,
    dry_run: bool,
) -> None:
    """Deploy OTAmpy lib/, boot.py, and main.py to a MicroPython device."""
    args = deploy.DeployArgs(
        port=port,  # type: ignore
        mpremote=mpremote,  # type: ignore
        no_mip=no_mip,  # type: ignore
        with_logger=with_logger,  # type: ignore
        no_reset=no_reset,  # type: ignore
        dry_run=dry_run,  # type: ignore
    )
    try:
        deploy.deploy(args)
    except FileNotFoundError as error:
        raise click.ClickException(
            f"Could not find {error.filename!r}. Install mpremote with `uv tool install mpremote` or pass --mpremote."
        ) from error
    except deploy.DeployError as error:
        deploy.print_deploy_error(error)
        ctx = click.get_current_context()
        ctx.exit(error.returncode or 1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
