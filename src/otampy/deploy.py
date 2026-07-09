#!/usr/bin/env python3
"""Erase and deploy OTAmpy device files with mpremote."""

from __future__ import annotations

import argparse
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
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


def _find_package_lib_dir() -> Path:
    """Locate the versioned lib/ directory from the installed package.

    Always returns the lib/ bundled with this version of OTAmpy, regardless
    of the user's project directory.  Falls back to DEVICE_ROOT / 'lib' when
    running directly from the repository.
    """
    try:
        import importlib.resources as resources

        files_fn = getattr(resources, "files", None)
        if files_fn is not None and callable(files_fn):
            base = cast(Any, files_fn("otampy"))
            candidate = base.joinpath("device").joinpath("lib")
            candidate_any = cast(Any, candidate)
            # Materialise to a real Path so callers can use / and rglob
            if hasattr(candidate_any, "__fspath__"):
                p = Path(os.fspath(candidate_any))
            else:
                p = Path(str(candidate_any))
            if p.is_dir():
                return p
    except Exception:
        pass

    # Fallback when running from the development repository
    return DEVICE_ROOT / "lib"


ROOT = _find_repo_root()
DEVICE_ROOT = _find_device_root(ROOT)
LIB_DIR = DEVICE_ROOT / "lib"
CONFIG_FILE = DEVICE_ROOT / "examples" / "configota.py"
BOOT_FILE = DEVICE_ROOT / "examples" / "boot.py"
MAIN_FILE = DEVICE_ROOT / "examples" / "main.py"

MIP_PACKAGES = ("github:simonl65/URST-mpy",)
LOGGER_MIP_PACKAGE = "github:simonl65/log-to-file"


class DeployError(Exception):
    def __init__(self, returncode: int, output: str):
        self.returncode = returncode
        self.output = output


class BytecodeDeployError(Exception):
    """Raised when a target-matched bytecode deployment cannot be built."""


@dataclass(frozen=True)
class DeployArgs:
    port: str | None
    mpremote: str
    no_mip: bool
    with_logger: bool
    no_reset: bool
    dry_run: bool
    bytecode: bool = False
    mpy_cross: str = "mpy-cross"
    device_dir: Path | None = None


@dataclass(frozen=True)
class TargetMpy:
    value: int
    small_int_bits: int
    runtime: str

    @property
    def version(self) -> int:
        return self.value & 0xFF


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


def query_target_mpy(args: DeployArgs) -> TargetMpy:
    code = (
        "import sys\n"
        "value=getattr(sys.implementation,'_mpy',None)\n"
        "n=sys.maxsize\n"
        "bits=0\n"
        "while n:\n"
        " bits+=1\n"
        " n>>=1\n"
        "print('OTAMPY_MPY|%s|%s|%s' % "
        "(value,bits,sys.version.replace('|','/')))"
    )
    command = [
        *mpremote_prefix(args),
        "resume",
        "+",
        "exec",
        code,
        "+",
        "reset",
    ]
    print("$ " + shlex.join(command), flush=True)

    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        output = (result.stdout or "") + (result.stderr or "")
        raise DeployError(result.returncode, output)

    for line in result.stdout.splitlines():  # type: ignore
        if not line.startswith("OTAMPY_MPY|"):
            continue
        _, value, small_int_bits, runtime = line.split("|", 3)
        if value == "None":
            break
        try:
            return TargetMpy(
                value=int(value),  # type: ignore
                small_int_bits=int(small_int_bits),  # type: ignore
                runtime=runtime,  # type: ignore
            )
        except ValueError:
            break

    raise BytecodeDeployError("The target did not report a valid sys.implementation._mpy value.")


def wait_for_target(args: DeployArgs) -> None:
    command = [
        *mpremote_prefix(args),
        "resume",
        "+",
        "exec",
        "print('OTAMPY_READY')",
    ]
    print("$ " + shlex.join(command), flush=True)
    last_result = None

    for delay in (0, 1, 2):
        if delay:
            time.sleep(delay)
        last_result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if last_result.returncode == 0 and "OTAMPY_READY" in last_result.stdout:  # type: ignore
            return

        output = ((last_result.stdout or "") + (last_result.stderr or "")).lower()
        retryable = (
            "busy" in output or "could not open" in output or "no device" in output or "failed to access" in output
        )
        if not retryable:
            break

    assert last_result is not None
    output = (last_result.stdout or "") + (last_result.stderr or "")
    raise DeployError(last_result.returncode or 1, output)


def _mpy_cross_prefix(args: DeployArgs) -> list[str]:
    prefix = shlex.split(args.mpy_cross)
    if not prefix:
        raise BytecodeDeployError("The mpy-cross command cannot be empty.")
    return prefix  # type: ignore


def _run_mpy_cross(args: DeployArgs, arguments: list[str]) -> subprocess.CompletedProcess[str]:  # type: ignore
    command = [*_mpy_cross_prefix(args), *arguments]
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise BytecodeDeployError(
            f"Could not find mpy-cross command: {command[0]!r}. Install a compatible compiler or pass --mpy-cross."
        ) from error


def _validate_mpy_header(path: Path, target: TargetMpy) -> None:
    header = path.read_bytes()[:4]
    if len(header) != 4 or header[0] != ord("M"):
        raise BytecodeDeployError(f"{path.name} is not a valid .mpy file.")
    if header[1] != target.version:
        raise BytecodeDeployError(
            f"{path.name} uses .mpy version {header[1]}, but the target "
            f"requires version {target.version}. Install a compatible "
            "mpy-cross or pass --mpy-cross."
        )

    feature_flags = header[2]
    native_arch = (feature_flags >> 2) & 0x0F
    if native_arch or feature_flags & 0x40:
        raise BytecodeDeployError(f"{path.name} unexpectedly contains architecture-specific code.")
    if header[3] > target.small_int_bits:
        raise BytecodeDeployError(
            f"{path.name} requires {header[3]} small-int bits, but the target supports {target.small_int_bits}."
        )


def _compile_module(
    args: DeployArgs,
    source: Path,
    destination: Path,
    device_source: str,
    target: TargetMpy,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    arguments = [
        f"-msmall-int-bits={target.small_int_bits}",
        "-s",
        device_source,
        "-o",
        str(destination),
        str(source),
    ]
    result = _run_mpy_cross(args, arguments)
    if result.returncode:
        output = (result.stdout or "") + (result.stderr or "")
        raise BytecodeDeployError(f"mpy-cross failed for {source}: {output.strip()}")
    _validate_mpy_header(destination, target)


def _copy_compiled_tree(
    args: DeployArgs,
    source_root: Path,
    destination_root: Path,
    device_root: str,
    target: TargetMpy,
) -> int:
    count = 0
    for source in sorted(source_root.rglob("*")):
        relative = source.relative_to(source_root)
        if source.is_dir() or "__pycache__" in relative.parts:
            continue
        if source.suffix == ".py":
            destination = (destination_root / relative).with_suffix(".mpy")
            device_source = device_root.rstrip("/") + "/" + relative.as_posix()
            _compile_module(
                args,
                source,
                destination,
                device_source,
                target,
            )
            count += 1
        elif source.suffix != ".pyc":
            destination = destination_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    return count


def _urst_source_dir() -> Path:
    spec = importlib.util.find_spec("urst")
    locations = None if spec is None else spec.submodule_search_locations
    if not locations:
        raise BytecodeDeployError("Could not locate the installed URST source package.")
    source_dir = Path(next(iter(locations)))
    if not source_dir.is_dir():
        raise BytecodeDeployError(f"Installed URST source directory does not exist: {source_dir}")
    return source_dir


def build_bytecode_lib(
    args: DeployArgs,
    destination: Path,
    target: TargetMpy,
) -> int:
    result = _run_mpy_cross(args, ["--version"])
    if result.returncode:
        output = (result.stdout or "") + (result.stderr or "")
        raise BytecodeDeployError(f"Could not run mpy-cross: {output.strip()}")

    paths = _resolve_deploy_paths(args)
    count = _copy_compiled_tree(
        args,
        paths.lib_dir,
        destination,
        "/lib",
        target,
    )
    count += _copy_compiled_tree(
        args,
        _urst_source_dir(),
        destination / "urst",
        "/lib/urst",
        target,
    )
    compiler_version = (result.stdout or result.stderr).strip()  # type: ignore
    print(f"Built {count} target-matched .mpy modules with {compiler_version}.")
    return count


@dataclass(frozen=True)
class DeployPaths:
    """Resolved source paths for a deploy operation.

    ``lib_dir`` always comes from the installed package so it stays in sync
    with the OTAmpy version.  The three user files (``config_file``,
    ``boot_file``, ``main_file``) come from the user's project directory when
    ``--device-dir`` is supplied, or fall back to the package's own
    ``examples/`` when running from the repository.
    """

    lib_dir: Path
    config_file: Path
    boot_file: Path
    main_file: Path


def _resolve_user_files(device_dir: Path) -> tuple[Path, Path, Path]:
    """Return (config, boot, main) paths from a user project directory.

    Files are expected flat in *device_dir* (as ``otampy init`` places them).
    """
    return (
        device_dir / "configota.py",
        device_dir / "boot.py",
        device_dir / "main.py",
    )


def _resolve_deploy_paths(args: DeployArgs) -> DeployPaths:
    """Return the effective source paths for *args*.

    ``lib_dir`` is always sourced from the installed package.
    User files are sourced from ``args.device_dir`` when set, otherwise
    from the package's own ``examples/`` directory (repo / dev use).
    """
    lib_dir = _find_package_lib_dir()

    if args.device_dir is not None:
        config_file, boot_file, main_file = _resolve_user_files(args.device_dir.resolve())
    else:
        # Repo / developer fallback: files live under examples/
        config_file = DEVICE_ROOT / "examples" / "configota.py"
        boot_file = DEVICE_ROOT / "examples" / "boot.py"
        main_file = DEVICE_ROOT / "examples" / "main.py"

    return DeployPaths(
        lib_dir=lib_dir,  # type: ignore
        config_file=config_file,  # type: ignore
        boot_file=boot_file,  # type: ignore
        main_file=main_file,  # type: ignore
    )


def validate_deploy_sources(args: DeployArgs | None = None) -> None:
    """Ensure local deploy sources exist before any destructive device operation."""
    if args is None:
        # Backwards-compatible call with no args — use module-level constants
        paths = DeployPaths(
            lib_dir=LIB_DIR,  # type: ignore
            config_file=CONFIG_FILE,  # type: ignore
            boot_file=BOOT_FILE,  # type: ignore
            main_file=MAIN_FILE,  # type: ignore
        )
    else:
        paths = _resolve_deploy_paths(args)

    missing = [
        path
        for path in (
            paths.lib_dir,
            paths.config_file,
            paths.boot_file,
            paths.main_file,
        )
        if not path.exists()
    ]
    if not missing:
        return

    rel_paths = ", ".join(str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path) for path in missing)
    print(f"Error: missing deploy source(s): {rel_paths}", file=sys.stderr)
    if paths.config_file in missing:
        if args is not None and args.device_dir is not None:
            # User's project dir — tell them to run `otampy init` or copy the example
            print(
                f"Run 'otampy init {args.device_dir}' to create the missing files, "
                "or copy config.example.py to configota.py and edit it.",
                file=sys.stderr,
            )
        else:
            example = paths.config_file.parent / "config.example.py"
            example_str = str(example.relative_to(ROOT)) if example.is_relative_to(ROOT) else str(example)
            print(
                f"Create configota.py from {example_str} before deploying.",
                file=sys.stderr,
            )
    raise SystemExit(1)


def deploy_command(
    args: DeployArgs,
    lib_dir: Path | None = None,
) -> list[str]:
    paths = _resolve_deploy_paths(args)
    effective_lib_dir = lib_dir if lib_dir is not None else paths.lib_dir

    command = [
        "resume",
        "rm",
        "-r",
        ":",
        "+",
        "cp",
        "-r",
        str(effective_lib_dir),
        str(paths.config_file),
        str(paths.main_file),
        str(paths.boot_file),
        ":",
    ]

    if not args.bytecode and not args.no_mip:
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
    validate_deploy_sources(args)
    _remove_pycache_dirs()
    if not args.bytecode:
        run_mpremote(args, deploy_command(args))
        return

    if args.with_logger:
        raise BytecodeDeployError(
            "--bytecode cannot be combined with --with-logger; use the source profile for development logging."
        )

    if args.dry_run:
        query = [
            *mpremote_prefix(args),
            "resume",
            "+",
            "exec",
            "<query target .mpy compatibility>",
            "+",
            "reset",
        ]
        print("$ " + shlex.join(query))
        print(
            "$ "
            + shlex.join(
                [
                    *_mpy_cross_prefix(args),
                    "<target flags>",
                    "<OTAmpy and URST sources>",
                ]
            )
        )
        print(
            "$ "
            + shlex.join(
                [
                    *mpremote_prefix(args),
                    "resume",
                    "+",
                    "exec",
                    "<wait for target>",
                ]
            )
        )
        run_mpremote(
            args,
            deploy_command(
                args,
                Path("<target-matched-mpy-lib>"),
            ),
        )
        return

    target = query_target_mpy(args)
    print(f"Target reports .mpy version {target.version}, {target.small_int_bits} small-int bits.")
    with tempfile.TemporaryDirectory(prefix="otampy-mpy-") as temp_dir:
        lib_dir = Path(temp_dir) / "lib"
        build_bytecode_lib(args, lib_dir, target)
        wait_for_target(args)
        run_mpremote(args, deploy_command(args, lib_dir))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Erase and deploy OTAmpy lib/, boot.py, and main.py to a MicroPython device.")
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
        "--bytecode",
        "--mpy",
        dest="bytecode",
        action="store_true",
        help="Deploy target-matched .mpy libraries.",
    )
    parser.add_argument(
        "--mpy-cross",
        default="mpy-cross",
        help="mpy-cross executable or command to use.",
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

    detail = error.output.strip()
    if detail:
        print(f"mpremote output:\n{detail}", file=sys.stderr)

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
    except BytecodeDeployError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
