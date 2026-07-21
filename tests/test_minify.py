from __future__ import annotations

from pathlib import Path

import otampy.deploy as deploy
from otampy.minify import minify_python_source, staged_minified_files


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
