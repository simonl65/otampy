"""Unit tests for deploy.validate_deploy_sources()."""

from __future__ import annotations

import unittest.mock as mock
from pathlib import Path

import pytest

import otampy.deploy as deploy

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
        mock_path = Path(
            real_path
        )  # keep the real value for relative_to checks
        mock_path = type(  # create a subclass with a patched exists()
            "MockPath",
            (Path,),
            {"exists": lambda self, _exists=exists: _exists},
        )(real_path)
        patches.append(mock.patch.object(deploy, name, mock_path))  # pyright: ignore[reportFunctionMemberAccess]
    return patches


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
            mock.patch.object(deploy, "LIB_DIR", lib_dir),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "CONFIG_FILE", config),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "BOOT_FILE", boot),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "MAIN_FILE", main),  # pyright: ignore[reportFunctionMemberAccess]
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
            mock.patch.object(deploy, "LIB_DIR", tmp_path / "lib"),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "CONFIG_FILE", config),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "BOOT_FILE", boot),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "MAIN_FILE", main),  # pyright: ignore[reportFunctionMemberAccess]
            pytest.raises(SystemExit) as exc_info,
        ):
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
            mock.patch.object(deploy, "ROOT", tmp_path),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "LIB_DIR", lib_dir),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "CONFIG_FILE", tmp_path / "config.py"),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "BOOT_FILE", boot),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "MAIN_FILE", main),  # pyright: ignore[reportFunctionMemberAccess]
            pytest.raises(SystemExit) as exc_info,
        ):
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
            mock.patch.object(deploy, "LIB_DIR", lib_dir),  # type: ignore
            mock.patch.object(deploy, "CONFIG_FILE", config),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "BOOT_FILE", tmp_path / "boot.py"),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "MAIN_FILE", main),  # pyright: ignore[reportFunctionMemberAccess]
            pytest.raises(SystemExit) as exc_info,
        ):
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
            mock.patch.object(deploy, "LIB_DIR", lib_dir),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "CONFIG_FILE", config),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "BOOT_FILE", boot),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "MAIN_FILE", tmp_path / "main.py"),  # pyright: ignore[reportFunctionMemberAccess]
            pytest.raises(SystemExit) as exc_info,
        ):
            deploy.validate_deploy_sources()

        assert exc_info.value.code == 1

    def test_raises_system_exit_when_all_missing(self, tmp_path):
        with (
            mock.patch.object(deploy, "ROOT", tmp_path),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "LIB_DIR", tmp_path / "lib"),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "CONFIG_FILE", tmp_path / "config.py"),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "BOOT_FILE", tmp_path / "boot.py"),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "MAIN_FILE", tmp_path / "main.py"),  # pyright: ignore[reportFunctionMemberAccess]
            pytest.raises(SystemExit) as exc_info,
        ):
            deploy.validate_deploy_sources()

        assert exc_info.value.code == 1


class TestValidateDeploySourcesStderr:
    """validate_deploy_sources() should print informative messages to stderr."""

    def test_prints_missing_paths_to_stderr(self, tmp_path, capsys):
        missing_lib = tmp_path / "lib"

        config = tmp_path / "config.py"
        config.touch()
        boot = tmp_path / "boot.py"
        boot.touch()
        main = tmp_path / "main.py"
        main.touch()

        with (
            mock.patch.object(deploy, "LIB_DIR", missing_lib),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "CONFIG_FILE", config),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "BOOT_FILE", boot),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "MAIN_FILE", main),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "ROOT", tmp_path),  # pyright: ignore[reportFunctionMemberAccess]
            pytest.raises(SystemExit),
        ):
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
            mock.patch.object(deploy, "LIB_DIR", lib_dir),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "CONFIG_FILE", missing_config),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "BOOT_FILE", boot),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "MAIN_FILE", main),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "ROOT", tmp_path),  # pyright: ignore[reportFunctionMemberAccess]
            pytest.raises(SystemExit),
        ):
            deploy.validate_deploy_sources()

        captured = capsys.readouterr()
        assert "config.py" in captured.err
        assert "config.example.py" in captured.err

    def test_no_config_hint_when_only_other_files_missing(
        self, tmp_path, capsys
    ):
        lib_dir = tmp_path / "lib"
        # lib_dir intentionally not created
        config = tmp_path / "config.py"
        config.touch()
        boot = tmp_path / "boot.py"
        boot.touch()
        main = tmp_path / "main.py"
        main.touch()

        with (
            mock.patch.object(deploy, "LIB_DIR", lib_dir),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "CONFIG_FILE", config),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "BOOT_FILE", boot),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "MAIN_FILE", main),  # pyright: ignore[reportFunctionMemberAccess]
            mock.patch.object(deploy, "ROOT", tmp_path),  # pyright: ignore[reportFunctionMemberAccess]
            pytest.raises(SystemExit),
        ):
            deploy.validate_deploy_sources()

        captured = capsys.readouterr()
        # config.py hint should NOT appear when config is not missing
        assert "Create config.py" not in captured.err


def test_remove_pycache_dirs_before_deploy(tmp_path, monkeypatch):
    root = tmp_path
    lib_dir = root / "lib"
    subdir = lib_dir / "package"
    pycache = subdir / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "module.cpython-311.pyc").touch()

    mock_args = mock.Mock()
    mock_args.port = None
    mock_args.mpremote = "mpremote"
    mock_args.no_mip = True
    mock_args.no_reset = True
    mock_args.dry_run = True

    monkeypatch.setattr(deploy, "ROOT", root)
    called = []

    def fake_run_mpremote(args, command):
        called.append((args, command))

    monkeypatch.setattr(deploy, "run_mpremote", fake_run_mpremote)

    deploy.deploy(mock_args)

    assert not pycache.exists()
    assert called, "run_mpremote should be called after cleanup"
