#!/usr/bin/env python3
"""Deploy OTAmpy device files to a MicroPython board with mpremote."""

# TODO: The following complete command works without fail: `mr resume rm -r : + cp -r packages/device/lib/ packages/device/examples/config.py packages/device/examples/main.py packages/device/examples/boot.py : + mip install "github:simonl65/log-to-file" "github:simonl65/URST-mpy" + reset`

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEVICE_ROOT = ROOT / "packages" / "device"
LIB_DIR = DEVICE_ROOT / "lib"
CONFIG_FILE = DEVICE_ROOT / "examples" / "config.py"
BOOT_FILE = DEVICE_ROOT / "examples" / "boot.py"
MAIN_FILE = DEVICE_ROOT / "examples" / "main.py"

MIP_PACKAGES = ("github:simonl65/URST-mpy", "github:simonl65/log-to-file")


class DeployError(Exception):
    def __init__(self, returncode: int, output: str):
        self.returncode = returncode
        self.output = output


def mpremote_prefix(args: argparse.Namespace) -> list[str]:
    prefix = [args.mpremote]
    if args.port:
        prefix.extend(("connect", args.port))
    return prefix


def run_mpremote(args: argparse.Namespace, command: list[str]) -> None:
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
        raise DeployError(result.returncode, result.stdout + result.stderr)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)


def mkdir_command(path: str) -> list[str]:
    return [
        "exec",
        f"import os\ntry:\n    os.mkdir({path!r})\nexcept OSError:\n    pass",
    ]


def should_deploy(path: Path) -> bool:
    return "__pycache__" not in path.parts and path.suffix != ".pyc"


def copy_tree_commands(source: Path, remote_root: str) -> list[list[str]]:
    commands = [mkdir_command(remote_root)]

    directories = (path for path in source.rglob("*") if path.is_dir())
    for directory in sorted(
        path for path in directories if should_deploy(path)
    ):
        remote_path = (
            f"{remote_root}/{directory.relative_to(source).as_posix()}"
        )
        commands.append(mkdir_command(remote_path))

    files = (path for path in source.rglob("*") if path.is_file())
    for file in sorted(path for path in files if should_deploy(path)):
        remote_path = f"{remote_root}/{file.relative_to(source).as_posix()}"
        commands.append(["cp", str(file), f":{remote_path}"])

    return commands


def file_deploy_commands() -> list[list[str]]:
    commands = copy_tree_commands(LIB_DIR, "/lib")
    commands.append(["cp", str(CONFIG_FILE), ":config.py"])
    commands.append(["cp", str(BOOT_FILE), ":boot.py"])
    commands.append(["cp", str(MAIN_FILE), ":main.py"])
    return commands


def deploy(args: argparse.Namespace) -> None:
    if not args.no_mip:
        for package in MIP_PACKAGES:
            run_mpremote(args, ["mip", "install", package])

    for command in file_deploy_commands():
        run_mpremote(args, command)

    if not args.no_reset:
        if args.reset_delay:
            print(f"Waiting {args.reset_delay:g}s before reset...", flush=True)
            if not args.dry_run:
                time.sleep(args.reset_delay)
        run_mpremote(args, ["reset"])


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
        "--reset-delay",
        default=2.0,
        type=float,
        help="Seconds to wait after copying files before resetting the device.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print mpremote commands without running them.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv

    if not argv:
        parser.print_help()
        raise SystemExit(0)

    return parser.parse_args(argv)


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
