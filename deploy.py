#!/usr/bin/env python3
"""Deploy OTAmpy device files to a MicroPython board with mpremote."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEVICE_ROOT = ROOT / "packages" / "device"
LIB_DIR = DEVICE_ROOT / "lib"
CONFIG_FILE = DEVICE_ROOT / "examples" / "config.py"
BOOT_FILE = DEVICE_ROOT / "examples" / "boot.py"
MAIN_FILE = DEVICE_ROOT / "examples" / "main.py"

MIP_PACKAGES = ("github:simonl65/log-to-file", "github:simonl65/URST-mpy")


class DeployError(Exception):
    def __init__(self, returncode: int, output: str):
        self.returncode = returncode
        self.output = output


@dataclass(frozen=True)
class DeployArgs:
    port: str | None
    mpremote: str
    no_mip: bool
    no_reset: bool
    dry_run: bool


def mpremote_prefix(args: DeployArgs) -> list[str]:
    prefix = [args.mpremote]
    if args.port:
        prefix.extend(("connect", args.port))
    return prefix


def run_mpremote(args: DeployArgs, command: list[str]) -> None:
    cmd = [*mpremote_prefix(args), *command]
    print("$ " + shlex.join(cmd), flush=True)
    if args.dry_run:
        return

    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode:
        output = (result.stdout or "") + (result.stderr or "")
        raise DeployError(result.returncode, output)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)


def deploy_command(args: DeployArgs) -> list[str]:
    command = [
        "resume",
        "rm",
        "-r",
        ":",
        "+",
        "cp",
        "-r",
        str(LIB_DIR),
        str(CONFIG_FILE),
        str(MAIN_FILE),
        str(BOOT_FILE),
        ":",
    ]

    if not args.no_mip:
        command.extend(("+", "mip", "install", *MIP_PACKAGES))

    if not args.no_reset:
        command.extend(("+", "reset"))

    return command


def deploy(args: DeployArgs) -> None:
    run_mpremote(args, deploy_command(args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deploy OTAmpy lib/, boot.py, and main.py to a MicroPython device."
    )
    parser.add_argument(
        "-p",
        "--port",
        help="Serial port to connect to, for example /dev/ttyACM0 or COM3.",
    )
    parser.add_argument(
        "--mpremote",
        default="mpremote",
        help="mpremote executable to use.",
    )
    parser.add_argument(
        "--no-mip",
        action="store_true",
        help="Skip installing MicroPython dependencies with mip.",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Skip resetting the device after deployment.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print mpremote commands without running them.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> DeployArgs:
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv

    if not argv:
        parser.print_help()
        raise SystemExit(0)

    return DeployArgs(**vars(parser.parse_args(argv)))


def print_deploy_error(error: DeployError) -> None:
    output = error.output.lower()
    print(
        f"Error: mpremote command failed with exit code {error.returncode}.",
        file=sys.stderr,
    )

    if "could not enter raw repl" in output:
        print(
            "mpremote could not enter raw REPL on the device.",
            file=sys.stderr,
        )
    elif "no device" in output or "could not open port" in output:
        print("mpremote could not find or open the device.", file=sys.stderr)

    print(
        "Check that the device is connected, not in use by another program, "
        "and pass --port if auto-detection did not find it.",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        deploy(parse_args(argv))
    except FileNotFoundError as error:
        print(
            f"Error: could not find {error.filename!r}. Install mpremote with "
            "`uv tool install mpremote` or pass --mpremote.",
            file=sys.stderr,
        )
        return 1
    except DeployError as error:
        print_deploy_error(error)
        return error.returncode or 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
