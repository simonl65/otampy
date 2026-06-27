from unittest.mock import Mock

import pytest
from shared import FakeLogger, FakeUART, LoadOTAModule, Manager, fake_config


def test_config_is_passed_in(monkeypatch):
    ota = LoadOTAModule.load_ota_module(monkeypatch)
    logger = FakeLogger()
    uart = FakeUART()
    manager = ota.OTAManager(uart, config=fake_config, logger=logger)

    assert manager.config == fake_config
    assert manager.logger is logger
    assert manager.uart is uart


def test_missing_config_takes_defaults(monkeypatch):
    ota = LoadOTAModule.load_ota_module(monkeypatch)
    logger = FakeLogger()
    uart = FakeUART()
    manager = ota.OTAManager(uart, logger=logger)

    assert manager.config == {
        "LOG_LEVEL": "DEBUG",
        "LOG_FILE": "/logs/ota.log",
        "UPDATE_REQUEST_FLAG_FILE": "update_requested.flag",
    }


@pytest.mark.skip("TODO: Implement test__check_for_update")
def test__check_for_update(monkeypatch):
    logger = FakeLogger()
    manager = Manager.setup_manager(monkeypatch, logger=logger)
    callback = Mock()

    manager.check_for_update(callback)

    # callback.assert_called_once()
