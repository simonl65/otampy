import logging

import click
from rich.console import Console

import otampy.deploy as deploy

logger = logging.getLogger(__name__)


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
            "help": "h",
            "bootloader": "bl",
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


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(cls=AliasedGroup, context_settings=CONTEXT_SETTINGS)
@click.option(
    "-p",
    "--port",
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


def _query(ctx: click.Context, command: bytes, expected_prefix: bytes) -> bytes:
    port = ctx.obj.get("port")
    baud = ctx.obj.get("baud")
    if not port:
        raise click.ClickException(
            "Error: Missing serial port. Specify with --port or -p option."
        )

    import serial
    from urst import Urst

    try:
        ser = serial.Serial(port, baudrate=baud, timeout=2.0)
        transport = Urst(ser)
    except Exception as e:
        raise click.ClickException(f"Failed to open serial port {port}: {e}") from e

    try:
        transport.send(command)
        response = transport.read()
        if not response:
            raise click.ClickException(
                f"Timeout waiting for response to command: {command.decode()}"
            )

        # Check for device error response
        if response.startswith(b"ERROR:"):
            err_msg = response[6:].decode("utf-8", errors="replace")
            raise click.ClickException(f"Device error: {err_msg}")

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
        if len(response) > prefix_len and response[prefix_len : prefix_len + 1] == b":":
            return response[prefix_len + 1 :]
        return response[prefix_len:]
    finally:
        ser.close()


def _send_command(
    ctx: click.Context, command: bytes, expected_response: bytes
) -> None:
    _query(ctx, command, expected_response)


@cli.command(name="h")
def help_cmd() -> None:
    """Shows helpful information about OTAmpy and its commands."""
    ctx = click.get_current_context()
    _console().print(
        "[bold cyan]OTAmpy[/bold cyan] - Over the Air (OTA) File Management CLI"
    )
    _console().print("Show helpful information about OTAmpy and its commands.")
    _console().print()
    if ctx.parent:
        _console().print(ctx.parent.get_help())


@cli.command(name="ping")
@click.pass_context
def ping(ctx: click.Context) -> None:
    """Connection health check with the device."""
    _console().print("[yellow]Sending PING to device...[/yellow]")
    _send_command(ctx, b"PING", b"PONG")
    _console().print("[green]Success: Received PONG from device.[/green]")


@cli.command(name="bl")
@click.pass_context
def bootloader(ctx: click.Context) -> None:
    """Reboots device into its bootloader mode."""
    _console().print(
        "[yellow]Rebooting device into bootloader mode...[/yellow]"
    )
    _send_command(ctx, b"BL", b"BL_OK")


@cli.command(name="rb")
@click.pass_context
def reboot(ctx: click.Context) -> None:
    """Hard reboots the device."""
    _console().print("[yellow]Hard rebooting the device...[/yellow]")
    _send_command(ctx, b"RB", b"RB_OK")


@cli.command(name="sr")
@click.pass_context
def soft_reset(ctx: click.Context) -> None:
    """Soft resets the device."""
    _console().print("[yellow]Soft resetting the device...[/yellow]")
    _send_command(ctx, b"SR", b"SR_OK")


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

    resp = _query(ctx, cmd, b"LS_OK")
    items_str = resp.decode("utf-8", errors="replace")
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
    resp = _query(ctx, f"CAT:{file}".encode(), b"CAT_OK")
    content = resp.decode("utf-8", errors="replace")
    _console().print(content)


@cli.command(name="rm")
@click.argument("file", required=True)
@click.pass_context
def remove(ctx: click.Context, file: str) -> None:
    """Remove specified file from device (may be wildcarded)."""
    _console().print(f"[red]Removing file: {file}[/red]")
    _send_command(ctx, f"RM:{file}".encode(), b"RM_OK")


@cli.command(name="upd")
@click.argument("args", nargs=-1)
@click.pass_context
def update(ctx: click.Context, args: tuple[str, ...]) -> None:
    """Updates application firmware on device."""
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
            ser = serial.Serial(port, baudrate=baud, timeout=1.0)
            transport = Urst(ser)
            resp = transport.read()
            if resp == b"READY":
                break
            ser.close()
            ser = None
        except Exception:
            if ser:
                ser.close()
                ser = None
            time.sleep(0.2)

    if not transport or not ser:
        raise click.ClickException("Timeout waiting for device READY broadcast.")

    _console().print("[green]Device is READY. Handshake complete.[/green]")
    ser.close()


@cli.command(name="mem")
def memory() -> None:
    """Retrieves current free and todal memory from the device."""
    _console().print("[green]Getting device's memory details...[/green]")


@cli.command(name="deploy")
@click.option(
    "-p",
    "--port",
    help="Serial port to connect to, for example /dev/ttyACM0 or COM3.",
    default=None,
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
    no_reset: bool,
    dry_run: bool,
) -> None:
    """Deploy OTAmpy lib/, boot.py, and main.py to a MicroPython device."""
    args = deploy.DeployArgs(
        port=port,  # type: ignore
        mpremote=mpremote,  # type: ignore
        no_mip=no_mip,  # type: ignore
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
