"""Unit tests for deploy.validate_deploy_sources()."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import deploy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_sources(exist_flags: dict[str, bool]):
    """Return a context manager that patches each deploy source path.

    *exist_flags* maps the name of the module-level constant (e.g. ``"LIB_DIR"``)
    to whether ``Path.exists()`` should return ``True`` or ``False``.
    """
    patches = []
    for name, exists in exist_flags.items():
        real_path: Path = getattr(deploy, name)
        mock_path = Path(real_path)  # keep the real value for relative_to checks
        mock_path = type(  # create a subclass with a patched exists()
            "MockPath",
            (Path,),
            {"exists": lambda self, _exists=exists: _exists},
        )(real_path)
        patches.append(patch.object(deploy, name, mock_path))
    return patches


def _all_exist():
    return {name: True for name in ("LIB_DIR", "CONFIG_FILE", "BOOT_FILE", "MAIN_FILE")}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestValidateDeploySourcesAllPresent:
    """validate_deploy_sources() should return None when every source exists."""

    def test_returns_none_when_all_sources_exist(self, tmp_path):
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        config = tmp_path / "config.py"
        config.touch()
        boot = tmp_path / "boot.py"
        boot.touch()
        main = tmp_path / "main.py"
        main.touch()

        with (
            patch.object(deploy, "LIB_DIR", lib_dir),
            patch.object(deploy, "CONFIG_FILE", config),
            patch.object(deploy, "BOOT_FILE", boot),
            patch.object(deploy, "MAIN_FILE", main),
        ):
            result = deploy.validate_deploy_sources()

        assert result is None


class TestValidateDeploySourcesMissing:
    """validate_deploy_sources() should exit with code 1 when sources are missing."""

    def test_raises_system_exit_when_lib_dir_missing(self, tmp_path):
        config = tmp_path / "config.py"
        config.touch()
        boot = tmp_path / "boot.py"
        boot.touch()
        main = tmp_path / "main.py"
        main.touch()

        with (
            patch.object(deploy, "LIB_DIR", tmp_path / "lib"),  # does not exist
            patch.object(deploy, "CONFIG_FILE", config),
            patch.object(deploy, "BOOT_FILE", boot),
            patch.object(deploy, "MAIN_FILE", main),
        ):
            with pytest.raises(SystemExit) as exc_info:
                deploy.validate_deploy_sources()

        assert exc_info.value.code == 1

    def test_raises_system_exit_when_config_missing(self, tmp_path):
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        boot = tmp_path / "boot.py"
        boot.touch()
        main = tmp_path / "main.py"
        main.touch()

        with (
            patch.object(deploy, "ROOT", tmp_path),
            patch.object(deploy, "LIB_DIR", lib_dir),
            patch.object(deploy, "CONFIG_FILE", tmp_path / "config.py"),  # missing
            patch.object(deploy, "BOOT_FILE", boot),
            patch.object(deploy, "MAIN_FILE", main),
        ):
            with pytest.raises(SystemExit) as exc_info:
                deploy.validate_deploy_sources()

        assert exc_info.value.code == 1

    def test_raises_system_exit_when_boot_missing(self, tmp_path):
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        config = tmp_path / "config.py"
        config.touch()
        main = tmp_path / "main.py"
        main.touch()

        with (
            patch.object(deploy, "LIB_DIR", lib_dir),
            patch.object(deploy, "CONFIG_FILE", config),
            patch.object(deploy, "BOOT_FILE", tmp_path / "boot.py"),  # missing
            patch.object(deploy, "MAIN_FILE", main),
        ):
            with pytest.raises(SystemExit) as exc_info:
                deploy.validate_deploy_sources()

        assert exc_info.value.code == 1

    def test_raises_system_exit_when_main_missing(self, tmp_path):
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        config = tmp_path / "config.py"
        config.touch()
        boot = tmp_path / "boot.py"
        boot.touch()

        with (
            patch.object(deploy, "LIB_DIR", lib_dir),
            patch.object(deploy, "CONFIG_FILE", config),
            patch.object(deploy, "BOOT_FILE", boot),
            patch.object(deploy, "MAIN_FILE", tmp_path / "main.py"),  # missing
        ):
            with pytest.raises(SystemExit) as exc_info:
                deploy.validate_deploy_sources()

        assert exc_info.value.code == 1

    def test_raises_system_exit_when_all_missing(self, tmp_path):
        with (
            patch.object(deploy, "ROOT", tmp_path),
            patch.object(deploy, "LIB_DIR", tmp_path / "lib"),
            patch.object(deploy, "CONFIG_FILE", tmp_path / "config.py"),
            patch.object(deploy, "BOOT_FILE", tmp_path / "boot.py"),
            patch.object(deploy, "MAIN_FILE", tmp_path / "main.py"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                deploy.validate_deploy_sources()

        assert exc_info.value.code == 1


class TestValidateDeploySourcesStderr:
    """validate_deploy_sources() should print informative messages to stderr."""

    def test_prints_missing_paths_to_stderr(self, tmp_path, capsys):
        missing_lib = tmp_path / "lib"

        lib_dir = tmp_path / "lib"
        config = tmp_path / "config.py"
        config.touch()
        boot = tmp_path / "boot.py"
        boot.touch()
        main = tmp_path / "main.py"
        main.touch()

        with (
            patch.object(deploy, "LIB_DIR", missing_lib),
            patch.object(deploy, "CONFIG_FILE", config),
            patch.object(deploy, "BOOT_FILE", boot),
            patch.object(deploy, "MAIN_FILE", main),
            patch.object(deploy, "ROOT", tmp_path),
        ):
            with pytest.raises(SystemExit):
                deploy.validate_deploy_sources()

        captured = capsys.readouterr()
        assert "Error: missing deploy source(s):" in captured.err
        assert "lib" in captured.err

    def test_prints_config_hint_when_config_missing(self, tmp_path, capsys):
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        missing_config = tmp_path / "config.py"
        boot = tmp_path / "boot.py"
        boot.touch()
        main = tmp_path / "main.py"
        main.touch()
        # config.example.py must exist for the hint path to render
        example = tmp_path / "config.example.py"
        example.touch()

        with (
            patch.object(deploy, "LIB_DIR", lib_dir),
            patch.object(deploy, "CONFIG_FILE", missing_config),
            patch.object(deploy, "BOOT_FILE", boot),
            patch.object(deploy, "MAIN_FILE", main),
            patch.object(deploy, "ROOT", tmp_path),
        ):
            with pytest.raises(SystemExit):
                deploy.validate_deploy_sources()

        captured = capsys.readouterr()
        assert "config.py" in captured.err
        assert "config.example.py" in captured.err

    def test_no_config_hint_when_only_other_files_missing(self, tmp_path, capsys):
        lib_dir = tmp_path / "lib"
        # lib_dir intentionally not created
        config = tmp_path / "config.py"
        config.touch()
        boot = tmp_path / "boot.py"
        boot.touch()
        main = tmp_path / "main.py"
        main.touch()

        with (
            patch.object(deploy, "LIB_DIR", lib_dir),
            patch.object(deploy, "CONFIG_FILE", config),
            patch.object(deploy, "BOOT_FILE", boot),
            patch.object(deploy, "MAIN_FILE", main),
            patch.object(deploy, "ROOT", tmp_path),
        ):
            with pytest.raises(SystemExit):
                deploy.validate_deploy_sources()

        captured = capsys.readouterr()
        # config.py hint should NOT appear when config is not missing
        assert "Create config.py" not in captured.err
