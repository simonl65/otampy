#!/usr/bin/env python3
"""Erase and deploy OTAmpy device files with mpremote."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


def _find_repo_root() -> Path:
    """Find the repository root by scanning parents for project files.

    Falls back to the installed package location when no repo markers are found.
    """
    here = Path(__file__).resolve()
    for p in (here, *here.parents):
        if (p / ".git").exists() or (p / "LICENSE.md").exists():
            return p

    # Fallback: use package resources for installed packages
    try:
        import importlib.resources as resources

        files_fn = getattr(resources, "files", None)
        if files_fn is None or not callable(files_fn):
            raise RuntimeError("importlib.resources.files not available")

        pkg = files_fn("otampy")
        pkg_any = cast(Any, pkg)
        # Traversable may not be directly path-like for Path(); use os.fspath or str()
        if hasattr(pkg_any, "__fspath__"):
            return Path(os.fspath(pkg_any))
        return Path(str(pkg_any))
    except Exception:
        return here.parent


def _find_device_root(root: Path) -> Path:
    """Locate the `device` package directory from a repo root or installed package.

    Search common candidate locations and fall back to the prior relative path.
    """
    # Look for `packages/device` or top-level `device` under the repo or its parents
    for p in (root, *root.parents):
        candidates = (p / "packages" / "device", p / "device")
        for candidate in candidates:
            if candidate.exists():
                return candidate

    # Try to find a `device` resource in the installed package
    try:
        import importlib.resources as resources

        files_fn = getattr(resources, "files", None)
        if files_fn is not None and callable(files_fn):
            base = files_fn("otampy")
            base_any = cast(Any, base)
            join = getattr(base_any, "joinpath", None)
            dev = None
            if callable(join):
                dev = base_any.joinpath("device")
            else:
                # Fallback: try building a path from the base's fs path
                try:
                    base_path = Path(os.fspath(base_any))
                    candidate = base_path / "device"
                    if candidate.is_dir():
                        return candidate
                except Exception:
                    pass

            if dev is not None:
                dev_any = cast(Any, dev)
                if hasattr(dev_any, "__fspath__"):
                    return Path(os.fspath(dev_any))
                return Path(str(dev_any))
    except Exception:
        pass

    # Last resort: preserve previous heuristic
    return Path(__file__).resolve().parent / "packages" / "device"


ROOT = _find_repo_root()
DEVICE_ROOT = _find_device_root(ROOT)
LIB_DIR = DEVICE_ROOT / "lib"
CONFIG_FILE = DEVICE_ROOT / "examples" / "config.py"
BOOT_FILE = DEVICE_ROOT / "examples" / "boot.py"
MAIN_FILE = DEVICE_ROOT / "examples" / "main.py"

MIP_PACKAGES = ("github:simonl65/URST-mpy",)
LOGGER_MIP_PACKAGE = "github:simonl65/log-to-file"


class DeployError(Exception):
    def __init__(self, returncode: int, output: str):
        self.returncode = returncode
        self.output = output


@dataclass(frozen=True)
class DeployArgs:
    port: str | None
    mpremote: str
    no_mip: bool
    with_logger: bool
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


def validate_deploy_sources() -> None:
    """Ensure local deploy sources exist before any destructive device operation."""
    missing = [
        path
        for path in (LIB_DIR, CONFIG_FILE, BOOT_FILE, MAIN_FILE)
        if not path.exists()
    ]
    if not missing:
        return

    rel_paths = ", ".join(
        str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        for path in missing
    )
    print(f"Error: missing deploy source(s): {rel_paths}", file=sys.stderr)
    if CONFIG_FILE in missing:
        example = CONFIG_FILE.parent / "config.example.py"
        print(
            f"Create config.py from {example.relative_to(ROOT)} before deploying.",
            file=sys.stderr,
        )
    raise SystemExit(1)


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
        if args.with_logger:
            command.append(LOGGER_MIP_PACKAGE)

    if not args.no_reset:
        command.extend(("+", "reset"))

    return command


def _remove_pycache_dirs() -> None:
    """Remove local __pycache__ directories from the workspace before copying files."""
    if not ROOT.is_dir():
        return

    for pycache_dir in ROOT.rglob("__pycache__"):
        if pycache_dir.is_dir():
            shutil.rmtree(pycache_dir)


def deploy(args: DeployArgs) -> None:
    validate_deploy_sources()
    _remove_pycache_dirs()
    run_mpremote(args, deploy_command(args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Erase and deploy OTAmpy lib/, boot.py, and main.py "
            "to a MicroPython device."
        )
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
        help="Skip installing all MicroPython dependencies with mip.",
    )
    parser.add_argument(
        "--with-logger",
        action="store_true",
        help="Install log-to-file for development logging.",
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
