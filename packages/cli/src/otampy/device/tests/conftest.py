import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

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

    def send(self, data):
        self.sent_messages.append(data)

    def read(self):
        if self.incoming_queue:
            return self.incoming_queue.pop(0)
        return None


class FakeProtocol:
    def __init__(self):
        self.sent_fragments = []

    def send_reliable(self, frame_type, payload):
        self.sent_fragments.append((frame_type, bytes(payload)))
        return True


fake_constants = types.SimpleNamespace(
    FRAME_FRAG=0x04,
    MAX_PAYLOAD_SIZE=200,
)
sys.modules["urst"] = types.SimpleNamespace(  # pyright: ignore[reportArgumentType]
    Urst=FakeUrst,
    constants=fake_constants,
)

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

# Load all submodules under 'device_otampy'
for path in PKG_PATH.glob("*.py"):
    if path.name == "__init__.py":
        continue
    mod_name = f"device_otampy.{path.stem}"
    sub_spec = importlib.util.spec_from_file_location(mod_name, path)
    sub_mod = importlib.util.module_from_spec(sub_spec)
    sys.modules[mod_name] = sub_mod
    sub_spec.loader.exec_module(sub_mod)  # pyright: ignore[reportOptionalMemberAccess]
    setattr(device_otampy, path.stem, sub_mod)
