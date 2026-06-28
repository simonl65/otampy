import pytest
from shared import FakeLogger, FakeUART, LoadOTAModule


def test_init_uses_provided_uart(monkeypatch):
    ota = LoadOTAModule.load(monkeypatch)
    uart = FakeUART()
    logger = FakeLogger()

    manager = ota.OTAManager(uart, logger=logger)

    assert manager.uart is uart
    assert manager.transport.uart is uart
    assert logger.messages == []


def test_init_errors_when_no_uart_provided(monkeypatch):
    ota = LoadOTAModule.load(monkeypatch)
    logger = FakeLogger()
    uart = None
    UartRequiredError = ota.UartRequiredError

    with pytest.raises(UartRequiredError, match="Must provide a UART object"):
        ota.OTAManager(uart, logger=logger)
    assert ("critical", "Must provide a UART object") in logger.messages
