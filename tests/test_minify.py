from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import otampy.deploy as deploy
from otampy.minify import minify_python_source, staged_minified_files

DEPLOYED_ROOTS = (deploy.LIB_DIR, deploy.DEVICE_ROOT / "examples")

needs_mpy_cross = pytest.mark.skipif(
    shutil.which("mpy-cross") is None,
    reason="mpy-cross is not installed",
)


def _compile_with_mpy_cross(source: bytes, tmp_path: Path, name: str) -> None:
    """Compile *source* with mpy-cross, failing the test on a compile error."""
    candidate = tmp_path / name
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(source)
    result = subprocess.run(
        ["mpy-cross", str(candidate)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{name}: {result.stderr.strip()}"


def test_minify_python_source_preserves_execution_and_docstrings():
    source = b'''# module comment\n\n"""kept documentation"""\n\ndef add(left, right):  # useful comment\n    return left + right\n\nvalue = "# not a comment"\n'''

    minified = minify_python_source(source)
    namespace: dict[str, object] = {}
    exec(minified, namespace)

    assert b"module comment" not in minified
    assert b"useful comment" not in minified
    assert namespace["__doc__"] == "kept documentation"
    assert namespace["add"](2, 3) == 5  # type: ignore[operator]
    assert namespace["value"] == "# not a comment"


def test_minify_python_source_preserves_fstring_conversions():
    source = (
        b"value = (2026, 9, 13)\n"
        b'rendered = f" machine.RTC().datetime({value!r})\\n"\n'
        b'padded = f"{value!s:>40}"\n'
        b"nested = f\"{f'{value!a}'}\"\n"
    )

    minified = minify_python_source(source)
    namespace: dict[str, object] = {}
    exec(minified, namespace)

    assert b"!r }" not in minified
    assert b"{value !r" not in minified
    assert namespace["rendered"] == " machine.RTC().datetime((2026, 9, 13))\n"
    assert namespace["padded"] == f"{(2026, 9, 13)!s:>40}"
    assert namespace["nested"] == f"{(2026, 9, 13)!a}"


@needs_mpy_cross
def test_minified_device_sources_compile_for_micropython(tmp_path):
    sources = [
        (root, source)
        for root in DEPLOYED_ROOTS
        for source in sorted(root.rglob("*.py"))
    ]
    assert sources, f"no device sources found under {DEPLOYED_ROOTS}"

    for root, source in sources:
        relative = source.relative_to(root.parent)
        _compile_with_mpy_cross(
            minify_python_source(source.read_bytes()), tmp_path, str(relative)
        )


def test_staged_minified_files_keeps_original_source_unchanged(tmp_path):
    source = tmp_path / "main.py"
    original = b"# comment\nprint('hello')\n"
    source.write_bytes(original)

    with staged_minified_files([("main.py", source)]) as staged:
        assert staged[0][0] == "main.py"
        assert staged[0][1] != source
        assert b"comment" not in staged[0][1].read_bytes()

    assert source.read_bytes() == original


def test_minified_deploy_uses_temporary_sources(tmp_path, monkeypatch):
    lib = tmp_path / "package-lib"
    lib.mkdir()
    module = lib / "module.py"
    module.write_text("# library comment\nvalue = 1\n")
    device = tmp_path / "device"
    device.mkdir()
    for name in ("configota.py", "main.py", "boot.py"):
        (device / name).write_text(f"# {name} comment\nprint({name!r})\n")

    args = deploy.DeployArgs(
        port=None,
        mpremote="mpremote",
        no_mip=True,
        with_logger=False,
        no_reset=True,
        no_rtc=True,
        dry_run=True,
        minify=True,
        device_dir=device,
    )
    commands: list[list[str]] = []

    def capture(_args, command):
        commands.append(command)
        copied_paths = [Path(item) for item in command if item.endswith(".py")]
        assert copied_paths
        assert all(b"comment" not in path.read_bytes() for path in copied_paths)

    monkeypatch.setattr(deploy, "_find_package_lib_dir", lambda: lib)
    monkeypatch.setattr(deploy, "run_mpremote", capture)

    deploy.deploy(args)

    assert commands
    copied_paths = [Path(item) for item in commands[0] if item.endswith(".py")]
    assert [path.name for path in copied_paths] == [
        "configota.py",
        "main.py",
        "boot.py",
    ]
    assert b"comment" in module.read_bytes()
    assert b"comment" in (device / "main.py").read_bytes()


def test_minified_bytecode_deploy_is_rejected(tmp_path, monkeypatch):
    args = deploy.DeployArgs(
        port=None,
        mpremote="mpremote",
        no_mip=True,
        with_logger=False,
        no_reset=True,
        no_rtc=True,
        dry_run=True,
        bytecode=True,
        minify=True,
    )
    monkeypatch.setattr(deploy, "validate_deploy_sources", lambda _args: None)

    try:
        deploy.deploy(args)
    except deploy.DeployOptionError as error:
        assert "cannot be combined" in str(error)
    else:
        raise AssertionError("expected --minify --bytecode to be rejected")
