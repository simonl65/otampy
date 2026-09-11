import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 1. Mock MicroPython specific modules for the testing environment
mock_machine = MagicMock()
sys.modules["machine"] = mock_machine


class FakeUrst:
    def __init__(self, uart):
        self.uart = uart
        self.sent_messages = []
        self.incoming_queue = []
        self._msg_id = 0
        self.protocol = FakeProtocol()
        self.last_request_id = None

    def send(self, data, request_id=None):
        self.sent_messages.append(data)
        return len(data)

    def read(self):
        if self.incoming_queue:
            self.last_request_id = 0
            return self.incoming_queue.pop(0)
        return None

    def reply(self, data):
        if self.last_request_id is None:
            raise RuntimeError(
                "reply() called with nothing received yet to reply to"
            )
        return self.send(data, request_id=self.last_request_id)


class FakeProtocol:
    def __init__(self):
        self.sent_fragments = []
        self.aborted = []
        # Mirrors urst-mpy's ProtocolLayer.session_reset_during_send
        # (US-003): True only when the last failed send_reliable() call
        # was abandoned because a CONNECT reset the peer's session.
        self.session_reset_during_send = False

    def send_reliable(self, frame_type, payload, request_id=0):
        self.sent_fragments.append((frame_type, bytes(payload)))
        return True

    def send_abort(self, message_id, request_id=0, reason_code=0):
        self.aborted.append((message_id, request_id, reason_code))


# mux.py uses the real COBS implementation (it's the thing under test in
# test_mux.py, which asserts identity against it) -- import it before
# sys.modules["urst"] gets replaced below, and pin it under the dotted
# submodule name too so `from urst.codec_layer import ...` resolves
# deterministically regardless of module collection order. `constants` is a
# pure-data module with no I/O -- keep the real one so the double stays
# faithful (pytest imports this conftest during collection, so the fake
# `urst` is visible to the `tests/` suite too, which now reads
# `urst.constants.ACK_TIMEOUT_MS` in cli._fast_recovery_handshake).
import urst.codec_layer as _real_urst_codec_layer  # noqa: E402
import urst.constants as _real_urst_constants  # noqa: E402

sys.modules["urst"] = types.SimpleNamespace(  # pyright: ignore[reportArgumentType]
    Urst=FakeUrst,
    constants=_real_urst_constants,
    codec_layer=_real_urst_codec_layer,
)
sys.modules["urst.codec_layer"] = _real_urst_codec_layer

# 2. Create a virtual package 'device_otampy' to avoid conflict with CLI
LIB_PATH = Path(__file__).resolve().parent.parent / "lib"
PKG_PATH = LIB_PATH / "otampy"

# Create the package module 'device_otampy'
spec = importlib.util.spec_from_file_location(
    "device_otampy", PKG_PATH / "__init__.py"
)
device_otampy = importlib.util.module_from_spec(spec)
sys.modules["device_otampy"] = device_otampy
spec.loader.exec_module(device_otampy)  # pyright: ignore[reportOptionalMemberAccess]

# Load all submodules under 'device_otampy'. `core` first: every other
# submodule does `from .core import ...`, and if `core` hasn't been placed in
# sys.modules yet that resolves through the normal import machinery instead,
# executing core.py a second time and binding the submodule's globals to a
# *different* `core` module instance than the one this loop then registers --
# silently breaking `monkeypatch.setattr`/`patch` against `device_otampy.core`
# for any submodule that imported before `core`'s turn (see TODO.md, F-10).
_submodule_paths = sorted(
    PKG_PATH.glob("*.py"), key=lambda path: (path.name != "core.py", path.name)
)
for path in _submodule_paths:
    if path.name == "__init__.py":
        continue
    mod_name = f"device_otampy.{path.stem}"
    sub_spec = importlib.util.spec_from_file_location(mod_name, path)
    sub_mod = importlib.util.module_from_spec(sub_spec)
    sys.modules[mod_name] = sub_mod
    sub_spec.loader.exec_module(sub_mod)  # pyright: ignore[reportOptionalMemberAccess]
    setattr(device_otampy, path.stem, sub_mod)


@pytest.fixture(autouse=True)
def _restore_device_otampy_submodule_table():
    """Snapshot and restore `sys.modules`/package attrs for `device_otampy`.

    `OTA.boot()` deliberately deletes `device_otampy.boot` (and `restore`,
    `authgate`) from `sys.modules` after each call so main.py never inherits a
    stale copy -- see ota.py. Left unrestored, that leaks across tests: a
    later test's `from device_otampy import boot` (bound once, at module
    import time) still points at the now-orphaned module object, while a
    fresh `device_otampy.boot` gets re-imported underneath it, so
    `patch("device_otampy.boot._resolve_path", ...)` silently patches a
    module nothing under test actually uses. Restoring the table after every
    test -- regardless of which test did the mutating -- makes the suite
    immune to collection order (TODO.md, found 2026-09-09).
    """
    package = sys.modules["device_otampy"]
    prefix = "device_otampy."
    modules_before = {
        name: module
        for name, module in sys.modules.items()
        if name == "device_otampy" or name.startswith(prefix)
    }
    attrs_before = dict(vars(package))

    yield

    for name in list(sys.modules):
        if (
            name == "device_otampy" or name.startswith(prefix)
        ) and name not in modules_before:
            del sys.modules[name]
    sys.modules.update(modules_before)

    for name in list(vars(package)):
        if name not in attrs_before:
            delattr(package, name)
    for name, value in attrs_before.items():
        setattr(package, name, value)
