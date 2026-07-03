"""Project scaffolding and device deployment source discovery."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

PROJECT_DEVICE_DIRECTORY = "device"
BUNDLED_DEVICE_DIRECTORY = "_device"


class ProjectError(Exception):
    """Raised when an OTAmpy project cannot be created or resolved."""


@dataclass(frozen=True)
class DeviceSources:
    """Files used to construct a complete device deployment."""

    project_root: Path
    device_root: Path
    lib_dir: Path
    config_file: Path
    boot_file: Path
    main_file: Path
    config_example_file: Path


def _package_directory() -> Path:
    return Path(__file__).resolve().parent


def _repository_device_root() -> Path | None:
    """Return the canonical device tree when running from a source checkout."""
    package_directory = _package_directory()
    for parent in (package_directory, *package_directory.parents):
        candidate = parent / "packages" / "device"
        if candidate.is_dir():
            return candidate
    return None


def bundled_device_root() -> Path:
    """Return the release bundle or source-checkout device tree."""
    bundled = _package_directory() / BUNDLED_DEVICE_DIRECTORY
    if bundled.is_dir():
        return bundled

    repository = _repository_device_root()
    if repository is not None:
        return repository

    return bundled


def resolve_device_sources(project_root: Path) -> DeviceSources:
    """Resolve library and application sources for *project_root*."""
    project_root = project_root.expanduser().resolve()
    repository_device = project_root / "packages" / "device"

    if repository_device.is_dir():
        device_root = repository_device
        examples = device_root / "examples"
        lib_dir = device_root / "lib"
    else:
        device_root = project_root / PROJECT_DEVICE_DIRECTORY
        examples = device_root
        lib_dir = bundled_device_root() / "lib"

    return DeviceSources(
        project_root=project_root,  # type: ignore
        device_root=device_root,  # type: ignore
        lib_dir=lib_dir,  # type: ignore
        config_file=examples / "config.py",  # type: ignore
        boot_file=examples / "boot.py",  # type: ignore
        main_file=examples / "main.py",  # type: ignore
        config_example_file=examples / "config.example.py",  # type: ignore
    )


def initialise_project(
    project_root: Path, *, force: bool = False
) -> list[Path]:
    """Create project-owned device files from the packaged templates."""
    project_root = project_root.expanduser().resolve()
    destination = project_root / PROJECT_DEVICE_DIRECTORY
    template_root = bundled_device_root() / "examples"
    templates = {
        template_root / "boot.py": destination / "boot.py",
        template_root / "main.py": destination / "main.py",
        template_root / "config.example.py": destination / "config.py",
    }

    missing = [source for source in templates if not source.is_file()]
    if missing:
        paths = ", ".join(str(path) for path in missing)
        raise ProjectError(f"Missing packaged device template(s): {paths}")

    existing = [target for target in templates.values() if target.exists()]
    if existing and not force:
        paths = ", ".join(str(path) for path in existing)
        raise ProjectError(
            f"Refusing to overwrite existing project file(s): {paths}. "
            "Use --force to replace them."
        )

    destination.mkdir(parents=True, exist_ok=True)
    for source, target in templates.items():
        shutil.copy2(source, target)

    return list(templates.values())
