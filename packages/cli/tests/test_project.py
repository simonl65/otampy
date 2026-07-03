"""Tests for project scaffolding and deployment source discovery."""

from pathlib import Path

import pytest

from otampy import project


def _create_templates(root: Path) -> Path:
    examples = root / "examples"
    examples.mkdir(parents=True)
    (examples / "boot.py").write_text("# boot\n")
    (examples / "main.py").write_text("# main\n")
    (examples / "config.example.py").write_text("# config\n")
    (root / "lib").mkdir()
    return root


def test_initialise_project_copies_project_owned_files(tmp_path, monkeypatch):
    bundle = _create_templates(tmp_path / "bundle")
    destination = tmp_path / "application"
    monkeypatch.setattr(project, "bundled_device_root", lambda: bundle)

    created = project.initialise_project(destination)

    assert created == [
        destination / "device" / "boot.py",
        destination / "device" / "main.py",
        destination / "device" / "config.py",
    ]
    assert (destination / "device" / "config.py").read_text() == "# config\n"
    assert not (destination / "device" / "config.example.py").exists()


def test_initialise_project_refuses_to_overwrite(tmp_path, monkeypatch):
    bundle = _create_templates(tmp_path / "bundle")
    destination = tmp_path / "application"
    existing = destination / "device" / "main.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("user application\n")
    monkeypatch.setattr(project, "bundled_device_root", lambda: bundle)

    with pytest.raises(project.ProjectError, match="Refusing to overwrite"):
        project.initialise_project(destination)

    assert existing.read_text() == "user application\n"
    assert not (destination / "device" / "boot.py").exists()


def test_initialise_project_force_replaces_files(tmp_path, monkeypatch):
    bundle = _create_templates(tmp_path / "bundle")
    destination = tmp_path / "application"
    existing = destination / "device" / "main.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("old\n")
    monkeypatch.setattr(project, "bundled_device_root", lambda: bundle)

    project.initialise_project(destination, force=True)

    assert existing.read_text() == "# main\n"


def test_resolve_device_sources_uses_bundle_for_new_project(
    tmp_path, monkeypatch
):
    bundle = _create_templates(tmp_path / "bundle")
    application = tmp_path / "application"
    monkeypatch.setattr(project, "bundled_device_root", lambda: bundle)

    sources = project.resolve_device_sources(application)

    assert sources.lib_dir == bundle / "lib"
    assert sources.boot_file == application / "device" / "boot.py"
    assert sources.main_file == application / "device" / "main.py"
    assert sources.config_file == application / "device" / "config.py"


def test_resolve_device_sources_uses_repository_tree(tmp_path):
    device = tmp_path / "packages" / "device"
    (device / "examples").mkdir(parents=True)
    (device / "lib").mkdir()

    sources = project.resolve_device_sources(tmp_path)

    assert sources.device_root == device
    assert sources.lib_dir == device / "lib"
    assert sources.config_file == device / "examples" / "config.py"
