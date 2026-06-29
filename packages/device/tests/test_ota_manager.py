import builtins

import machine
from device_otampy import manager  # type: ignore
from device_otampy.core import OTACore  # type: ignore

import shared


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


# =============================================================================
# PHASE 2: FILESYSTEM OPERATION TESTS
# =============================================================================


def test_manager_handles_ls_default(monkeypatch):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"LS")

    def mock_listdir(path="."):
        return ["boot.py", "main.py", "lib"]

    import os
    monkeypatch.setattr(os, "listdir", mock_listdir)

    manager.poll(core)
    assert core.transport.sent_messages == [b"LS_OK:boot.py,main.py,lib"]


def test_manager_handles_ls_path(monkeypatch):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"LS:lib")

    def mock_listdir(path):
        assert path == "lib"
        return ["sensor.py"]

    import os
    monkeypatch.setattr(os, "listdir", mock_listdir)

    manager.poll(core)
    assert core.transport.sent_messages == [b"LS_OK:sensor.py"]


def test_manager_handles_ls_error(monkeypatch):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"LS:nonexistent")

    def mock_listdir(path):
        raise OSError("Directory not found")

    import os
    monkeypatch.setattr(os, "listdir", mock_listdir)

    manager.poll(core)
    assert len(core.transport.sent_messages) == 1
    assert core.transport.sent_messages[0].startswith(b"ERROR:")


def test_manager_handles_cat(monkeypatch):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"CAT:boot.py")

    class MockFile:
        def read(self):
            return "import config"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def mock_open(path, mode="r"):
        assert path == "boot.py"
        assert mode == "r"
        return MockFile()

    monkeypatch.setattr(builtins, "open", mock_open)

    manager.poll(core)
    assert core.transport.sent_messages == [b"CAT_OK:import config"]


def test_manager_handles_cat_error(monkeypatch):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"CAT:missing.py")

    def mock_open(path, mode="r"):
        raise OSError("File not found")

    monkeypatch.setattr(builtins, "open", mock_open)

    manager.poll(core)
    assert len(core.transport.sent_messages) == 1
    assert core.transport.sent_messages[0].startswith(b"ERROR:")


def test_manager_handles_rm(monkeypatch):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"RM:temp.py")

    removed_files = []

    def mock_remove(path):
        removed_files.append(path)

    import os
    monkeypatch.setattr(os, "remove", mock_remove)

    manager.poll(core)
    assert core.transport.sent_messages == [b"RM_OK"]
    assert removed_files == ["temp.py"]


def test_manager_handles_rm_error(monkeypatch):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"RM:system.py")

    def mock_remove(path):
        raise OSError("Permission denied")

    import os
    monkeypatch.setattr(os, "remove", mock_remove)

    manager.poll(core)
    assert len(core.transport.sent_messages) == 1
    assert core.transport.sent_messages[0].startswith(b"ERROR:")
