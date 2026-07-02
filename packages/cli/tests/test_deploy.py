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
    mock_args.bytecode = False
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


def test_deploy_installs_only_urst_mip_dependency_by_default():
    args = deploy.DeployArgs(
        port="/dev/ttyACM0",
        mpremote="mpremote",
        no_mip=False,
        with_logger=False,
        no_reset=False,
        dry_run=True,
    )

    command = deploy.deploy_command(args)

    assert "github:simonl65/URST-mpy" in command
    assert not any("log-to-file" in item for item in command)


def test_deploy_installs_optional_logger():
    args = deploy.DeployArgs(
        port="/dev/ttyACM0",
        mpremote="mpremote",
        no_mip=False,
        with_logger=True,
        no_reset=False,
        dry_run=True,
    )

    command = deploy.deploy_command(args)

    assert "github:simonl65/URST-mpy" in command
    assert "github:simonl65/log-to-file" in command


def test_no_mip_skips_optional_logger():
    args = deploy.DeployArgs(
        port="/dev/ttyACM0",
        mpremote="mpremote",
        no_mip=True,
        with_logger=True,
        no_reset=False,
        dry_run=True,
    )

    command = deploy.deploy_command(args)

    assert "mip" not in command
    assert "github:simonl65/log-to-file" not in command


def test_bytecode_command_uses_staged_lib_and_skips_mip(tmp_path):
    args = deploy.DeployArgs(
        port="/dev/ttyACM0",
        mpremote="mpremote",
        no_mip=False,
        with_logger=False,
        no_reset=False,
        dry_run=False,
        bytecode=True,
    )
    staged_lib = tmp_path / "lib"

    command = deploy.deploy_command(args, staged_lib)

    assert str(staged_lib) in command
    assert "mip" not in command
    assert "github:simonl65/URST-mpy" not in command


def test_query_target_mpy_parses_runtime_capabilities():
    args = deploy.DeployArgs(
        port="/dev/ttyACM0",
        mpremote="mpremote",
        no_mip=False,
        with_logger=False,
        no_reset=False,
        dry_run=False,
        bytecode=True,
    )
    result = mock.Mock(
        returncode=0,
        stdout=(
            "unrelated output\n"
            "OTAMPY_MPY|4870|32|MicroPython v1.28.0\n"
        ),
        stderr="",
    )

    with mock.patch("subprocess.run", return_value=result):
        target = deploy.query_target_mpy(args)

    assert target.value == 4870
    assert target.version == 6
    assert target.small_int_bits == 32
    assert target.runtime == "MicroPython v1.28.0"


def test_query_target_mpy_rejects_missing_support():
    args = deploy.DeployArgs(
        port=None,
        mpremote="mpremote",
        no_mip=False,
        with_logger=False,
        no_reset=False,
        dry_run=False,
        bytecode=True,
    )
    result = mock.Mock(
        returncode=0,
        stdout="OTAMPY_MPY|None|32|MicroPython\n",
        stderr="",
    )

    with (
        mock.patch("subprocess.run", return_value=result),
        pytest.raises(deploy.BytecodeDeployError, match="_mpy"),
    ):
        deploy.query_target_mpy(args)


def test_validate_mpy_header_rejects_incompatible_version(tmp_path):
    compiled = tmp_path / "module.mpy"
    compiled.write_bytes(bytes((ord("M"), 5, 0, 32)))
    target = deploy.TargetMpy(
        value=4870,
        small_int_bits=32,
        runtime="MicroPython v1.28.0",
    )

    with pytest.raises(
        deploy.BytecodeDeployError,
        match="target requires version 6",
    ):
        deploy._validate_mpy_header(compiled, target)


def test_validate_mpy_header_rejects_excess_small_int_bits(tmp_path):
    compiled = tmp_path / "module.mpy"
    compiled.write_bytes(bytes((ord("M"), 6, 0, 64)))
    target = deploy.TargetMpy(
        value=4870,
        small_int_bits=32,
        runtime="MicroPython v1.28.0",
    )

    with pytest.raises(
        deploy.BytecodeDeployError,
        match="target supports 32",
    ):
        deploy._validate_mpy_header(compiled, target)


def test_build_bytecode_lib_compiles_otampy_and_urst(tmp_path, monkeypatch):
    source_lib = tmp_path / "source-lib"
    (source_lib / "otampy").mkdir(parents=True)
    (source_lib / "Blink.py").write_text("class Blink: pass\n")
    (source_lib / "otampy" / "__init__.py").write_text("VALUE = 1\n")
    (source_lib / "data.bin").write_bytes(b"asset")

    urst_source = tmp_path / "urst-source"
    urst_source.mkdir()
    (urst_source / "__init__.py").write_text("class Urst: pass\n")

    destination = tmp_path / "build" / "lib"
    target = deploy.TargetMpy(
        value=4870,
        small_int_bits=32,
        runtime="MicroPython v1.28.0",
    )
    args = deploy.DeployArgs(
        port=None,
        mpremote="mpremote",
        no_mip=False,
        with_logger=False,
        no_reset=False,
        dry_run=False,
        bytecode=True,
        mpy_cross="custom-cross --flag",
    )
    calls = []

    def fake_cross(_args, arguments):
        calls.append(arguments)
        if arguments == ["--version"]:
            return mock.Mock(
                returncode=0,
                stdout="mpy-cross emitting mpy v6.3",
                stderr="",
            )
        output = Path(arguments[arguments.index("-o") + 1])
        output.write_bytes(bytes((ord("M"), 6, 0, 32)) + b"payload")
        return mock.Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(deploy, "LIB_DIR", source_lib)
    monkeypatch.setattr(deploy, "_urst_source_dir", lambda: urst_source)
    monkeypatch.setattr(deploy, "_run_mpy_cross", fake_cross)

    count = deploy.build_bytecode_lib(args, destination, target)

    assert count == 3
    assert (destination / "Blink.mpy").is_file()
    assert (destination / "otampy" / "__init__.mpy").is_file()
    assert (destination / "urst" / "__init__.mpy").is_file()
    assert not (destination / "Blink.py").exists()
    assert (destination / "data.bin").read_bytes() == b"asset"
    assert any("/lib/Blink.py" in call for call in calls)
    assert any("/lib/urst/__init__.py" in call for call in calls)


def test_bytecode_deploy_rejects_development_logger():
    args = deploy.DeployArgs(
        port="/dev/ttyACM0",
        mpremote="mpremote",
        no_mip=False,
        with_logger=True,
        no_reset=False,
        dry_run=True,
        bytecode=True,
    )

    with pytest.raises(
        deploy.BytecodeDeployError,
        match="cannot be combined",
    ):
        deploy.deploy(args)


def test_bytecode_deploy_builds_before_destructive_command(monkeypatch):
    args = deploy.DeployArgs(
        port="/dev/ttyACM0",
        mpremote="mpremote",
        no_mip=False,
        with_logger=False,
        no_reset=False,
        dry_run=False,
        bytecode=True,
    )
    target = deploy.TargetMpy(
        value=4870,
        small_int_bits=32,
        runtime="MicroPython v1.28.0",
    )
    calls = []

    def fake_query(_args):
        calls.append("query")
        return target

    def fake_build(_args, lib_dir, received_target):
        assert lib_dir.name == "lib"
        assert received_target is target
        calls.append("build")
        return 12

    def fake_run(_args, command):
        assert "mip" not in command
        assert any("otampy-mpy-" in item for item in command)
        calls.append("deploy")

    monkeypatch.setattr(deploy, "query_target_mpy", fake_query)
    monkeypatch.setattr(deploy, "build_bytecode_lib", fake_build)
    monkeypatch.setattr(deploy, "run_mpremote", fake_run)

    deploy.deploy(args)

    assert calls == ["query", "build", "deploy"]


def test_missing_mpy_cross_has_clear_error():
    args = deploy.DeployArgs(
        port=None,
        mpremote="mpremote",
        no_mip=False,
        with_logger=False,
        no_reset=False,
        dry_run=False,
        bytecode=True,
        mpy_cross="missing-cross",
    )

    with (
        mock.patch("subprocess.run", side_effect=FileNotFoundError),
        pytest.raises(
            deploy.BytecodeDeployError,
            match="Could not find mpy-cross command",
        ),
    ):
        deploy._run_mpy_cross(args, ["--version"])
