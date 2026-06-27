from shared import FakeLogger, FakeUART, LoadOTAModule


def test_has_uart_interface_accepts_uart_like_object(monkeypatch):
    ota = LoadOTAModule.load_ota_module(monkeypatch)
    manager = ota.OTAManager(FakeUART())

    assert manager._has_uart_interface(FakeUART())


def test_has_uart_interface_rejects_incomplete_object(monkeypatch):
    ota = LoadOTAModule.load_ota_module(monkeypatch)
    manager = ota.OTAManager(FakeUART())

    assert not manager._has_uart_interface(object())


def test_init_uses_provided_uart_when_interface_is_valid(monkeypatch):
    ota = LoadOTAModule.load_ota_module(monkeypatch)
    uart = FakeUART()
    logger = FakeLogger()

    manager = ota.OTAManager(uart, logger=logger)

    assert manager.uart is uart
    assert manager.transport.uart is uart
    assert logger.messages == []
