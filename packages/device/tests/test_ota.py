import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest


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


def setup_manager(monkeypatch, uart=None, config=None, logger=None):
    ota = load_ota_module(monkeypatch)
    manager = ota.OTAManager(uart=FakeUART(), config=config, logger=logger)
    return manager


class TestUart:
    def test_has_uart_interface_accepts_uart_like_object(self, monkeypatch):
        ota = load_ota_module(monkeypatch)
        manager = ota.OTAManager(FakeUART())

        assert manager._has_uart_interface(FakeUART())

    def test_has_uart_interface_rejects_incomplete_object(self, monkeypatch):
        ota = load_ota_module(monkeypatch)
        manager = ota.OTAManager(FakeUART())

        assert not manager._has_uart_interface(object())

    def test_init_uses_provided_uart_when_interface_is_valid(self, monkeypatch):
        ota = load_ota_module(monkeypatch)
        uart = FakeUART()
        logger = FakeLogger()

        manager = ota.OTAManager(uart, logger=logger)

        assert manager.uart is uart
        assert manager.transport.uart is uart
        assert logger.messages == []

    def test_init_uses_mock_uart_when_interface_is_invalid(self, monkeypatch):
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
            (
                "debug",
                "Falling back to a mock/simulated serial for demonstration.",
            ),
        ]


class TestBootTime:
    def test__do_we_have_update_flag__returns_true(self, monkeypatch):
        # TODO: Implement test test_do_we_have_update_flag_yes
        pass

    def test__check_for_update_file__logs_flag_found(
        self, monkeypatch, tmp_path
    ):
        logger = FakeLogger()
        manager = setup_manager(monkeypatch, logger=logger)

        # Create a temporary flag file
        flag_file = tmp_path / "update_requested.flag"
        flag_file.write_text("")
        manager.config["UPDATE_REQUEST_FLAG_FILE"] = str(flag_file)

        manager.check_for_update_file(callback=None)

        assert (
            "debug",
            f"Update request flag found: {flag_file}",
        ) in logger.messages

    def test__check_for_update_flag__returns_false_if_flag_not_found(
        self, monkeypatch, tmp_path
    ):
        logger = FakeLogger()
        manager = setup_manager(monkeypatch, logger=logger)
        flag_file = tmp_path / "update_requested.flag"
        manager.config["UPDATE_REQUEST_FLAG_FILE"] = str(flag_file)

        manager.check_for_update_file(callback=None)

        assert (
            "debug",
            f"Update request flag found: {flag_file}",
        ) not in logger.messages


class TestRunTime:
    # @pytest.mark.skip("TODO: Implement test__check_for_update")
    def test__check_for_update(self, monkeypatch):
        logger = FakeLogger()
        manager = setup_manager(monkeypatch, logger=logger)
        callback = Mock()

        manager.check_for_update(callback)

        # callback.assert_called_once()

    def test_init_sets_default_config(self, monkeypatch):
        ota = load_ota_module(monkeypatch)

        manager = ota.OTAManager(FakeUART())

        assert manager.config == {
            "LOG_LEVEL": "DEBUG",
            "LOG_FILE": "/logs/ota.log",
            "UPDATE_REQUEST_FLAG_FILE": "update_requested.flag",
        }

    def test_config_is_passed_in(self, monkeypatch):
        ota = load_ota_module(monkeypatch)
        logger = FakeLogger()
        uart = FakeUART()
        manager = ota.OTAManager(uart, config=fake_config, logger=logger)

        assert (
            manager.config["UPDATE_REQUEST_FLAG_FILE"]
            == "update_requested.flag"
        )
        assert manager.logger is logger
        assert manager.uart is uart

    def test_missing_config_takes_defaults(self, monkeypatch):
        ota = load_ota_module(monkeypatch)
        logger = FakeLogger()
        uart = FakeUART()
        manager = ota.OTAManager(uart, logger=logger)

        assert manager.config == {
            "LOG_LEVEL": "DEBUG",
            "LOG_FILE": "/logs/ota.log",
            "UPDATE_REQUEST_FLAG_FILE": "update_requested.flag",
        }
