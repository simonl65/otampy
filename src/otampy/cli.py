from __future__ import annotations

import hashlib
import importlib.resources
import logging
import time
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.console import Console

import otampy.deploy as deploy
import otampy.minify as source_minify

if TYPE_CHECKING:
    from urst import Urst

logger = logging.getLogger(__name__)
MONOTONIC = time.perf_counter

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

MAX_TX_BUFFER_BYTES = 2048

CONFIG_SETTINGS = {
    "serial_timeout_seconds": {
        "display": "serial-timeout",
        "env": "OTAMPY_SERIAL_TIMEOUT",
        "default": 2.0,
        "type": float,
        "description": "Serial read timeout in seconds.",
    },
    "query_retries": {
        "display": "query-retries",
        "env": "OTAMPY_QUERY_RETRIES",
        "default": 3,
        "type": int,
        "description": "Connection attempts for one-shot CLI queries.",
    },
    "query_retry_backoff_seconds": {
        "display": "query-retry-backoff",
        "env": "OTAMPY_QUERY_RETRY_BACKOFF",
        "default": 0.25,
        "type": float,
        "description": "Initial retry backoff in seconds for one-shot CLI queries.",
    },
    "update_ready_timeout_seconds": {
        "display": "update-ready-timeout",
        "env": "OTAMPY_UPDATE_READY_TIMEOUT",
        "default": 10.0,
        "type": float,
        "description": "Seconds to wait for the boot-time READY broadcast during upd.",
    },
    "transfer_chunk_size": {
        "display": "transfer-chunk-size",
        "env": "OTAMPY_TRANSFER_CHUNK_SIZE",
        "default": 256,
        "type": int,
        "description": "Bytes per host transfer chunk. Must not exceed your serial module's (e.g. XBee) transmit buffer size.",
    },
}

_CONFIG_DISPLAY_TO_KEY = {setting["display"]: key for key, setting in CONFIG_SETTINGS.items()}


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

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
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
            "devicedir": "device-dir",
        }
        if normalized_name in aliases:
            return click.Group.get_command(self, ctx, aliases[normalized_name])
        return None

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted(click.Group.list_commands(self, ctx))


def _detect_project_root() -> Path:
    """Walk up from cwd to find the project root.

    Recognises .git, pyproject.toml, uv.lock, or setup.py as root markers.
    Falls back to cwd when none are found (e.g. running outside any project).
    """
    here = Path.cwd().resolve()
    for p in (here, *here.parents):
        if any((p / marker).exists() for marker in (".git", "pyproject.toml", "uv.lock", "setup.py")):
            return p
    return here


def _config_path() -> Path:
    return Path.home() / ".config" / "otampy" / "config.json"


def _session_id() -> str:
    """Return an identifier shared by commands in the current shell session."""
    import os
    import sys

    if sys.platform == "win32":
        try:
            import ctypes

            session_id = ctypes.c_ulong()
            if ctypes.windll.kernel32.ProcessIdToSessionId(  # type: ignore[attr-defined]
                os.getpid(), ctypes.byref(session_id)
            ):
                return f"win-{session_id.value}"
        except (AttributeError, OSError):
            pass

    return str(os.getppid())


def _session_config_path() -> Path:
    import tempfile

    return Path(tempfile.gettempdir()) / f"otampy_session_{_session_id()}.json"


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
        json.dump(data, f, indent=4)  # type: ignore


def _migrate_flat_keys(data: dict) -> dict:
    """Migrate old flat-key config files to the new project/global structure.

    Old format: {"default_port": "...", "log_level": "...", "device_dir": "..."}
    New format: {"projects": {...}, "global": {"log_level": "..."}}

    Runs in-place and returns the (possibly modified) dict.  Does not write
    to disk — callers decide whether to persist the result.
    """
    flat_project_keys = ("default_port", "device_dir")
    flat_global_keys = ("log_level",)

    for key in flat_project_keys:
        if key in data and "projects" not in data:
            # Migrate under current project root
            project_root = str(_detect_project_root())
            data.setdefault("projects", {}).setdefault(project_root, {})[key] = data.pop(key)
    for key in flat_global_keys:
        if key in data and "global" not in data:
            data.setdefault("global", {})[key] = data.pop(key)

    return data


def _read_global_config() -> dict:
    """Return the 'global' sub-dict from the permanent config file."""
    data = _read_json(_config_path())
    _migrate_flat_keys(data)
    return data.get("global", {})


def _read_project_config(project_root: Path | None = None) -> dict:
    """Return the project-scoped sub-dict from the permanent config file."""
    root = str(project_root or _detect_project_root())
    data = _read_json(_config_path())
    _migrate_flat_keys(data)
    return data.get("projects", {}).get(root, {})


def _write_project_config(updates: dict, project_root: Path | None = None) -> None:
    """Merge *updates* into the project-scoped section of the permanent config.

    Keys with a value of ``None`` are removed.
    """
    config_path = _config_path()
    root = str(project_root or _detect_project_root())
    data = _read_json(config_path)
    _migrate_flat_keys(data)
    projects = data.setdefault("projects", {})
    project = projects.setdefault(root, {})

    for key, value in updates.items():
        if value is None:
            project.pop(key, None)
        else:
            project[key] = value

    # Drop empty project entry
    if not project:
        projects.pop(root, None)
    if not projects:
        data.pop("projects", None)

    _write_json(config_path, data)


def _write_global_config(updates: dict) -> None:
    """Merge *updates* into the 'global' section of the permanent config.

    Keys with a value of ``None`` are removed.
    """
    config_path = _config_path()
    data = _read_json(config_path)
    _migrate_flat_keys(data)
    glbl = data.setdefault("global", {})

    for key, value in updates.items():
        if value is None:
            glbl.pop(key, None)
        else:
            glbl[key] = value

    if not glbl:
        data.pop("global", None)

    _write_json(config_path, data)


# ---------------------------------------------------------------------------
# Advanced host configuration
# ---------------------------------------------------------------------------


def _normalize_config_key(key: str) -> str:
    normalized = key.strip().replace("-", "_")
    if normalized in CONFIG_SETTINGS:
        return normalized
    display_key = key.strip().replace("_", "-")
    if display_key in _CONFIG_DISPLAY_TO_KEY:
        return _CONFIG_DISPLAY_TO_KEY[display_key]
    raise click.ClickException(
        "Unknown config setting. Choose from: " + ", ".join(setting["display"] for setting in CONFIG_SETTINGS.values())
    )


def _coerce_config_value(key: str, raw_value) -> int | float:
    setting = CONFIG_SETTINGS[key]
    value_type = setting["type"]
    try:
        if value_type is int:
            if isinstance(raw_value, str):
                stripped = raw_value.strip()
                if not stripped or "." in stripped:
                    raise ValueError()
            value = int(raw_value)
        else:
            value = float(raw_value)
    except (TypeError, ValueError) as ex:
        raise click.ClickException(f"{setting['display']} must be a {value_type.__name__}.") from ex

    if key == "query_retries":
        if value < 1:
            raise click.ClickException("query-retries must be at least 1.")
    elif key == "transfer_chunk_size":
        if value < 1 or value > MAX_TX_BUFFER_BYTES:
            raise click.ClickException(f"transfer-chunk-size must be between 1 and {MAX_TX_BUFFER_BYTES} bytes.")
    elif value <= 0:
        raise click.ClickException(f"{setting['display']} must be greater than 0.")

    return value


def _read_session_config_value(key: str) -> int | float | None:
    value = _read_json(_session_config_path()).get(key)
    if value is None:
        return None
    try:
        return _coerce_config_value(key, value)
    except click.ClickException:
        return None


def _read_project_config_value(key: str) -> int | float | None:
    value = _read_project_config().get(key)
    if value is None:
        return None
    try:
        return _coerce_config_value(key, value)
    except click.ClickException:
        return None


def get_config_value(key: str) -> int | float:
    import os

    key = _normalize_config_key(key)
    setting = CONFIG_SETTINGS[key]

    env_value = os.environ.get(setting["env"])  # type: ignore
    if env_value is not None:
        return _coerce_config_value(key, env_value)

    session_value = _read_session_config_value(key)
    if session_value is not None:
        return session_value

    project_value = _read_project_config_value(key)
    if project_value is not None:
        return project_value

    return setting["default"]  # type: ignore[return-value]


def _config_value_source(key: str) -> tuple[int | float, str]:
    import os

    key = _normalize_config_key(key)
    setting = CONFIG_SETTINGS[key]

    env_value = os.environ.get(setting["env"])  # type: ignore
    if env_value is not None:
        return _coerce_config_value(key, env_value), f"env:{setting['env']}"

    session_value = _read_session_config_value(key)
    if session_value is not None:
        return session_value, "session"

    project_value = _read_project_config_value(key)
    if project_value is not None:
        return project_value, "project"

    return setting["default"], "default"  # type: ignore[return-value]


def set_config_value(key: str, value: int | float | None, session: bool = False) -> None:
    key = _normalize_config_key(key)
    coerced = None if value is None else _coerce_config_value(key, value)

    if session:
        path = _session_config_path()
        try:
            data = _read_json(path)
            if coerced is None:
                data.pop(key, None)
            else:
                data[key] = coerced
            _write_json(path, data)
        except Exception as e:
            raise click.ClickException(f"Failed to save session config: {e}") from e
        return

    try:
        _write_project_config({key: coerced})
    except Exception as e:
        raise click.ClickException(f"Failed to save config: {e}") from e


# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------


def get_default_port() -> str | None:
    import os

    if "OTAMPY_PORT" in os.environ:  # type: ignore
        return os.environ["OTAMPY_PORT"]  # type: ignore

    # Session config
    session = _read_json(_session_config_path())
    value = session.get("default_port")
    if isinstance(value, str):
        return value

    # Project-scoped permanent config
    value = _read_project_config().get("default_port")
    if isinstance(value, str):
        return value

    # Global permanent fallback
    value = _read_global_config().get("default_port")
    return value if isinstance(value, str) else None


def set_default_port(port: str | None, session: bool = False) -> None:
    if session:
        path = _session_config_path()
        try:
            data = _read_json(path)
            if port is None:
                data.pop("default_port", None)
            else:
                data["default_port"] = port
            _write_json(path, data)
        except Exception as e:
            raise click.ClickException(f"Failed to save session port: {e}") from e
        return

    try:
        _write_project_config({"default_port": port})
    except Exception as e:
        raise click.ClickException(f"Failed to save default port: {e}") from e


# ---------------------------------------------------------------------------
# Log level (global only — not project-specific)
# ---------------------------------------------------------------------------


def get_default_log_level() -> str:
    import os

    if "OTAMPY_LOG_LEVEL" in os.environ:  # type: ignore
        return os.environ["OTAMPY_LOG_LEVEL"].upper()  # type: ignore

    # Session config
    value = _read_json(_session_config_path()).get("log_level")
    if isinstance(value, str) and value.upper() in LOG_LEVELS:
        return value.upper()

    # Global permanent config
    value = _read_global_config().get("log_level")
    if isinstance(value, str) and value.upper() in LOG_LEVELS:
        return value.upper()

    return "ERROR"


def set_default_log_level(level: str | None, session: bool = False) -> None:
    if session:
        path = _session_config_path()
        try:
            data = _read_json(path)
            if level is None:
                data.pop("log_level", None)
            else:
                data["log_level"] = level.upper()
            _write_json(path, data)
        except Exception as e:
            raise click.ClickException(f"Failed to save session log level: {e}") from e
        return

    try:
        _write_global_config({"log_level": level.upper() if level else None})
    except Exception as e:
        raise click.ClickException(f"Failed to save permanent log level: {e}") from e


# ---------------------------------------------------------------------------
# Device directory (project-scoped; stored relative to project root)
#
# The device directory MUST always reside inside the project root.  Paths
# are displayed and accepted using a project-root-relative notation where
# "/" means the project root (e.g. "/device" means <project-root>/device).
# ---------------------------------------------------------------------------


def _to_display_path(abs_path: str) -> str:
    """Convert an absolute path to a project-root-relative display string.

    Returns "/<relative>" if the path is inside the project root, or the
    original absolute path as a fallback (e.g. for env-var overrides that
    predate this constraint).
    """
    try:
        project_root = _detect_project_root()
        relative = Path(abs_path).relative_to(project_root)
        return "/" + str(relative)
    except ValueError:
        return abs_path


def _resolve_project_path_input(raw: str) -> Path:
    """Resolve a user-supplied project-relative input to an absolute Path.

    Resolution rules:
      - Starts with "./" or "../"  → relative to CWD, then validated.
      - Starts with "/"            → project-root-relative.
      - Bare name / bare path      → project-root-relative.

    Raises click.ClickException if the resolved path escapes the project root.
    """
    import os

    project_root = _detect_project_root()

    if raw.startswith("./") or raw.startswith("../"):
        resolved = Path(os.getcwd()) / raw
    else:
        # Strip any leading "/" so Path doesn't treat it as filesystem root
        resolved = project_root / raw.lstrip("/")

    resolved = resolved.resolve()

    try:
        resolved.relative_to(project_root)
    except ValueError as ex:
        raise click.ClickException(f"Path must be inside the project root ({project_root}): {resolved}") from ex

    return resolved


def get_default_device_dir() -> str | None:
    import os

    if "OTAMPY_DEVICE_DIR" in os.environ:  # type: ignore
        return os.environ["OTAMPY_DEVICE_DIR"]  # type: ignore

    # Session config (stored as absolute)
    value = _read_json(_session_config_path()).get("device_dir")
    if isinstance(value, str):
        return value

    # Project-scoped permanent config (stored relative to project root)
    relative = _read_project_config().get("device_dir")
    if isinstance(relative, str):
        project_root = _detect_project_root()
        resolved = (project_root / relative).resolve()
        return str(resolved)

    return None


def set_default_device_dir(device_dir: str | None, session: bool = False) -> None:
    if session:
        path = _session_config_path()
        try:
            data = _read_json(path)
            if device_dir is None:
                data.pop("device_dir", None)
            else:
                data["device_dir"] = device_dir
            _write_json(path, data)
        except Exception as e:
            raise click.ClickException(f"Failed to save session device dir: {e}") from e
        return

    try:
        if device_dir is None:
            _write_project_config({"device_dir": None})
        else:
            # Store relative to project root for portability.
            # The device directory must always reside inside the project root.
            project_root = _detect_project_root()
            abs_dir = Path(device_dir).resolve()
            try:
                relative = str(abs_dir.relative_to(project_root))
            except ValueError as ex:
                raise click.ClickException(
                    f"Device directory must be inside the project root ({project_root}): {abs_dir}"
                ) from ex
            _write_project_config({"device_dir": relative})
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Failed to save permanent device dir: {e}") from e


def _ensure_device_dir_exists(path: Path) -> bool:
    """Create a missing device directory when the user confirms."""
    if path.is_dir():
        return True
    if path.exists():
        raise click.ClickException(f"Device directory is not a directory: {path}")

    if not click.confirm(f"Directory does not exist: {path}. Create it?", default=True):
        _console().print("Cancelled.")
        return False

    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise click.ClickException(f"Failed to create device directory: {e}") from e
    return True


def _offer_to_save_log_level(level: str) -> None:
    choice = click.prompt(
        f"Keep {level} as the log level? (p=permanent, s=session, c=current command only)",
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
@click.version_option(
    None,
    "-v",
    "--version",
    package_name="otampy",
    prog_name="otampy",
)
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
@click.option(
    "--timing",
    is_flag=True,
    help="Temporarily print elapsed-time metrics for the command.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    port: str | None,
    baud: int,
    log_level: str,
    timing: bool,
) -> None:
    """OTAmpy CLI - Over the air (OTA) file management for MicroPython devices."""
    log_level = log_level.upper()
    logging.getLogger().setLevel(getattr(logging, log_level))

    ctx.ensure_object(dict)
    ctx.obj["port"] = port
    ctx.obj["baud"] = baud
    ctx.obj["log_level"] = log_level
    ctx.obj["timing"] = timing
    if timing:
        ctx.obj["command_started_at"] = MONOTONIC()


@cli.result_callback()
@click.pass_context
def report_command_timing(ctx: click.Context, _result: object, **_params: object) -> None:
    """Temporarily report successful command wall-clock durations."""
    started_at = ctx.obj.get("command_started_at")
    if started_at is None or ctx.invoked_subcommand in (None, "upd"):
        return
    elapsed = MONOTONIC() - started_at
    _console().print(f"[dim]Timing: {ctx.invoked_subcommand} completed in {elapsed:.2f} s.[/dim]")


def _friendly_error(err_msg: str, command: bytes) -> str:
    err_msg_lower = err_msg.lower()
    target = ""
    is_directory_err = "eisdir" in err_msg_lower or "errno 21" in err_msg_lower or err_msg == "21"
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

    if "enoent" in err_msg_lower or "errno 2" in err_msg_lower or err_msg == "2":
        return f"No such file or directory{target}"
    if "eacces" in err_msg_lower or "errno 13" in err_msg_lower or err_msg == "13":
        return f"Permission denied{target}"
    if "enospc" in err_msg_lower or "errno 28" in err_msg_lower or err_msg == "28":
        return "No space left on device"
    if "eexist" in err_msg_lower or "errno 17" in err_msg_lower or err_msg == "17":
        return f"File or directory already exists{target}"
    if "eisdir" in err_msg_lower or "errno 21" in err_msg_lower or err_msg == "21":
        return f"Is a directory{target}"
    if "enotdir" in err_msg_lower or "errno 20" in err_msg_lower or err_msg == "20":
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
        raise click.ClickException("Error: Missing serial port. Specify with --port or -p option.")

    import serial
    from urst import Urst

    serial_timeout = float(get_config_value("serial_timeout_seconds"))

    # If transport provided, use it directly (single attempt)
    if transport is not None:
        if not transport.send(command):
            raise click.ClickException("Failed to send command over transport.")

        response = transport.read()
        if not response:
            raise click.ClickException(f"Timeout waiting for response to command: {command.decode()}")

        # Check for device error response
        if response.startswith(b"ERROR:"):
            err_msg = response[6:].decode("utf-8", errors="replace")
            raise DeviceError(err_msg, command)

        if not response.startswith(expected_prefix):
            resp_str = response.decode("utf-8", errors="replace") if isinstance(response, bytes) else str(response)
            raise click.ClickException(
                f"Unexpected response to command '{command.decode()}'. "
                f"Expected prefix '{expected_prefix.decode()}', got '{resp_str}'"
            )

        # Return payload after prefix and potential colon separator
        prefix_len = len(expected_prefix)
        if len(response) > prefix_len and response[prefix_len : prefix_len + 1] == b":":
            res = response[prefix_len + 1 :]
        else:
            res = response[prefix_len:]

        return res, None

    # Create new transport with retry logic
    last_err = None
    query_retries = int(get_config_value("query_retries"))
    retry_backoff = float(get_config_value("query_retry_backoff_seconds"))

    for attempt in range(query_retries):
        ser = None
        try:
            ser = serial.Serial(port, baudrate=baud, timeout=serial_timeout)
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
                raise click.ClickException("Failed to send command over transport.")

            response = new_transport.read()
            if not response:
                raise click.ClickException(f"Timeout waiting for response to command: {command.decode()}")

            # Check for device error response
            if response.startswith(b"ERROR:"):
                err_msg = response[6:].decode("utf-8", errors="replace")
                ser.close()
                raise DeviceError(err_msg, command)

            if not response.startswith(expected_prefix):
                resp_str = response.decode("utf-8", errors="replace") if isinstance(response, bytes) else str(response)
                ser.close()
                raise click.ClickException(
                    f"Unexpected response to command '{command.decode()}'. "
                    f"Expected prefix '{expected_prefix.decode()}', got '{resp_str}'"
                )

            # Return payload after prefix and potential colon separator
            prefix_len = len(expected_prefix)
            if len(response) > prefix_len and response[prefix_len : prefix_len + 1] == b":":
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
            if attempt < query_retries - 1:
                time.sleep(retry_backoff * (2**attempt))

    raise click.ClickException(str(last_err))


def _handle_device_error(device_error: DeviceError) -> None:
    """Display a friendly error message and exit."""
    friendly = _friendly_error(device_error.error_msg, device_error.command)
    _console().print(f"[red]Error: {friendly}[/red]")
    raise SystemExit(1)


def _send_command(ctx: click.Context, command: bytes, expected_response: bytes) -> None:
    """Send command and verify response (backward compatible)."""
    _query(ctx, command, expected_response)


def _stage_rtc_update(ctx: click.Context) -> None:
    """Stage a one-shot RTC helper for the next normal device boot."""
    now = datetime.now()
    command = (
        f"RTC_STAGE:{now.year}:{now.month}:{now.day}:{now.weekday()}:"
        f"{now.hour}:{now.minute}:{now.second}:{now.microsecond}"
    ).encode()
    _console().print("[yellow]Staging device RTC update...[/yellow]")
    _send_command(ctx, command, b"RTC_STAGE_OK")


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


@cli.command(name="rtc")
@click.pass_context
def rtc(ctx: click.Context) -> None:
    """Display the device RTC timestamp without resetting it."""
    try:
        rtc_tuple, _ = _query(ctx, b"RTC", b"RTC_OK")
    except DeviceError as e:
        _handle_device_error(e)
        return
    try:
        year, month, day, _weekday, hour, minute, second, _subsecond = (
            int(value.strip()) for value in rtc_tuple.strip(b"()").split(b",")
        )
    except ValueError as e:
        raise click.ClickException("Invalid RTC response from device.") from e
    _console().print(f"Device RTC: {year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}")


@cli.command(name="rb")
@click.option(
    "--set-time",
    is_flag=True,
    help="Set the device RTC from the host during reboot.",
)
@click.pass_context
def reboot(ctx: click.Context, set_time: bool) -> None:
    """Hard reboots the device."""
    if not click.confirm(
        click.style("Are you sure you want to hard reboot the device?", fg="red"),
        default=False,
    ):
        _console().print("[yellow]Aborted.[/yellow]")
        return
    _console().print("[yellow]Hard rebooting the device...[/yellow]")
    try:
        if set_time:
            _stage_rtc_update(ctx)
        _send_command(ctx, b"RB", b"RB_OK")
    except DeviceError as e:
        _handle_device_error(e)


@cli.command(name="sr")
@click.option(
    "--set-time",
    is_flag=True,
    help="Set the device RTC from the host during reboot.",
)
@click.pass_context
def soft_reset(ctx: click.Context, set_time: bool) -> None:
    """Soft resets the device."""
    if not click.confirm(
        click.style("Are you sure you want to soft reset the device?", fg="red"),
        default=False,
    ):
        _console().print("[yellow]Aborted.[/yellow]")
        return
    _console().print("[yellow]Soft resetting the device...[/yellow]")
    try:
        if set_time:
            _stage_rtc_update(ctx)
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
        _console().print("[green]Listing content of current directory...[/green]")
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
    _console().print(f"[green]Showing content of specified file: {file}[/green]")
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


def _remote_directory_entries(ctx: click.Context, path: str) -> list[tuple[str, bool, str]]:
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
    segments = [segment for segment in pattern.split("/") if segment not in ("", ".")]
    if not segments:
        return []

    matches = []
    start = "/" if pattern.startswith("/") else ""

    def walk(parent: str, index: int) -> None:
        segment = segments[index]
        final_segment = index == len(segments) - 1

        if segment == "**":
            if final_segment:
                for path, is_dir, _name in _remote_directory_entries(ctx, parent):
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


def _expand_remote_targets(ctx: click.Context, patterns: tuple[str, ...]) -> list[str]:
    targets = []
    unmatched = []
    for pattern in patterns:
        pattern = _canonical_remote_argument(pattern)
        if any(char in pattern for char in "*?["):
            try:
                matches = _expand_remote_pattern(ctx, pattern)
            except DeviceError as e:
                raise click.ClickException(_friendly_error(e.error_msg, e.command)) from e
            if not matches:
                unmatched.append(pattern)
            targets.extend(matches)
        else:
            targets.append(pattern.rstrip("/") or "/")

    if unmatched:
        raise click.ClickException("No remote paths matched: " + ", ".join(unmatched))
    return list(dict.fromkeys(targets))


_PROTECTED_RECOVERY_PATHS = (
    "boot.py",
    "main.py",
    "configota.py",
    "lib/otampy",
    "lib/urst",
)


def _normalize_remote_path(path: str) -> str:
    from posixpath import normpath  # type: ignore

    path = _canonical_remote_argument(path)
    normalized = normpath("/" + path.replace("\\", "/").lstrip("/"))
    return normalized.lstrip("/")


def _is_protected_recovery_path(path: str) -> bool:
    normalized = _normalize_remote_path(path)
    if not normalized:
        return True
    return any(
        normalized == protected or normalized.startswith(protected + "/") or protected.startswith(normalized + "/")
        for protected in _PROTECTED_RECOVERY_PATHS
    )


def _validate_removal_targets(targets: list[str]) -> None:
    protected = [target for target in targets if _is_protected_recovery_path(target)]
    if protected:
        raise click.ClickException(
            "Refusing to remove protected recovery path(s): "
            + ", ".join(protected)
            + ". Replace them with 'otampy cp' or 'otampy upd'."
        )


def _validate_remote_only_arguments(files: tuple[str, ...], literal_remote_paths: bool) -> None:
    if literal_remote_paths:
        return
    local_matches = [file for file in files if not file.startswith(":") and Path(file).exists()]
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
        raise click.ClickException("Error: Missing serial port. Specify with --port or -p option.")

    ser = None
    try:
        # Establish persistent connection
        serial_timeout = float(get_config_value("serial_timeout_seconds"))
        ser = serial.Serial(port, baudrate=baud, timeout=serial_timeout)
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
                    _console().print(f"  Removing remote path: {item_path}")
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
    target_summary = f"'{targets[0]}'" if len(targets) == 1 else f"these {len(targets)} paths: {', '.join(targets)}"
    if not click.confirm(
        click.style(
            f"Are you sure you want to remove {target_summary} from the remote device?",
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
                    "Remote directory is not empty. Remove all contents recursively?",
                    default=False,
                ):
                    _console().print("[yellow]Recursively removing directory on device...[/yellow]")
                    _recursive_rm_with_connection(ctx, file)
                    _console().print("[green]Directory removed successfully.[/green]")
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
        raise click.ClickException(f"Invalid memory response from device: {payload}") from e

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
    _console().print(f"  Free:      {ram_free_pct:.1f}% ({format_size(ram_free):<7} / {format_size(ram_total)})")
    _console().print(f"  Allocated: {ram_alloc_pct:.1f}% ({format_size(ram_alloc):<7})")
    _console().print()
    _console().print("[bold]Flash (Storage):[/bold]")
    _console().print(f"  Free:      {flash_free_pct:.1f}% ({format_size(flash_free):<7} / {format_size(flash_total)})")
    _console().print(f"  Used:      {flash_used_pct:.1f}% ({format_size(flash_used):<7})")


def _split_update_arg(arg: str) -> tuple[str, str | None]:
    separator = arg.find(":")
    if separator == 1 and arg[0].isalpha() and len(arg) > 2 and arg[2] in ("\\", "/"):
        separator = arg.find(":", 3)
    if separator < 0:
        return arg, None
    return arg[:separator], arg[separator + 1 :]


def _update_target_path(source: Path, target: str | None, multiple_matches: bool) -> str:
    if target is not None:
        target_is_dir = target.endswith(("/", "\\"))
        if multiple_matches and not target_is_dir:
            raise click.ClickException(
                f"A wildcard matching multiple files requires a destination directory ending in '/': {target}"
            )
        if target_is_dir:
            return target.rstrip("/\\") + "/" + source.name
        return target

    try:
        return str(source.relative_to(_detect_project_root()))
    except ValueError:
        return str(source)


def _get_files_to_send(
    args: tuple[str, ...], *, python_only: bool = True, all_files: bool = False
) -> list[tuple[str, Path]]:
    from glob import glob, has_magic

    res = []
    unmatched = []

    if args:
        for arg in args:
            src_str, target_str = _split_update_arg(arg)
            source_pattern = str(_resolve_project_path_input(src_str))
            if has_magic(source_pattern):
                sources = [Path(match) for match in sorted(glob(source_pattern, recursive=True))]
            else:
                source = Path(source_pattern)
                sources = [source] if source.exists() else []

            matched_files = []
            for source in sources:
                if source.is_file():
                    matched_files.append((source, None))
                elif source.is_dir():
                    pattern = "*.py" if python_only else "*"
                    matched_files.extend(
                        (file, file.relative_to(source)) for file in sorted(source.rglob(pattern)) if file.is_file()
                    )

            if not matched_files:
                unmatched.append(src_str)
                continue

            multiple_matches = len(matched_files) > 1
            for source, relative in matched_files:
                if relative is None:
                    target_path = _update_target_path(source, target_str, multiple_matches)
                elif target_str is not None:
                    target_path = target_str.rstrip("/\\") + "/" + str(relative)
                else:
                    try:
                        target_path = str(source.relative_to(_detect_project_root()))
                    except ValueError:
                        target_path = str(source)
                res.append((target_path.replace("\\", "/"), source))

        if unmatched:
            raise click.ClickException("No local files matched: " + ", ".join(unmatched))
    else:
        project_root = _detect_project_root()
        source_root = Path(get_default_device_dir() or project_root)
        if all_files:
            res.extend(
                (str(file.relative_to(source_root)).replace("\\", "/"), file)
                for file in sorted(source_root.rglob("*"))
                if file.is_file()
            )
        else:
            for name in ("boot.py", "main.py", "configota.py"):
                file = source_root / name
                if file.is_file():
                    res.append((name, file))
            p_lib = source_root / "lib"
            if p_lib.is_dir():
                for f in p_lib.rglob("*.py"):
                    rel_path = str(f.relative_to(source_root))
                    res.append((rel_path.replace("\\", "/"), f))

    # Validate for conflicts
    target_paths = [t for t, _ in res]
    for i, t1 in enumerate(target_paths):
        for j, t2 in enumerate(target_paths):
            if i != j:
                if t1 == t2:
                    raise click.ClickException(f"Conflict: Multiple files mapped to the same destination '{t1}'")
                if t2.startswith(t1 + "/"):
                    raise click.ClickException(
                        f"Conflict: Destination '{t1}' is mapped as a file, but also used as a directory for '{t2}'"
                    )

    return res


def _copy_requires_reboot(target: str) -> bool:
    normalized = target.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    return normalized in ("boot.py", "main.py")


def _print_minification_report(sources: list[tuple[str, Path]], staged: list[tuple[str, Path]]) -> None:
    """Report each temporary Python artifact using its real source and target."""
    for (target, source), (_, artifact) in zip(sources, staged, strict=True):
        if source.suffix == ".py":
            _console().print(
                f"Minified {source} for {target}: {source.stat().st_size} -> {artifact.stat().st_size} bytes"
            )


@cli.command(name="cp")
@click.option(
    "--minify",
    is_flag=True,
    help="Remove Python comments and redundant blank lines before copying.",
)
@click.argument("args", nargs=-1, required=True)
@click.pass_context
def copy_files(ctx: click.Context, args: tuple[str, ...], minify: bool) -> None:
    """Copy files or directories without rebooting the device."""
    files_to_send = _get_files_to_send(args, python_only=False)

    port = ctx.obj.get("port")
    baud = ctx.obj.get("baud")
    if not port:
        raise click.ClickException("Error: Missing serial port. Specify with --port or -p option.")

    import binascii
    import hashlib

    import serial
    from urst import Urst

    staging = source_minify.staged_minified_files(files_to_send) if minify else nullcontext(files_to_send)  # type: ignore
    with staging as files_to_copy:
        if minify:
            _print_minification_report(files_to_send, files_to_copy)  # type: ignore
        serial_timeout = float(get_config_value("serial_timeout_seconds"))
        ser = serial.Serial(port, baudrate=baud, timeout=serial_timeout)
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
                for target_path, local_path in files_to_copy:  # type: ignore
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
                        raise click.ClickException(f"Failed to read local file {local_path}: {e}") from e

                    digest = hasher.hexdigest()
                    _console().print(f"Copying {local_path} to {target_path} ({size} bytes)...")
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
                                b"CP_CHUNK:" + str(sequence).encode() + b":" + encoded,
                                b"CP_ACK",
                                transport=transport,
                            )
                            if response != str(sequence).encode():
                                raise click.ClickException(
                                    f"Unexpected copy acknowledgement for {target_path}: {response!r}"
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
                        reboot_targets.append("/" + target_path.replace("\\", "/").lstrip("/"))
                    _console().print(f"[green]Copied {target_path} successfully.[/green]")
            except DeviceError as e:
                raise click.ClickException(_friendly_error(e.error_msg, e.command)) from e
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
                        f"[yellow]Reboot required: {targets} will not take effect until the device restarts.[/yellow]"
                    )
        finally:
            ser.close()


@cli.command(name="upd")
@click.option(
    "--minify",
    is_flag=True,
    help="Remove Python comments and redundant blank lines before updating.",
)
@click.option(
    "--all-files",
    is_flag=True,
    help="Upload every file in the device directory after confirmation.",
)
@click.option(
    "--set-time",
    is_flag=True,
    help="Set the device RTC from the host during the final reboot.",
)
@click.argument("args", nargs=-1)
@click.pass_context
def update(
    ctx: click.Context,
    args: tuple[str, ...],
    minify: bool,
    all_files: bool,
    set_time: bool,
) -> None:
    """Reboot & update files or directories on the device."""
    if all_files and args:
        raise click.UsageError("--all-files cannot be combined with explicit update sources.")

    # 0. Scan and collect files to send locally before touching device
    files_to_send = _get_files_to_send(args, all_files=all_files)
    if not files_to_send:
        _console().print("[yellow]No files found to transfer.[/yellow]")
        return

    if all_files:
        _console().print("[yellow]The following files will be uploaded:[/yellow]")
        for target_path, _ in files_to_send:
            _console().print(f"  {target_path}")
        if not click.confirm("Continue with the update?", default=False):
            _console().print("Cancelled.")
            return

    staging = source_minify.staged_minified_files(files_to_send) if minify else nullcontext(files_to_send)  # type: ignore
    with staging as files_to_update:
        if minify:
            _print_minification_report(files_to_send, files_to_update)  # type: ignore
        _update_files(ctx, files_to_update, set_time)  # type: ignore


def _update_files(ctx: click.Context, files_to_send: list[tuple[str, Path]], set_time: bool) -> None:
    """Transfer an already-resolved (and optionally staged) update file set."""
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
            raise click.ClickException(f"Failed to read local file {local_path}: {e}") from e

    if set_time:
        content = deploy.rtc_helper_content().encode()
        size = len(content)
        manifest.append(
            (
                deploy.RTC_HELPER_FILE,
                Path(deploy.RTC_HELPER_FILE),
                size,
                hashlib.sha256(content).hexdigest(),
                content,
            )
        )
        total_bytes += size

    _console().print("[yellow]Initiating update handshake...[/yellow]")

    # 1. Send UPDATE_REQUEST to device runtime (main.py)
    _send_command(ctx, b"UPDATE_REQUEST", b"REBOOTING")
    _console().print("[yellow]Device acknowledged update request. Rebooting...[/yellow]")

    # 2. Wait for device to boot up and broadcast READY
    port = ctx.obj.get("port")
    baud = ctx.obj.get("baud")
    if not port:
        raise click.ClickException("Error: Missing serial port. Specify with --port or -p option.")

    import binascii
    import time

    import serial
    from urst import Urst

    time.sleep(0.5)

    start_time = time.time()
    timeout = float(get_config_value("update_ready_timeout_seconds"))
    transport = None
    ser = None

    while time.time() - start_time < timeout:
        try:
            if ser is None:
                serial_timeout = float(get_config_value("serial_timeout_seconds"))
                ser = serial.Serial(port, baudrate=baud, timeout=serial_timeout)
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
        raise click.ClickException("Timeout waiting for device READY broadcast.")

    _console().print("[green]Device is READY. Handshake complete.[/green]")

    # 4. Start update session: UPDATE_START
    _console().print(f"Sending manifest ({len(manifest)} files, {total_bytes} bytes)...")
    commit_sent = False
    transfer_started_at = MONOTONIC() if ctx.obj["timing"] else None
    try:
        transport.send(f"UPDATE_START:{len(manifest)}:{total_bytes}".encode())
        resp = transport.read()
        if resp != b"SPACE_OK":
            raise click.ClickException(
                f"Device rejected manifest. Response: {resp.decode('utf-8', errors='replace') if resp else 'None'}"
            )

        # 5. Send files sequentially
        chunk_size = int(get_config_value("transfer_chunk_size"))
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
                b64_chunk = binascii.b2a_base64(chunk_data).strip().decode("utf-8")

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
        commit_sent = True
        transport.send(b"UPDATE_COMMIT")
        resp = transport.read()
        if resp != b"COMMIT_OK":
            raise click.ClickException(
                f"Device commit failed: {resp.decode('utf-8', errors='replace') if resp else 'None'}"
            )

        _console().print("[green]Update completed successfully! Device is rebooting.[/green]")
        if transfer_started_at is not None:
            transfer_elapsed = MONOTONIC() - transfer_started_at
            transfer_rate = total_bytes / transfer_elapsed if transfer_elapsed else 0
            _console().print(
                f"[dim]Timing: transferred {len(manifest)} files ({total_bytes} bytes) in "
                f"{transfer_elapsed:.2f} s ({transfer_rate:.0f} bytes/s).[/dim]"
            )
    except BaseException:
        if not commit_sent:
            try:
                transport.send(b"UPDATE_ABORT")
                if transport.read() != b"UPDATE_ABORTED":
                    _console().print(
                        "[yellow]Device did not acknowledge update abort; waiting for its inactivity timeout.[/yellow]"
                    )
            except Exception:
                _console().print(
                    "[yellow]Could not send update abort; waiting for the device inactivity timeout.[/yellow]"
                )
        raise
    finally:
        ser.close()


@cli.command(name="ports")
@click.option("--set", "set_port", help="Set the default port permanently.")
@click.option("--clear", is_flag=True, help="Clear the default port settings.")
@click.option("--show", is_flag=True, help="Show the current default port.")
@click.pass_context
def ports_cmd(ctx: click.Context, set_port: str | None, clear: bool, show: bool) -> None:
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
        _console().print(f"[green]Permanent default port set to: {set_port}[/green]")
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
            _console().print(f"  [bold green]* {idx}: {port_summary}[/bold green]")
        else:
            _console().print(f"    [bold]{idx}[/bold]: [cyan]{port_summary}[/cyan]")

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
        _console().print(f"[green]Permanent default port set to: {selected_port}[/green]")
    elif choice == "s":
        set_default_port(selected_port, session=True)
        _console().print(f"[green]Session default port set to: {selected_port}[/green]")
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
        _console().print(f"[green]Permanent log level set to: {set_level.upper()}[/green]")
        return

    # Interactive mode — show current and prompt to change
    current = get_default_log_level()
    _console().print(f"Current log level: [bold]{current}[/bold]")
    _console().print(f"Available levels: {', '.join(LOG_LEVELS)}")

    selection = (
        click.prompt(
            "\nEnter a log level to set as default (or press Enter to cancel)",
            default="",
            show_default=False,
        )
        .strip()
        .upper()
    )

    if not selection:
        _console().print("Cancelled.")
        return

    if selection not in LOG_LEVELS:
        raise click.ClickException(f"Invalid log level '{selection}'. Choose from: {', '.join(LOG_LEVELS)}")

    choice = (
        click.prompt(
            f"Set {selection} as default? (p=permanent, s=session, c=cancel) [p/s/c]",
            default="p",
        )
        .strip()
        .lower()
    )

    if choice == "p":
        set_default_log_level(selection)
        set_default_log_level(None, session=True)
        _console().print(f"[green]Permanent log level set to: {selection}[/green]")
    elif choice == "s":
        set_default_log_level(selection, session=True)
        _console().print(f"[green]Session log level set to: {selection}[/green]")
    else:
        _console().print("Cancelled.")


@cli.command(name="device-dir")
@click.option("--show", is_flag=True, help="Show the current default device directory.")
@click.option(
    "--set",
    "set_dir",
    type=click.Path(file_okay=False, dir_okay=True),
    help="Set the default device directory permanently.",
)
@click.option("--clear", is_flag=True, help="Clear the saved device directory.")
def device_dir_cmd(show: bool, set_dir: str | None, clear: bool) -> None:
    """Show or manage the saved project directory for deploy.

    The project directory should contain boot.py, main.py, and configota.py as
    created by 'otampy init'. The OTAmpy library (lib/) is always sourced
    from the installed package — you do not need lib/ in your project.

    The device directory must always reside inside the project root.  Paths
    are displayed and accepted in project-root-relative notation, where "/"
    means the project root (e.g. "/device" → <project-root>/device).  Bare
    paths without a leading slash are also treated as project-root-relative.
    Use "./" or "../" to anchor a path to the current working directory
    instead (it is still validated against the project root).

    With no options, shows the current value and prompts to change it.
    Override for a single deploy with 'otampy deploy --device-dir PATH'.
    """
    if show:
        d = get_default_device_dir()
        if d:
            _console().print(f"Current device directory: [green]{_to_display_path(d)}[/green]")
        else:
            _console().print("No default device directory set (using auto-detected path).")
        return

    if clear:
        set_default_device_dir(None)
        set_default_device_dir(None, session=True)
        _console().print("[green]Saved device directory cleared.[/green]")
        return

    if set_dir:
        resolved = _resolve_project_path_input(set_dir)
        if not _ensure_device_dir_exists(resolved):
            return
        abs_str = str(resolved)
        set_default_device_dir(abs_str)
        set_default_device_dir(None, session=True)
        _console().print(f"[green]Permanent device directory set to: {_to_display_path(abs_str)}[/green]")
        return

    # Interactive mode
    current = get_default_device_dir()
    if current:
        _console().print(f"Current device directory: [bold]{_to_display_path(current)}[/bold]")
    else:
        _console().print("No default device directory set (using auto-detected path).")

    new_dir = click.prompt(
        "\nEnter path to device directory (or press Enter to cancel)",
        default="",
        show_default=False,
    ).strip()

    if not new_dir:
        _console().print("Cancelled.")
        return

    resolved = _resolve_project_path_input(new_dir)
    if not _ensure_device_dir_exists(resolved):
        return

    display = _to_display_path(str(resolved))
    choice = (
        click.prompt(
            f"Set {display} as default? (p=permanent, s=session, c=cancel) [p/s/c]",
            default="p",
        )
        .strip()
        .lower()
    )

    if choice == "p":
        set_default_device_dir(str(resolved))
        set_default_device_dir(None, session=True)
        _console().print(f"[green]Permanent device directory set to: {display}[/green]")
    elif choice == "s":
        set_default_device_dir(str(resolved), session=True)
        _console().print(f"[green]Session device directory set to: {display}[/green]")
    else:
        _console().print("Cancelled.")


@cli.command(name="config")
@click.option(
    "--show",
    is_flag=True,
    help="Show advanced host configuration and effective values.",
)
@click.option(
    "--set",
    "set_item",
    nargs=2,
    metavar="KEY VALUE",
    help="Set an advanced host configuration value permanently.",
)
@click.option(
    "--clear",
    "clear_key",
    metavar="KEY",
    help="Clear a saved advanced host configuration value.",
)
@click.option(
    "--session",
    is_flag=True,
    help="Apply --set or --clear to the current shell session only.",
)
def config_cmd(
    show: bool,
    set_item: tuple[str, str] | None,
    clear_key: str | None,
    session: bool,
) -> None:
    """Show or manage advanced host configuration.

    Values are project-scoped when saved permanently. Session values shadow
    permanent config for commands in the current shell. Environment variables
    shown in --show output shadow both saved sources.
    """
    if sum(bool(value) for value in (show, set_item, clear_key)) > 1:
        raise click.UsageError("Choose only one of --show, --set, or --clear.")

    if set_item is not None:
        key, raw_value = set_item
        normalized = _normalize_config_key(key)
        value = _coerce_config_value(normalized, raw_value)
        set_config_value(normalized, value, session=session)
        if not session:
            set_config_value(normalized, None, session=True)
        scope = "Session" if session else "Permanent"
        display = CONFIG_SETTINGS[normalized]["display"]
        _console().print(f"[green]{scope} config set: {display}={value}[/green]")
        return

    if clear_key is not None:
        normalized = _normalize_config_key(clear_key)
        set_config_value(normalized, None, session=session)
        if not session:
            set_config_value(normalized, None, session=True)
        scope = "Session" if session else "Saved"
        display = CONFIG_SETTINGS[normalized]["display"]
        _console().print(f"[green]{scope} config cleared: {display}[/green]")
        return

    _console().print("[bold]Advanced host configuration:[/bold]")
    for key, setting in CONFIG_SETTINGS.items():
        value, source = _config_value_source(key)
        _console().print(f"  {setting['display']}: [green]{value}[/green] ({source}; env {setting['env']})")


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
    help="Skip installing all MicroPython dependencies with mip.",
)
@click.option(
    "--with-logger",
    is_flag=True,
    help="Install log-to-file for development logging.",
)
@click.option(
    "--urst-branch",
    metavar="BRANCH",
    help="Install URST-mpy from this Git branch instead of its default branch.",
)
@click.option(
    "--bytecode",
    "--mpy",
    is_flag=True,
    help="Deploy target-matched .mpy libraries.",
)
@click.option(
    "--minify",
    is_flag=True,
    help="Remove Python comments and redundant blank lines before deploying.",
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
    "--set-time",
    is_flag=True,
    help="Set the device RTC from the host during the final boot.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print mpremote commands without running them.",
)
@click.option(
    "--device-dir",
    default=get_default_device_dir,
    help=(
        "Path to the project directory containing boot.py, main.py, and configota.py "
        "(created by 'otampy init'). "
        "Paths are relative to the project root; '/' means the project root. "
        "The OTAmpy library (lib/) is always sourced from the installed package. "
        "Use 'otampy device-dir' to save this as the default."
    ),
)
@click.pass_context
def deploy_cmd(
    ctx: click.Context,
    port: str | None,
    mpremote: str,
    no_mip: bool,
    with_logger: bool,
    urst_branch: str | None,
    bytecode: bool,
    minify: bool,
    mpy_cross: str,
    no_reset: bool,
    set_time: bool,
    dry_run: bool,
    device_dir: str | None,
) -> None:
    """Erase and deploy OTAmpy, examples, and device dependencies."""
    args = deploy.DeployArgs(
        port=port,  # type: ignore
        mpremote=mpremote,  # type: ignore
        no_mip=no_mip,  # type: ignore
        with_logger=with_logger,  # type: ignore
        urst_branch=urst_branch,  # type: ignore
        bytecode=bytecode,  # type: ignore
        minify=minify,  # type: ignore
        mpy_cross=mpy_cross,  # type: ignore
        no_reset=no_reset,  # type: ignore
        set_time=set_time,  # type: ignore
        dry_run=dry_run,  # type: ignore
        device_dir=(  # type: ignore
            Path(device_dir)
            if device_dir and ctx.get_parameter_source("device_dir") is click.core.ParameterSource.DEFAULT
            else _resolve_project_path_input(device_dir)
            if device_dir
            else None
        ),  # type: ignore
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
    except deploy.DependencyPreflightError as error:
        raise click.ClickException(str(error)) from error
    except deploy.DeployOptionError as error:
        raise click.ClickException(str(error)) from error


@cli.command(name="init")
@click.argument(
    "path",
    type=str,
    required=False,
    default=None,
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Overwrite existing files without prompting.",
)
@click.pass_context
def init(ctx: click.Context, path: str | None, force: bool) -> None:
    """Initialize a new project with example configuration files.

    Creates boot.py, main.py, and configota.py in the specified directory.
    If no directory is given, prompts for one (remembering the last used path).
    """
    console = _console()

    if path is None:
        saved = get_default_device_dir()
        default_display = _to_display_path(saved) if saved else str(Path.cwd())
        raw = click.prompt(
            "Project directory",
            default=default_display,
        ).strip()
        path = _resolve_project_path_input(raw)  # type: ignore
    else:
        path = _resolve_project_path_input(path)  # type: ignore
    path.mkdir(parents=True, exist_ok=True)  # type: ignore

    # Example files to copy
    examples = ["boot.py", "main.py", "configota.example.py"]

    try:
        # Get the examples package resource
        pkg_files = importlib.resources.files("otampy").joinpath(  # type: ignore
            "device", "examples"
        )

        for example_file in examples:
            src = pkg_files.joinpath(example_file)
            dst = path / "configota.py" if example_file == "configota.example.py" else path / example_file  # type: ignore

            # Check if file exists
            if (
                dst.exists()
                and not force
                and not click.confirm(f"{dst.name} already exists. Overwrite?", default=False)
            ):
                console.print(f"[yellow]Skipped[/yellow] {dst.name}")
                continue

            # Read and write the file (cross-OS compatible)
            content = src.read_text()
            dst.write_text(content)
            console.print(f"[green]✓[/green] Created {dst.name}")

        console.print(f"\n[green]✓[/green] Project initialized at {path}")

        # Remember this directory for the current shell session so
        # 'otampy deploy' works immediately without --device-dir.
        # Not saved permanently — use 'otampy device-dir --set .' for that.
        set_default_device_dir(str(path), session=True)
        console.print(
            f"[dim]Device directory set to {_to_display_path(str(path))} for this session. "
            f"Run 'otampy device-dir --set {_to_display_path(str(path))}' to make it permanent.[/dim]"
        )

    except Exception as e:
        console.print(f"[red]✗ Error:[/red] {e}", style="red")
        raise click.ClickException(f"Failed to initialize project: {e}") from e


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
