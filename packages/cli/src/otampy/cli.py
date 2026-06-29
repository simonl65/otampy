import logging

import click
from rich.console import Console

import otampy.deploy as deploy

from .shared.protocol import OTA_COMMANDS

logger = logging.getLogger(__name__)


def _console() -> Console:
    return Console(highlight=False)


# Sanity-check the protocol at import time so maintainers see mismatches
try:
    logger.debug("Loaded OTA_COMMANDS: %s", OTA_COMMANDS)
except Exception:
    pass


class AliasedGroup(click.Group):
    """A Click Group that supports convenient aliases for its subcommands."""

    def get_command(
        self, ctx: click.Context, cmd_name: str
    ) -> click.Command | None:
        # First try to get the command exactly
        rv = click.Group.get_command(self, ctx, cmd_name)
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
        if cmd_name in aliases:
            return click.Group.get_command(self, ctx, aliases[cmd_name])
        return None

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted(click.Group.list_commands(self, ctx))


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(cls=AliasedGroup, context_settings=CONTEXT_SETTINGS)
def cli() -> None:
    """OTAmpy CLI - Over the air (OTA) file management for MicroPython devices."""
    pass


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


@cli.command(name="bl")
def bootloader() -> None:
    """Reboots device into its bootloader mode."""
    _console().print(
        "[yellow]Rebooting device into bootloader mode...[/yellow]"
    )


@cli.command(name="rb")
def reboot() -> None:
    """Hard reboots the device."""
    _console().print("[yellow]Hard rebooting the device...[/yellow]")


@cli.command(name="sr")
def soft_reset() -> None:
    """Soft resets the device."""
    _console().print("[yellow]Soft resetting the device...[/yellow]")


@cli.command(name="ls")
@click.argument("path", required=False)
def list_dir(path: str | None) -> None:
    """Lists content of current (or specified) folder on device."""
    if path:
        _console().print(f"[green]Listing content of {path}...[/green]")
    else:
        _console().print(
            "[green]Listing content of current directory...[/green]"
        )


@cli.command(name="cat")
@click.argument("file", required=True)
def cat(file: str) -> None:
    """Shows content of specified file on device."""
    _console().print(
        f"[green]Showing content of specified file: {file}[/green]"
    )


@cli.command(name="rm")
@click.argument("file", required=True)
def remove(file: str) -> None:
    """Remove specified file from device (may be wildcarded)."""
    _console().print(f"[red]Removing file: {file}[/red]")


@cli.command(name="upd")
@click.argument("args", nargs=-1)
def update(args: tuple[str, ...]) -> None:
    """Updates application firmware on device."""
    if not args:
        _console().print("[green]Updating all application firmware...[/green]")
    else:
        _console().print(
            f"[green]Updating firmware with arguments: {args}[/green]"
        )


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
