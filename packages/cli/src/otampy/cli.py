import logging

import click
from rich.console import Console

logger = logging.getLogger(__name__)


console = Console()


class AliasedGroup(click.Group):
    """A Click Group that supports convenient aliases for its subcommands."""

    def get_command(
        self, ctx: click.Context, name: str
    ) -> click.Command | None:
        # First try to get the command exactly
        rv = click.Group.get_command(self, ctx, name)
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
        if name in aliases:
            return click.Group.get_command(self, ctx, aliases[name])
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
    console.print(
        "[bold cyan]OTAmpy[/bold cyan] - Over the Air (OTA) File Management CLI"
    )
    console.print("Show helpful information about OTAmpy and its commands.")
    console.print()
    if ctx.parent:
        console.print(ctx.parent.get_help())


@cli.command(name="bl")
def bootloader() -> None:
    """Reboots device into its bootloader mode."""
    console.print("[yellow]Rebooting device into bootloader mode...[/yellow]")


@cli.command(name="rb")
def reboot() -> None:
    """Hard reboots the device."""
    console.print("[yellow]Hard rebooting the device...[/yellow]")


@cli.command(name="sr")
def soft_reset() -> None:
    """Soft resets the device."""
    console.print("[yellow]Soft resetting the device...[/yellow]")


@cli.command(name="ls")
@click.argument("path", required=False)
def list_dir(path: str | None) -> None:
    """Lists content of current (or specified) folder on device."""
    if path:
        console.print(f"[green]Listing content of {path}...[/green]")
    else:
        console.print("[green]Listing content of current directory...[/green]")


@cli.command(name="cat")
@click.argument("file", required=True)
def cat(file: str) -> None:
    """Shows content of specified file on device."""
    console.print(f"[green]Showing content of specified file: {file}[/green]")


@cli.command(name="rm")
@click.argument("file", required=True)
def remove(file: str) -> None:
    """Remove specified file from device (may be wildcarded)."""
    console.print(f"[red]Removing file: {file}[/red]")


@cli.command(name="upd")
@click.argument("args", nargs=-1)
def update(args: tuple[str, ...]) -> None:
    """Updates application firmware on device."""
    if not args:
        console.print("[green]Updating all application firmware...[/green]")
    else:
        console.print(
            f"[green]Updating firmware with arguments: {args}[/green]"
        )


@cli.command(name="mem")
def memory() -> None:
    """Retrieves current free and todal memory from the device."""
    console.print("[green]Getting device's memory details...[/green]")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
