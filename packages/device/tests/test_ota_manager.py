import machine
import shared
from device_otampy import manager  # type: ignore
from device_otampy.core import OTACore  # type: ignore


def test_manager_poll_idle():
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    # Idle poll when there are no incoming packets
    manager.poll(core)
    assert core.transport.sent_messages == []


def test_manager_handles_ping():
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    # Queue PING command
    core.transport.incoming_queue.append(b"PING")

    manager.poll(core)
    assert core.transport.sent_messages == [b"PONG"]


def test_manager_handles_bootloader():
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"BL")

    # Clear mock history
    machine.bootloader.reset_mock()

    manager.poll(core)
    assert core.transport.sent_messages == [b"BL_OK"]
    machine.bootloader.assert_called_once()


def test_manager_handles_reboot():
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"RB")

    machine.reset.reset_mock()

    manager.poll(core)
    assert core.transport.sent_messages == [b"RB_OK"]
    machine.reset.assert_called_once()


def test_manager_handles_soft_reset():
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"SR")

    machine.soft_reset.reset_mock()

    manager.poll(core)
    assert core.transport.sent_messages == [b"SR_OK"]
    machine.soft_reset.assert_called_once()


def test_manager_ignores_unknown_commands():
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"UNKNOWN_XYZ")

    manager.poll(core)
    assert core.transport.sent_messages == []
    assert any("Unknown command" in msg[1] for msg in logger.messages)
