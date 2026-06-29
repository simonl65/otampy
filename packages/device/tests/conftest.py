import importlib.util
import sys
import types
from pathlib import Path


# Mock urst for the device package so imports succeed during loading
class FakeUrst:
    def __init__(self, uart):
        self.uart = uart

    def send(self, data):
        pass

    def receive(self):
        return None


sys.modules["urst"] = types.SimpleNamespace(Urst=FakeUrst)  # pyright: ignore[reportArgumentType]

# Create a virtual package 'device_otampy' to avoid conflict with CLI
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
    # Also set the attribute on the parent package
    setattr(device_otampy, path.stem, sub_mod)
