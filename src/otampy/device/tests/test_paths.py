"""Target-path constraints for CP_START / CAT / RM (F-14).

`CP_START:<target>:…` took the target straight from the command with no
directory restriction and no `..` rejection, so `CP_START:main.py:…`
overwrote device code -- persistent remote code execution.

Two independent rules:

* `..` is **always** rejected. There is no legitimate traversal on a
  MicroPython filesystem, and it is the actual traversal primitive.
* An allowlist is applied only when `OTA_ALLOWED_PATH_PREFIXES` is
  configured, so existing deployments are unaffected by default.
"""

import device_otampy.paths as paths
import pytest
import shared
from device_otampy import manager
from device_otampy.core import OTACore

# --- normalise ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("main.py", "main.py"),
        ("/main.py", "main.py"),  # cwd is / on the device: the same file
        ("./main.py", "main.py"),
        ("lib/robot/x.py", "lib/robot/x.py"),
        ("//lib//robot//x.py", "lib/robot/x.py"),
        ("/logs/ota.log", "logs/ota.log"),
        ("data/", "data"),
    ],
)
def test_normalise_collapses_equivalent_spellings(raw, expected):
    assert paths.normalise(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "../boot.py",
        "../../etc/passwd",
        "lib/../../../boot.py",
        "lib/../boot.py",
        "/../boot.py",
        "..",
        "a/../..",
    ],
)
def test_normalise_rejects_any_traversal_component(raw):
    assert paths.normalise(raw) is None


@pytest.mark.parametrize("raw", ["", "/", ".", "./", None, 42])
def test_normalise_rejects_empty_or_non_string_paths(raw):
    assert paths.normalise(raw) in (None, "")


# --- is_allowed, no allowlist configured --------------------------------


@pytest.mark.parametrize("prefixes", [None, "", (), []])
@pytest.mark.parametrize("path", ["main.py", "lib/robot/x.py", "/logs/ota.log"])
def test_with_no_allowlist_ordinary_paths_are_allowed(path, prefixes):
    # The backward-compatibility guarantee for existing deployments.
    assert paths.is_allowed(path, prefixes) is True


@pytest.mark.parametrize("prefixes", [None, "", ()])
def test_traversal_is_rejected_even_with_no_allowlist(prefixes):
    # F-14's actual fix: the allowlist is opt-in, `..` rejection is not.
    assert paths.is_allowed("../boot.py", prefixes) is False
    assert paths.is_allowed("lib/../../boot.py", prefixes) is False


@pytest.mark.parametrize("path", ["", "/", None, 42, ".."])
def test_an_unusable_path_is_never_allowed(path):
    assert paths.is_allowed(path, None) is False


# --- is_allowed, allowlist configured -----------------------------------


PREFIXES = ("data", "lib/user")


@pytest.mark.parametrize(
    "path",
    [
        "data",
        "data/x.csv",
        "/data/x.csv",
        "data/deep/nested/x",
        "lib/user/m.py",
    ],
)
def test_a_path_inside_an_allowed_prefix_is_allowed(path):
    assert paths.is_allowed(path, PREFIXES) is True


@pytest.mark.parametrize(
    "path",
    ["main.py", "boot.py", "lib/robot/x.py", "logs/ota.log", "configota.py"],
)
def test_a_path_outside_every_prefix_is_rejected(path):
    assert paths.is_allowed(path, PREFIXES) is False


@pytest.mark.parametrize("path", ["database.db", "data-evil.py", "libuser/x"])
def test_a_sibling_that_merely_shares_a_string_prefix_is_rejected(path):
    # The classic startswith() bug: "data" must not admit "database.db".
    assert paths.is_allowed(path, PREFIXES) is False


def test_traversal_out_of_an_allowed_prefix_is_rejected():
    assert paths.is_allowed("data/../main.py", PREFIXES) is False
    assert paths.is_allowed("data/../../boot.py", PREFIXES) is False


def test_prefixes_may_be_a_comma_separated_string():
    # configota.py can hold either a tuple or a plain string.
    assert paths.is_allowed("data/x", "data,lib/user") is True
    assert paths.is_allowed("main.py", "data,lib/user") is False


def test_prefix_spellings_are_normalised_too():
    for prefix in ("/data", "data/", "./data"):
        assert paths.is_allowed("data/x.csv", (prefix,)) is True
        assert paths.is_allowed("main.py", (prefix,)) is False


def test_a_prefix_of_slash_allows_everything_except_traversal():
    assert paths.is_allowed("main.py", ("/",)) is True
    assert paths.is_allowed("../x", ("/",)) is False


# --- enforcement in the commands that take a target path ----------------

FORBIDDEN = b"ERROR:Forbidden path"


def _core(prefixes=None):
    config = {"LOG_LEVEL": "DEBUG"}
    if prefixes is not None:
        config["OTA_ALLOWED_PATH_PREFIXES"] = prefixes
    return OTACore(shared.FakeUART(), config=config, logger=shared.FakeLogger())


def _poll(command, prefixes=None):
    core = _core(prefixes)
    core.transport.incoming_queue.append(command)
    manager.poll(core)
    return core


@pytest.mark.parametrize(
    "command",
    [
        b"CAT:../boot.py",
        b"RM:../boot.py",
        b"CP_START:../boot.py:10:" + b"a" * 64,
        b"CAT:lib/../../boot.py",
        b"RM:a/../..",
    ],
)
def test_traversal_is_refused_with_no_allowlist_configured(command):
    core = _poll(command)
    assert core.transport.sent_messages == [FORBIDDEN]


@pytest.mark.parametrize(
    "command",
    [
        b"CAT:main.py",
        b"RM:main.py",
        b"CP_START:main.py:10:" + b"a" * 64,
        b"CAT:configota.py",
    ],
)
def test_a_path_outside_the_allowlist_is_refused(command):
    core = _poll(command, prefixes=("data",))
    assert core.transport.sent_messages == [FORBIDDEN]


def test_cp_start_refuses_before_opening_any_staging_file(tmp_path):
    # F-14's evidence path: the rejection must land before _make_dirs and
    # open(staging, "wb"), or a refused copy still litters the filesystem.
    target = str(tmp_path / "main.py")
    core = _poll(
        f"CP_START:{target}:10:{'a' * 64}".encode(), prefixes=("data",)
    )
    assert core.transport.sent_messages == [FORBIDDEN]
    assert getattr(core, "_copy_state", None) is None
    assert not (tmp_path / "main.py.cp").exists()


def test_an_allowed_path_still_reaches_its_handler(tmp_path):
    # Not "works" -- reaches the filesystem and fails there, proving the
    # guard let it through rather than short-circuiting.
    core = _poll(b"CAT:data/nope.txt", prefixes=("data",))
    assert core.transport.sent_messages[0].startswith(b"ERROR:")
    assert core.transport.sent_messages[0] != FORBIDDEN


def test_with_no_allowlist_ordinary_commands_are_unaffected():
    core = _poll(b"CAT:does-not-exist.txt")
    assert core.transport.sent_messages[0].startswith(b"ERROR:")
    assert core.transport.sent_messages[0] != FORBIDDEN


def test_ls_is_deliberately_not_constrained():
    # Out of scope for F-14, which is about read/write of a named file.
    # Recorded so the omission is a decision, not an oversight.
    # (LS replies via the fragment path, so sent_messages may be empty.)
    core = _poll(b"LS:.")
    assert FORBIDDEN not in core.transport.sent_messages
