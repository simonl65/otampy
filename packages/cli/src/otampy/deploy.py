#!/usr/bin/env python3
"""Erase and deploy OTAmpy device files with mpremote."""

from __future__ import annotations

import argparse
import importlib.util
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from otampy.project import DeviceSources, resolve_device_sources

_DEFAULT_SOURCES = resolve_device_sources(Path.cwd())
ROOT = _DEFAULT_SOURCES.project_root
DEVICE_ROOT = _DEFAULT_SOURCES.device_root
LIB_DIR = _DEFAULT_SOURCES.lib_dir
CONFIG_FILE = _DEFAULT_SOURCES.config_file
BOOT_FILE = _DEFAULT_SOURCES.boot_file
MAIN_FILE = _DEFAULT_SOURCES.main_file

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
    project: Path | None = None


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
    command = [*mpremote_prefix(args), "resume", "+", "exec", code, "+", "reset"]
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

    for line in result.stdout.splitlines():
        if not line.startswith("OTAMPY_MPY|"):
            continue
        _, value, small_int_bits, runtime = line.split("|", 3)
        if value == "None":
            break
        try:
            return TargetMpy(
                value=int(value),
                small_int_bits=int(small_int_bits),
                runtime=runtime,
            )
        except ValueError:
            break

    raise BytecodeDeployError(
        "The target did not report a valid sys.implementation._mpy value."
    )


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
        if last_result.returncode == 0 and "OTAMPY_READY" in last_result.stdout:
            return

        output = ((last_result.stdout or "") + (last_result.stderr or "")).lower()
        retryable = (
            "busy" in output
            or "could not open" in output
            or "no device" in output
            or "failed to access" in output
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
    return prefix


def _run_mpy_cross(
    args: DeployArgs, arguments: list[str]
) -> subprocess.CompletedProcess[str]:
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
            f"Could not find mpy-cross command: {command[0]!r}. "
            "Install a compatible compiler or pass --mpy-cross."
        ) from error


def _validate_mpy_header(path: Path, target: TargetMpy) -> None:
    header = path.read_bytes()[:4]
    if len(header) != 4 or header[0] != ord("M"):
        raise BytecodeDeployError(
            f"{path.name} is not a valid .mpy file."
        )
    if header[1] != target.version:
        raise BytecodeDeployError(
            f"{path.name} uses .mpy version {header[1]}, but the target "
            f"requires version {target.version}. Install a compatible "
            "mpy-cross or pass --mpy-cross."
        )

    feature_flags = header[2]
    native_arch = (feature_flags >> 2) & 0x0F
    if native_arch or feature_flags & 0x40:
        raise BytecodeDeployError(
            f"{path.name} unexpectedly contains architecture-specific code."
        )
    if header[3] > target.small_int_bits:
        raise BytecodeDeployError(
            f"{path.name} requires {header[3]} small-int bits, but the "
            f"target supports {target.small_int_bits}."
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
        raise BytecodeDeployError(
            f"mpy-cross failed for {source}: {output.strip()}"
        )
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
            device_source = (
                device_root.rstrip("/") + "/" + relative.as_posix()
            )
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
        raise BytecodeDeployError(
            "Could not locate the installed URST source package."
        )
    source_dir = Path(next(iter(locations)))
    if not source_dir.is_dir():
        raise BytecodeDeployError(
            f"Installed URST source directory does not exist: {source_dir}"
        )
    return source_dir


def build_bytecode_lib(
    args: DeployArgs,
    destination: Path,
    target: TargetMpy,
    source_lib: Path | None = None,
) -> int:
    source_lib = LIB_DIR if source_lib is None else source_lib
    result = _run_mpy_cross(args, ["--version"])
    if result.returncode:
        output = (result.stdout or "") + (result.stderr or "")
        raise BytecodeDeployError(
            f"Could not run mpy-cross: {output.strip()}"
        )

    count = _copy_compiled_tree(
        args,
        source_lib,
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
    compiler_version = (result.stdout or result.stderr).strip()
    print(
        f"Built {count} target-matched .mpy modules "
        f"with {compiler_version}."
    )
    return count


def _legacy_sources() -> DeviceSources:
    """Return module-level paths retained for direct API compatibility."""
    return DeviceSources(
        project_root=ROOT,
        device_root=DEVICE_ROOT,
        lib_dir=LIB_DIR,
        config_file=CONFIG_FILE,
        boot_file=BOOT_FILE,
        main_file=MAIN_FILE,
        config_example_file=CONFIG_FILE.parent / "config.example.py",
    )


def _sources_for_args(args: DeployArgs) -> DeviceSources:
    project = getattr(args, "project", None)
    if project is None:
        return _legacy_sources()
    return resolve_device_sources(project)


def validate_deploy_sources(sources: DeviceSources | None = None) -> None:
    """Ensure local deploy sources exist before any destructive device operation."""
    sources = _legacy_sources() if sources is None else sources
    missing = [
        path
        for path in (
            sources.lib_dir,
            sources.config_file,
            sources.boot_file,
            sources.main_file,
        )
        if not path.exists()
    ]
    if not missing:
        return

    rel_paths = ", ".join(
        str(path.relative_to(sources.project_root))
        if path.is_relative_to(sources.project_root)
        else str(path)
        for path in missing
    )
    print(f"Error: missing deploy source(s): {rel_paths}", file=sys.stderr)
    if sources.config_file in missing:
        if sources.config_example_file.is_file():
            print(
                f"Create config.py from {sources.config_example_file} "
                "before deploying.",
                file=sys.stderr,
            )
        else:
            print(
                "Run `otampy init` in the project directory, then edit "
                f"{sources.config_file} before deploying.",
                file=sys.stderr,
            )
    raise SystemExit(1)


def deploy_command(
    args: DeployArgs,
    lib_dir: Path | None = None,
    sources: DeviceSources | None = None,
) -> list[str]:
    sources = _sources_for_args(args) if sources is None else sources
    lib_dir = sources.lib_dir if lib_dir is None else lib_dir
    command = [
        "resume",
        "rm",
        "-r",
        ":",
        "+",
        "cp",
        "-r",
        str(lib_dir),
        str(sources.config_file),
        str(sources.main_file),
        str(sources.boot_file),
        ":",
    ]

    if not args.bytecode and not args.no_mip:
        command.extend(("+", "mip", "install", *MIP_PACKAGES))
        if args.with_logger:
            command.append(LOGGER_MIP_PACKAGE)

    if not args.no_reset:
        command.extend(("+", "reset"))

    return command


def _remove_pycache_dirs(lib_dir: Path) -> None:
    """Remove local __pycache__ directories from the copied library tree."""
    if not lib_dir.is_dir():
        return

    for pycache_dir in lib_dir.rglob("__pycache__"):
        if pycache_dir.is_dir():
            shutil.rmtree(pycache_dir)


def deploy(args: DeployArgs) -> None:
    sources = _sources_for_args(args)
    validate_deploy_sources(sources)
    _remove_pycache_dirs(sources.lib_dir)
    if not args.bytecode:
        run_mpremote(args, deploy_command(args, sources=sources))
        return

    if args.with_logger:
        raise BytecodeDeployError(
            "--bytecode cannot be combined with --with-logger; "
            "use the source profile for development logging."
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
                sources,
            ),
        )
        return

    target = query_target_mpy(args)
    print(
        f"Target reports .mpy version {target.version}, "
        f"{target.small_int_bits} small-int bits."
    )
    with tempfile.TemporaryDirectory(prefix="otampy-mpy-") as temp_dir:
        lib_dir = Path(temp_dir) / "lib"
        build_bytecode_lib(args, lib_dir, target, sources.lib_dir)
        wait_for_target(args)
        run_mpremote(args, deploy_command(args, lib_dir, sources))


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
        "--project",
        type=Path,
        default=Path.cwd(),
        help="Project directory containing device/ (default: current directory).",
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
