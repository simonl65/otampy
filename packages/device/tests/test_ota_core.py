import pytest
import shared
from device_otampy.core import OTACore, UartRequiredError


def test_core_init_uses_provided_uart():
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)
    assert core.uart is uart
    assert core.logger is logger
    assert core.transport is not None


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
