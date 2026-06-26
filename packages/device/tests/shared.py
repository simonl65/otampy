import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock


class LoadOTAModule:
    @staticmethod
    def load_ota_module(monkeypatch):
        class FakeUrst:
            def __init__(self, uart):
                self.uart = uart

        monkeypatch.setitem(
            sys.modules, "urst", types.SimpleNamespace(Urst=FakeUrst)
        )

        module_path = (
            Path(__file__).resolve().parents[1] / "lib" / "otampy" / "ota.py"  # type: ignore
        )
        spec = importlib.util.spec_from_file_location("device_ota", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        return module


class FakeUART:
    def write(self, data):
        return len(data)

    def read(self, n):
        return b""

    def any(self):
        return 0


class FakeLogger:
    def __init__(self):
        self.messages = []

    def debug(self, msg):
        self.messages.append(("debug", msg))

    def info(self, msg):
        self.messages.append(("info", msg))

    def warning(self, msg):
        self.messages.append(("warning", msg))

    def error(self, msg):
        self.messages.append(("error", msg))

    def critical(self, msg):
        self.messages.append(("critical", msg))


fake_config = {
    "LOG_LEVEL": "DEBUG",
    "LOG_FILE": "/ota.log",
    "UPDATE_REQUEST_FLAG_FILE": "update_requested.flag",
}


class Manager:
    @staticmethod
    def setup_manager(monkeypatch, uart=None, config=None, logger=None):
        ota = LoadOTAModule.load_ota_module(monkeypatch)
        if uart is None:
            uart = FakeUART()
        manager = ota.OTAManager(uart=uart, config=config, logger=logger)
        return manager
