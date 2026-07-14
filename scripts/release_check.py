#!/usr/bin/env python3
"""Build and verify OTAmpy release artifacts from canonical sources."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
CLI_ROOT = ROOT
DEVICE_ROOT = ROOT / "src" / "otampy" / "device"
DEFAULT_OUTPUT = ROOT / "release-dist"
BUNDLE_RELATIVE = Path("src/otampy/device")
EXAMPLE_FILES = ("boot.py", "main.py", "configota.example.py")
IGNORED_NAMES = {
    "__pycache__",
    ".coverage",
    ".pytest_cache",
    ".ruff_cache",
    ".git",
    ".venv",
    "release-dist",
    "dist",
    "configota.py",
}


class ReleaseCheckError(Exception):
    """Raised when an artifact is not safe or complete enough to publish."""


def _run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(command), flush=True)
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture,
    )


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in IGNORED_NAMES or name.endswith((".pyc", ".pyo"))
    }


def _project_version() -> str:
    with (CLI_ROOT / "pyproject.toml").open("rb") as file:
        metadata = tomllib.load(file)
    return str(metadata["project"]["version"])


def _project_name(project_root: Path) -> str:
    with (project_root / "pyproject.toml").open("rb") as file:
        metadata = tomllib.load(file)
    return str(metadata["project"]["name"])


def _require_clean_worktree() -> None:
    result = _run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        capture=True,
    )
    if result.stdout.strip():
        raise ReleaseCheckError(
            "The worktree is not clean. Commit or stash changes before creating release artifacts."
        )


def stage_package(destination: Path) -> Path:
    """Create a build tree containing generated package device resources."""
    package_root = destination / "otampy-package"
    shutil.copytree(CLI_ROOT, package_root, ignore=_copy_ignore)

    bundle = package_root / BUNDLE_RELATIVE
    examples = bundle / "examples"
    forbidden_config = examples / "configota.py"
    if forbidden_config.exists():
        raise ReleaseCheckError(
            f"Private configuration must not enter the release: {forbidden_config}"
        )
    return package_root


def _archive_files(path: Path) -> dict[str, bytes]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return {
                name: archive.read(name)
                for name in archive.namelist()
                if not name.endswith("/")
            }

    with tarfile.open(path, "r:gz") as archive:
        files: dict[str, bytes] = {}
        for member in archive.getmembers():
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ReleaseCheckError(f"Could not inspect {member.name}")
            files[member.name] = extracted.read()
        return files


def _find_archive_member(files: dict[str, bytes], suffix: str) -> str:
    matches = [name for name in files if name.endswith(suffix)]
    if len(matches) != 1:
        raise ReleaseCheckError(
            f"Expected one archive member ending in {suffix!r}; found {matches}"
        )
    return matches[0]


def _canonical_bundle_files() -> dict[str, Path]:
    files = {
        f"lib/{path.relative_to(DEVICE_ROOT / 'lib').as_posix()}": path
        for path in (DEVICE_ROOT / "lib").rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    }
    files.update(
        {
            f"examples/{name}": DEVICE_ROOT / "examples" / name
            for name in EXAMPLE_FILES
        }
    )
    return files


def inspect_artifact(path: Path) -> None:
    """Verify bundle completeness, provenance, and release hygiene."""
    files = _archive_files(path)
    names = tuple(files)

    forbidden_names = [
        name
        for name in names
        if "__pycache__" in Path(name).parts
        or name.endswith((".pyc", ".pyo"))
        or name.endswith("/device/examples/configota.py")
    ]
    if forbidden_names:
        raise ReleaseCheckError(
            f"Forbidden generated or private files in {path.name}: {forbidden_names}"
        )

    for relative, canonical in _canonical_bundle_files().items():
        suffix = f"otampy/device/{relative}"
        member = _find_archive_member(files, suffix)
        if (
            hashlib.sha256(files[member]).digest()
            != hashlib.sha256(canonical.read_bytes()).digest()
        ):
            raise ReleaseCheckError(
                f"Bundled file differs from canonical source: {member}"
            )

    forbidden_content = {
        str(Path.home()).encode(): "the maintainer home directory",
        str(ROOT).encode(): "the repository path",
    }
    for name, content in files.items():
        for value, description in forbidden_content.items():
            if value and value in content:
                raise ReleaseCheckError(
                    f"{name} contains {description}: {value.decode()}"
                )


def build_artifacts(staged_root: Path, output: Path) -> tuple[Path, Path]:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    _run(
        [
            "uv",
            "build",
            "--no-sources",
            str(staged_root),
            "--out-dir",
            str(output),
        ]
    )

    version = _project_version()
    wheels = list(output.glob(f"otampy-{version}-*.whl"))
    sdists = list(output.glob(f"otampy-{version}.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ReleaseCheckError(
            f"Expected one wheel and one sdist for {version}; found wheels={wheels}, sdists={sdists}"
        )
    return wheels[0], sdists[0]


def smoke_test_install(
    wheel: Path,
    workspace: Path,
    *,
    urst_source: Path | None = None,
) -> None:
    """Install the wheel cleanly and exercise init plus deploy resolution."""
    environment = workspace / "venv"
    project = workspace / "new-project"
    _run(["uv", "venv", "--python", sys.executable, str(environment)])

    if os.name == "nt":
        python = environment / "Scripts" / "python.exe"
        executable = environment / "Scripts" / "otampy.exe"
    else:
        python = environment / "bin" / "python"
        executable = environment / "bin" / "otampy"

    install_command = [
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
    ]
    if urst_source is not None:
        if not (urst_source / "pyproject.toml").is_file():
            raise ReleaseCheckError(
                f"URST source is not a Python project: {urst_source}"
            )
        project_name = _project_name(urst_source)
        if project_name != "urst-mpy":
            raise ReleaseCheckError(
                "--urst-source must point to a local urst-mpy checkout; "
                f"{urst_source} is project {project_name!r}."
            )
        install_command.append(str(urst_source))
        print(
            "Using a local URST source for preflight only; run without --urst-source before publishing OTAmpy.",
            flush=True,
        )
    install_command.append(str(wheel))
    _run(install_command)
    _run([str(executable), "init", "new-project"], cwd=workspace)
    result = _run(
        [
            str(executable),
            "deploy",
            "--device-dir",
            "new-project",
            "--dry-run",
            "--no-mip",
        ],
        cwd=workspace,
        capture=True,
    )

    for name in ("boot.py", "main.py", "configota.py"):
        if not (project / name).is_file():
            raise ReleaseCheckError(f"otampy init did not create {name}")
    if str(ROOT) in result.stdout or str(ROOT) in result.stderr:
        raise ReleaseCheckError(
            "Installed deploy command leaked or used the source repository path."
        )
    if "otampy/device/lib" not in result.stdout:
        raise ReleaseCheckError(
            "Installed deploy command did not use the packaged device library."
        )


def check_release(
    output: Path,
    *,
    allow_dirty: bool = False,
    urst_source: Path | None = None,
) -> None:
    """Run all release checks and leave verified artifacts in *output*."""
    if not allow_dirty:
        _require_clean_worktree()

    _run(["uv", "run", "ruff", "check", "."])
    _run(["uv", "run", "pytest"])

    with tempfile.TemporaryDirectory(prefix="otampy-release-") as temporary:
        workspace = Path(temporary)
        staged_root = stage_package(workspace / "stage")
        wheel, sdist = build_artifacts(staged_root, output)
        inspect_artifact(wheel)
        inspect_artifact(sdist)
        smoke_test_install(
            wheel,
            workspace / "smoke",
            urst_source=urst_source,
        )

    print(f"Release checks passed. Verified artifacts: {output}", flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and verify publishable OTAmpy artifacts."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory for verified wheel and sdist artifacts.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow a dirty worktree (intended only while developing this script).",
    )
    parser.add_argument(
        "--urst-source",
        type=Path,
        help=(
            "Use a local URST checkout for preflight. Omit this for the final "
            "release check so registry dependency resolution is verified."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        urst_source = (
            args.urst_source.expanduser().resolve()
            if args.urst_source is not None
            else None
        )
        check_release(
            args.output_dir.resolve(),
            allow_dirty=args.allow_dirty,
            urst_source=urst_source,
        )
    except ReleaseCheckError as error:
        print(f"Release check failed: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(f"Release check failed: {error}", file=sys.stderr)
        if error.stdout:
            print("--- Subprocess stdout ---", file=sys.stderr)
            print(error.stdout, file=sys.stderr)
        if error.stderr:
            print("--- Subprocess stderr ---", file=sys.stderr)
            print(error.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
