from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.console import Console

import otampy.deploy as deploy
import otampy.project as project

if TYPE_CHECKING:
    from urst import Urst

logger = logging.getLogger(__name__)

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


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
            "copy": "cp",
            "reboot": "rb",
            "reset": "sr",
            "softreset": "sr",
            "remove": "rm",
            "update": "upd",
            "memory": "mem",
            "loglevel": "log-level",
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
    port = _read_json(_config_path()).get("default_port")
    return port if isinstance(port, str) else None


def _config_path() -> Path:
    return Path.home() / ".config" / "otampy" / "config.json"


def _session_config_path() -> Path:
    import os
    import tempfile

    return Path(tempfile.gettempdir()) / f"otampy_session_{os.getppid()}.json"


def _read_json(path: Path) -> dict:
    import json

    if not path.is_file():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    import json

    if not data:
        if path.is_file():
            path.unlink()
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


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

    try:
        config_path = _config_path()
        data = _read_json(config_path)
        if port is None:
            data.pop("default_port", None)
        else:
            data["default_port"] = port
        _write_json(config_path, data)
    except Exception as e:
        raise click.ClickException(f"Failed to save default port: {e}") from e


def get_default_log_level() -> str:
    import os

    if "OTAMPY_LOG_LEVEL" in os.environ:
        return os.environ["OTAMPY_LOG_LEVEL"].upper()

    for path in (_session_config_path(), _config_path()):
        value = _read_json(path).get("log_level")
        if isinstance(value, str) and value.upper() in LOG_LEVELS:
            return value.upper()

    return "ERROR"


def set_default_log_level(level: str | None, session: bool = False) -> None:
    path = _session_config_path() if session else _config_path()
    try:
        data = _read_json(path)
        if level is None:
            data.pop("log_level", None)
        else:
            data["log_level"] = level.upper()
        _write_json(path, data)
    except Exception as e:
        scope = "session" if session else "permanent"
        raise click.ClickException(
            f"Failed to save {scope} log level: {e}"
        ) from e


def _offer_to_save_log_level(level: str) -> None:
    choice = click.prompt(
        f"Keep {level} as the log level? "
        "(p=permanent, s=session, c=current command only)",
        type=click.Choice(("p", "s", "c"), case_sensitive=False),
        default="c",
    ).lower()

    if choice == "p":
        set_default_log_level(level)
        set_default_log_level(None, session=True)
        _console().print(f"[green]Permanent log level set to: {level}[/green]")
    elif choice == "s":
        set_default_log_level(level, session=True)
        _console().print(f"[green]Session log level set to: {level}[/green]")


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
@click.option(
    "--log-level",
    type=click.Choice(LOG_LEVELS, case_sensitive=False),
    default=get_default_log_level,
    help="CLI logging verbosity for this command. Use 'otampy log-level' to view or save the default.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    port: str | None,
    baud: int,
    log_level: str,
) -> None:
    """OTAmpy CLI - Over the air (OTA) file management for MicroPython devices."""
    log_level = log_level.upper()
    logging.getLogger().setLevel(getattr(logging, log_level))

    ctx.ensure_object(dict)
    ctx.obj["port"] = port
    ctx.obj["baud"] = baud
    ctx.obj["log_level"] = log_level


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
        or "directory not empty" in err_msg_lower
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


def _join_remote_path(parent: str, name: str) -> str:
    name = name.rstrip("/")
    if parent == "/":
        return f"/{name}"
    if parent in ("", "."):
        return name
    return f"{parent.rstrip('/')}/{name}"


def _remote_directory_entries(
    ctx: click.Context, path: str
) -> list[tuple[str, bool, str]]:
    command = b"LS" if path in ("", ".") else f"LS:{path}".encode()
    resp, _ = _query(ctx, command, b"LS_OK")
    entries = []
    for item in resp.decode("utf-8", errors="replace").split(","):
        item = item.strip()
        if not item:
            continue
        is_dir = item.endswith("/")
        name = item.rstrip("/")
        entries.append((_join_remote_path(path, name), is_dir, name))
    return entries


def _canonical_remote_argument(path: str) -> str:
    return path[1:] if path.startswith(":") else path


def _expand_remote_pattern(ctx: click.Context, pattern: str) -> list[str]:
    """Expand one remote glob using directory listings from the device."""
    from fnmatch import fnmatchcase

    pattern = _canonical_remote_argument(pattern)
    segments = [
        segment for segment in pattern.split("/") if segment not in ("", ".")
    ]
    if not segments:
        return []

    matches = []
    start = "/" if pattern.startswith("/") else ""

    def walk(parent: str, index: int) -> None:
        segment = segments[index]
        final_segment = index == len(segments) - 1

        if segment == "**":
            if final_segment:
                for path, is_dir, _name in _remote_directory_entries(
                    ctx, parent
                ):
                    if is_dir:
                        walk(path, index)
                    matches.append(path)
                return

            walk(parent, index + 1)
            for path, is_dir, _name in _remote_directory_entries(ctx, parent):
                if is_dir:
                    walk(path, index)
            return

        has_magic = any(char in segment for char in "*?[")
        if has_magic:
            for path, is_dir, name in _remote_directory_entries(ctx, parent):
                if not fnmatchcase(name, segment):
                    continue
                if final_segment:
                    matches.append(path)
                elif is_dir:
                    walk(path, index + 1)
            return

        path = _join_remote_path(parent, segment)
        if final_segment:
            matches.append(path)
        else:
            walk(path, index + 1)

    walk(start, 0)
    return list(dict.fromkeys(matches))


def _expand_remote_targets(
    ctx: click.Context, patterns: tuple[str, ...]
) -> list[str]:
    targets = []
    unmatched = []
    for pattern in patterns:
        pattern = _canonical_remote_argument(pattern)
        if any(char in pattern for char in "*?["):
            try:
                matches = _expand_remote_pattern(ctx, pattern)
            except DeviceError as e:
                raise click.ClickException(
                    _friendly_error(e.error_msg, e.command)
                ) from e
            if not matches:
                unmatched.append(pattern)
            targets.extend(matches)
        else:
            targets.append(pattern.rstrip("/") or "/")

    if unmatched:
        raise click.ClickException(
            "No remote paths matched: " + ", ".join(unmatched)
        )
    return list(dict.fromkeys(targets))


_PROTECTED_RECOVERY_PATHS = (
    "boot.py",
    "main.py",
    "config.py",
    "lib/otampy",
    "lib/urst",
)


def _normalize_remote_path(path: str) -> str:
    from posixpath import normpath

    path = _canonical_remote_argument(path)
    normalized = normpath("/" + path.replace("\\", "/").lstrip("/"))
    return normalized.lstrip("/")


def _is_protected_recovery_path(path: str) -> bool:
    normalized = _normalize_remote_path(path)
    if not normalized:
        return True
    return any(
        normalized == protected
        or normalized.startswith(protected + "/")
        or protected.startswith(normalized + "/")
        for protected in _PROTECTED_RECOVERY_PATHS
    )


def _validate_removal_targets(targets: list[str]) -> None:
    protected = [
        target for target in targets if _is_protected_recovery_path(target)
    ]
    if protected:
        raise click.ClickException(
            "Refusing to remove protected recovery path(s): "
            + ", ".join(protected)
            + ". Replace them with 'otampy cp' or 'otampy upd'."
        )


def _validate_remote_only_arguments(
    files: tuple[str, ...], literal_remote_paths: bool
) -> None:
    if literal_remote_paths:
        return
    local_matches = [
        file
        for file in files
        if not file.startswith(":") and Path(file).exists()
    ]
    if local_matches:
        raise click.ClickException(
            "RM only deletes paths on the remote device, but these arguments "
            "also exist locally and may have been expanded by your shell: "
            + ", ".join(local_matches)
            + ". No local files were changed. Quote remote wildcards, for "
            "example: otampy rm '*'. If the matching names are intentional "
            "remote paths, add --literal-remote-paths."
        )


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

        def remove_directory(directory: str) -> None:
            resp, _ = _query(
                ctx,
                f"LS:{directory}".encode(),
                b"LS_OK",
                transport=transport,
            )
            for item in resp.decode("utf-8", errors="replace").split(","):
                item = item.strip()
                if not item:
                    continue
                is_dir = item.endswith("/")
                item_path = _join_remote_path(directory, item)
                if is_dir:
                    remove_directory(item_path)
                else:
                    _console().print(
                        f"  Removing remote path: {item_path}"
                    )
                    _query(
                        ctx,
                        f"RM:{item_path}".encode(),
                        b"RM_OK",
                        transport=transport,
                    )
            _console().print(f"  Removing remote path: {directory}")
            _query(
                ctx,
                f"RM:{directory}".encode(),
                b"RM_OK",
                transport=transport,
            )

        remove_directory(path.rstrip("/"))
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
@click.option(
    "--literal-remote-paths",
    is_flag=True,
    help="Allow remote path names that also exist on the local filesystem.",
)
@click.argument("files", nargs=-1, required=True)
@click.pass_context
def remove(
    ctx: click.Context,
    literal_remote_paths: bool,
    files: tuple[str, ...],
) -> None:
    """Remove files, directories, or glob matches from the remote device."""
    _validate_removal_targets(list(files))
    _validate_remote_only_arguments(files, literal_remote_paths)
    targets = _expand_remote_targets(ctx, files)
    _validate_removal_targets(targets)
    target_summary = (
        f"'{targets[0]}'"
        if len(targets) == 1
        else f"these {len(targets)} paths: {', '.join(targets)}"
    )
    if not click.confirm(
        click.style(
            f"Are you sure you want to remove {target_summary} "
            "from the remote device?",
            fg="red",
        ),
        default=False,
    ):
        _console().print("[yellow]Aborted.[/yellow]")
        return

    for file in targets:
        _console().print(f"[red]Removing remote path: {file}[/red]")
        try:
            _send_command(ctx, f"RM:{file}".encode(), b"RM_OK")
        except DeviceError as e:
            friendly = _friendly_error(e.error_msg, e.command)
            if "directory not empty" in friendly.lower():
                _console().print(f"[yellow]{friendly}[/yellow]")
                if click.confirm(
                    "Remote directory is not empty. "
                    "Remove all contents recursively?",
                    default=False,
                ):
                    _console().print(
                        "[yellow]Recursively removing directory on "
                        "device...[/yellow]"
                    )
                    _recursive_rm_with_connection(ctx, file)
                    _console().print(
                        "[green]Directory removed successfully.[/green]"
                    )
                else:
                    _console().print("[yellow]Skipped.[/yellow]")
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


def _split_update_arg(arg: str) -> tuple[str, str | None]:
    separator = arg.find(":")
    if (
        separator == 1
        and arg[0].isalpha()
        and len(arg) > 2
        and arg[2] in ("\\", "/")
    ):
        separator = arg.find(":", 3)
    if separator < 0:
        return arg, None
    return arg[:separator], arg[separator + 1 :]


def _update_target_path(
    source: Path, target: str | None, multiple_matches: bool
) -> str:
    if target is not None:
        target_is_dir = target.endswith(("/", "\\"))
        if multiple_matches and not target_is_dir:
            raise click.ClickException(
                "A wildcard matching multiple files requires a destination "
                f"directory ending in '/': {target}"
            )
        if target_is_dir:
            return target.rstrip("/\\") + "/" + source.name
        return target

    try:
        return str(source.relative_to(Path.cwd()))
    except ValueError:
        return str(source)


def _get_files_to_send(
    args: tuple[str, ...], *, python_only: bool = True
) -> list[tuple[str, Path]]:
    from glob import glob, has_magic

    res = []
    unmatched = []

    if args:
        for arg in args:
            src_str, target_str = _split_update_arg(arg)
            if has_magic(src_str):
                sources = [
                    Path(match)
                    for match in sorted(glob(src_str, recursive=True))
                ]
            else:
                source = Path(src_str)
                sources = [source] if source.exists() else []

            matched_files = []
            for source in sources:
                if source.is_file():
                    matched_files.append((source, None))
                elif source.is_dir():
                    pattern = "*.py" if python_only else "*"
                    matched_files.extend(
                        (file, file.relative_to(source))
                        for file in sorted(source.rglob(pattern))
                        if file.is_file()
                    )

            if not matched_files:
                unmatched.append(src_str)
                continue

            multiple_matches = len(matched_files) > 1
            for source, relative in matched_files:
                if relative is None:
                    target_path = _update_target_path(
                        source, target_str, multiple_matches
                    )
                elif target_str is not None:
                    target_path = target_str.rstrip("/\\") + "/" + str(relative)
                else:
                    try:
                        target_path = str(source.relative_to(Path.cwd()))
                    except ValueError:
                        target_path = str(source)
                res.append((target_path.replace("\\", "/"), source))

        if unmatched:
            raise click.ClickException(
                "No local files matched: " + ", ".join(unmatched)
            )
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


def _copy_requires_reboot(target: str) -> bool:
    normalized = target.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    return normalized in ("boot.py", "main.py")


@cli.command(name="cp")
@click.argument("args", nargs=-1, required=True)
@click.pass_context
def copy_files(ctx: click.Context, args: tuple[str, ...]) -> None:
    """Copy files or directories without rebooting the device."""
    files_to_send = _get_files_to_send(args, python_only=False)

    port = ctx.obj.get("port")
    baud = ctx.obj.get("baud")
    if not port:
        raise click.ClickException(
            "Error: Missing serial port. Specify with --port or -p option."
        )

    import binascii
    import hashlib

    import serial
    from urst import Urst

    ser = serial.Serial(port, baudrate=baud, timeout=2.0)
    try:
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

        reboot_targets = []
        transfer_active = False
        try:
            for target_path, local_path in files_to_send:
                hasher = hashlib.sha256()
                size = 0
                try:
                    with open(local_path, "rb") as source:
                        while True:
                            block = source.read(4096)
                            if not block:
                                break
                            hasher.update(block)
                            size += len(block)
                except OSError as e:
                    raise click.ClickException(
                        f"Failed to read local file {local_path}: {e}"
                    ) from e

                digest = hasher.hexdigest()
                _console().print(
                    f"Copying {local_path} to {target_path} ({size} bytes)..."
                )
                transfer_active = True
                _query(
                    ctx,
                    f"CP_START:{target_path}:{size}:{digest}".encode(),
                    b"CP_READY",
                    transport=transport,
                )

                with open(local_path, "rb") as source:
                    sequence = 0
                    while True:
                        chunk = source.read(256)
                        if not chunk:
                            break
                        encoded = binascii.b2a_base64(chunk).strip()
                        response, _ = _query(
                            ctx,
                            b"CP_CHUNK:"
                            + str(sequence).encode()
                            + b":"
                            + encoded,
                            b"CP_ACK",
                            transport=transport,
                        )
                        if response != str(sequence).encode():
                            raise click.ClickException(
                                "Unexpected copy acknowledgement for "
                                f"{target_path}: {response!r}"
                            )
                        sequence += 1

                _query(
                    ctx,
                    b"CP_END",
                    b"CP_OK",
                    transport=transport,
                )
                transfer_active = False
                if _copy_requires_reboot(target_path):
                    reboot_targets.append(
                        "/" + target_path.replace("\\", "/").lstrip("/")
                    )
                _console().print(
                    f"[green]Copied {target_path} successfully.[/green]"
                )
        except DeviceError as e:
            raise click.ClickException(
                _friendly_error(e.error_msg, e.command)
            ) from e
        except OSError as e:
            raise click.ClickException(f"Failed to read local file: {e}") from e
        finally:
            if transfer_active:
                try:
                    _query(
                        ctx,
                        b"CP_ABORT",
                        b"CP_ABORTED",
                        transport=transport,
                    )
                except Exception:
                    pass
            if reboot_targets:
                targets = ", ".join(dict.fromkeys(reboot_targets))
                _console().print(
                    f"[yellow]Reboot required: {targets} will not take effect "
                    "until the device restarts.[/yellow]"
                )
    finally:
        ser.close()


@cli.command(name="upd")
@click.argument("args", nargs=-1)
@click.pass_context
def update(ctx: click.Context, args: tuple[str, ...]) -> None:
    """Reboot & update files or directories on the device."""
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
@click.pass_context
def ports_cmd(
    ctx: click.Context, set_port: str | None, clear: bool, show: bool
) -> None:
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
        set_default_port(None, session=True)
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
    selected_port = ctx.obj.get("port")

    for idx, port_info in enumerate(ports, 1):
        details = []
        if port_info.serial_number:
            details.append(port_info.serial_number)
        if port_info.vid is not None and port_info.pid is not None:
            details.append(f"{port_info.vid:04x}:{port_info.pid:04x}")
        if port_info.manufacturer:
            details.append(port_info.manufacturer)
        if port_info.product:
            details.append(port_info.product)
        elif port_info.description and port_info.description != "n/a":
            details.append(port_info.description)

        port_summary = " ".join((port_info.device, *details))
        if port_info.device == selected_port:
            _console().print(
                f"  [bold green]* {idx}: {port_summary}[/bold green]"
            )
        else:
            _console().print(
                f"    [bold]{idx}[/bold]: [cyan]{port_summary}[/cyan]"
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
        set_default_port(None, session=True)
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


@cli.command(name="log-level")
@click.option("--show", is_flag=True, help="Show the current default log level.")
@click.option(
    "--set",
    "set_level",
    type=click.Choice(LOG_LEVELS, case_sensitive=False),
    help="Set the default log level permanently.",
)
@click.option("--clear", is_flag=True, help="Clear the saved log level (resets to ERROR).")
def log_level_cmd(show: bool, set_level: str | None, clear: bool) -> None:
    """Show or manage the saved CLI log level.

    With no options, lists available levels and prompts to choose one.
    The saved level is used as the default for every subsequent command.
    Override it for a single command with 'otampy --log-level LEVEL <cmd>'.
    """
    if show:
        level = get_default_log_level()
        _console().print(f"Current log level: [green]{level}[/green]")
        return

    if clear:
        set_default_log_level(None)
        set_default_log_level(None, session=True)
        _console().print("[green]Saved log level cleared (will default to ERROR).[/green]")
        return

    if set_level:
        set_default_log_level(set_level.upper())
        set_default_log_level(None, session=True)
        _console().print(
            f"[green]Permanent log level set to: {set_level.upper()}[/green]"
        )
        return

    # Interactive mode — show current and prompt to change
    current = get_default_log_level()
    _console().print(f"Current log level: [bold]{current}[/bold]")
    _console().print(
        f"Available levels: {', '.join(LOG_LEVELS)}"
    )

    selection = click.prompt(
        "\nEnter a log level to set as default (or press Enter to cancel)",
        default="",
        show_default=False,
    ).strip().upper()

    if not selection:
        _console().print("Cancelled.")
        return

    if selection not in LOG_LEVELS:
        raise click.ClickException(
            f"Invalid log level '{selection}'. "
            f"Choose from: {', '.join(LOG_LEVELS)}"
        )

    choice = click.prompt(
        f"Set {selection} as default? (p=permanent, s=session, c=cancel) [p/s/c]",
        default="p",
    ).strip().lower()

    if choice == "p":
        set_default_log_level(selection)
        set_default_log_level(None, session=True)
        _console().print(f"[green]Permanent log level set to: {selection}[/green]")
    elif choice == "s":
        set_default_log_level(selection, session=True)
        _console().print(f"[green]Session log level set to: {selection}[/green]")
    else:
        _console().print("Cancelled.")


@cli.command(name="init")
@click.argument(
    "directory",
    type=click.Path(path_type=Path, file_okay=False),
    default=".",
)
@click.option(
    "--force",
    is_flag=True,
    help="Replace existing project-owned device files.",
)
def init_cmd(directory: Path, force: bool) -> None:
    """Create boot.py, main.py, and config.py for an OTAmpy project."""
    try:
        created = project.initialise_project(directory, force=force)
    except project.ProjectError as error:
        raise click.ClickException(str(error)) from error

    root = directory.expanduser().resolve()
    _console().print(f"[green]Initialised OTAmpy project in {root}[/green]")
    for path in created:
        _console().print(f"  {path.relative_to(root)}")
    _console().print("Edit device/config.py before deploying.")


@cli.command(name="deploy")
@click.option(
    "-p",
    "--port",
    help="Serial port to connect to, for example /dev/ttyACM0 or COM3.",
    default=get_default_port,
)
@click.option(
    "--project",
    type=click.Path(path_type=Path, file_okay=False),
    default=".",
    show_default=True,
    help="Project directory containing device/.",
)
@click.option(
    "--mpremote",
    default="mpremote",
    help="mpremote executable to use.",
)
@click.option(
    "--no-mip",
    is_flag=True,
    help="Skip installing all MicroPython dependencies with mip.",
)
@click.option(
    "--with-logger",
    is_flag=True,
    help="Install log-to-file for development logging.",
)
@click.option(
    "--bytecode",
    "--mpy",
    is_flag=True,
    help="Deploy target-matched .mpy libraries.",
)
@click.option(
    "--mpy-cross",
    default="mpy-cross",
    help="mpy-cross executable or command to use.",
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
    project: Path,
    mpremote: str,
    no_mip: bool,
    with_logger: bool,
    bytecode: bool,
    mpy_cross: str,
    no_reset: bool,
    dry_run: bool,
) -> None:
    """Erase and deploy OTAmpy, examples, and device dependencies."""
    args = deploy.DeployArgs(
        port=port,  # type: ignore
        mpremote=mpremote,  # type: ignore
        no_mip=no_mip,  # type: ignore
        with_logger=with_logger,  # type: ignore
        bytecode=bytecode,  # type: ignore
        mpy_cross=mpy_cross,  # type: ignore
        no_reset=no_reset,  # type: ignore
        dry_run=dry_run,  # type: ignore
        project=project,
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
    except deploy.BytecodeDeployError as error:
        raise click.ClickException(str(error)) from error


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
