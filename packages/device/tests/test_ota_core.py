from unittest.mock import patch

import pytest
from device_otampy.core import OTACore, UartRequiredError

import shared


def test_core_init_uses_provided_uart():
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)
    assert core.uart is uart
    assert core.logger is logger
    assert core._transport is None


def test_core_creates_transport_once_on_first_access():
    uart = shared.FakeUART()
    transport = object()

    with patch("urst.Urst", return_value=transport) as factory:
        core = OTACore(uart)

        factory.assert_not_called()
        assert core.transport is transport
        assert core.transport is transport

    factory.assert_called_once_with(uart)


def test_core_allows_transport_injection_without_importing_urst():
    uart = shared.FakeUART()
    transport = object()

    with patch("urst.Urst") as factory:
        core = OTACore(uart)
        core.transport = transport

        assert core.transport is transport
        factory.assert_not_called()


def test_core_init_errors_when_no_uart_provided():
    logger = shared.FakeLogger()
    with pytest.raises(UartRequiredError, match="Must provide a UART object"):
        OTACore(None, logger=logger)
    assert ("critical", "Must provide a UART object") in logger.messages


def test_core_default_config():
    uart = shared.FakeUART()
    core = OTACore(uart)
    assert core.config["LOG_LEVEL"] == "DEBUG"
    assert core.config["LOG_FILE"] == "/logs/ota.log"
    assert core.config["UPDATE_REQUEST_FLAG_FILE"] == "update_requested.flag"


def test_core_normalizes_module_like_config():
    class ConfigModule:
        UPDATE_REQUEST_FLAG_FILE = "update_requested.flag"
        LOG_LEVEL = "DEBUG"
        LOG_FILE = "/logs/ota.log"

    uart = shared.FakeUART()
    core = OTACore(uart, config=ConfigModule)

    assert core.config["UPDATE_REQUEST_FLAG_FILE"] == "update_requested.flag"
    assert core.config["LOG_LEVEL"] == "DEBUG"
    assert core.config["LOG_FILE"] == "/logs/ota.log"
    assert (
        core.config.get("UPDATE_REQUEST_FLAG_FILE") == "update_requested.flag"
    )
