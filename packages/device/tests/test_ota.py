import importlib.util
import sys
import types
from pathlib import Path


def load_ota_module(monkeypatch):
    class FakeUrst:
        def __init__(self, uart):
            self.uart = uart

    monkeypatch.setitem(
        sys.modules, "urst", types.SimpleNamespace(Urst=FakeUrst)
    )

    module_path = (
        Path(__file__).resolve().parents[1] / "lib" / "otampy" / "ota.py"
    )
    spec = importlib.util.spec_from_file_location("device_ota", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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

    def warning(self, msg):
        self.messages.append(("warning", msg))


def test_has_uart_interface_accepts_uart_like_object(monkeypatch):
    ota = load_ota_module(monkeypatch)
    manager = ota.OTAManager(FakeUART())

    assert manager._has_uart_interface(FakeUART())


def test_has_uart_interface_rejects_incomplete_object(monkeypatch):
    ota = load_ota_module(monkeypatch)
    manager = ota.OTAManager(FakeUART())

    assert not manager._has_uart_interface(object())


def test_init_uses_provided_uart_when_interface_is_valid(monkeypatch):
    ota = load_ota_module(monkeypatch)
    uart = FakeUART()
    logger = FakeLogger()

    manager = ota.OTAManager(uart, logger=logger)

    assert manager.uart is uart
    assert manager.transport.uart is uart
    assert logger.messages == []


def test_init_uses_mock_uart_when_interface_is_invalid(monkeypatch):
    ota = load_ota_module(monkeypatch)
    logger = FakeLogger()

    manager = ota.OTAManager(object(), logger=logger)

    assert isinstance(manager.uart, ota._MockUART)
    assert manager.transport.uart is manager.uart
    assert logger.messages == [
        (
            "warning",
            "UART object is not available or does not provide the expected interface.",
        ),
        ("debug", "Falling back to a mock/simulated serial for demonstration."),
    ]


def test_init_sets_default_config(monkeypatch):
    ota = load_ota_module(monkeypatch)

    manager = ota.OTAManager(FakeUART())

    assert manager.config == {
        "LOG_LEVEL": "DEBUG",
        "LOG_FILE": "/logs/ota.log",
    }


def test_check_for_update_logs_check(monkeypatch):
    ota = load_ota_module(monkeypatch)
    logger = FakeLogger()
    manager = ota.OTAManager(FakeUART(), logger=logger)

    manager.check_for_update(callback=None)

    assert logger.messages == [
        ("debug", "Checking for update request flag file...")
    ]
