import builtins

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


def test_manager_handles_reboot():
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"RB")

    machine.reset.reset_mock()

    manager.poll(core)
    assert core.transport.sent_messages == [b"RB_OK"]
    machine.reset.assert_called_once()
    assert any(
        level == "info" and "RB" in msg for level, msg in logger.messages
    ), "Expected a shutdown reason log message before RB reset"


def test_manager_handles_soft_reset():
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"SR")

    machine.soft_reset.reset_mock()

    manager.poll(core)
    assert core.transport.sent_messages == [b"SR_OK"]
    machine.soft_reset.assert_called_once()
    assert any(
        level == "info" and "SR" in msg for level, msg in logger.messages
    ), "Expected a shutdown reason log message before SR reset"


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

    original_stat = os.stat

    def mock_stat(path, *args, **kwargs):
        path_str = str(path)
        if path_str.endswith("lib") or path_str.endswith("lib/"):
            return os.stat_result((0x4000, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        if any(path_str.endswith(f) for f in ("boot.py", "main.py")):
            return os.stat_result((0x8000, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "listdir", mock_listdir)
    monkeypatch.setattr(os, "stat", mock_stat)

    manager.poll(core)
    assert core.transport.sent_messages == [b"LS_OK:boot.py,main.py,lib/"]


def test_manager_handles_ls_path(monkeypatch):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"LS:lib")

    def mock_listdir(path):
        assert path == "lib"
        return ["sensor.py", "subfolder"]

    import os

    original_stat = os.stat

    def mock_stat(path, *args, **kwargs):
        path_str = str(path)
        if path_str.endswith("subfolder") or path_str.endswith("subfolder/"):
            return os.stat_result((0x4000, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        if path_str.endswith("sensor.py"):
            return os.stat_result((0x8000, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "listdir", mock_listdir)
    monkeypatch.setattr(os, "stat", mock_stat)

    manager.poll(core)
    assert core.transport.sent_messages == [b"LS_OK:sensor.py,subfolder/"]


def test_manager_handles_ls_file(monkeypatch):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"LS:lib/Boot.py")

    import os

    original_stat = os.stat

    def mock_stat(path, *args, **kwargs):
        path_str = str(path)
        if path_str.endswith("lib/Boot.py") or path_str == "lib/Boot.py":
            return os.stat_result((0x8000, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", mock_stat)

    manager.poll(core)
    assert core.transport.sent_messages == [b"LS_OK:Boot.py"]


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
        def read(self, _size):
            if self.exhausted:
                return b""
            self.exhausted = True
            return b"import config"

        def __enter__(self):
            self.exhausted = False
            return self

        def __exit__(self, *args):
            pass

    def mock_open(path, mode="r"):
        assert path == "boot.py"
        assert mode == "rb"
        return MockFile()

    import os

    monkeypatch.setattr(builtins, "open", mock_open)
    monkeypatch.setattr(
        os,
        "stat",
        lambda _path: os.stat_result(
            (0x8000, 0, 0, 0, 0, 0, len(b"import config"), 0, 0, 0)
        ),
    )

    manager.poll(core)
    assert core.transport.sent_messages == [b"CAT_OK:import config"]


def _reassemble_fragments(transport):
    fragments = transport.protocol.sent_fragments
    assert fragments
    message_id = fragments[0][1][0]
    total = fragments[0][1][2]
    assert len(fragments) == total

    payload = bytearray()
    for index, (frame_type, fragment) in enumerate(fragments):
        assert frame_type == 0x04
        assert fragment[0] == message_id
        assert fragment[1] == index
        assert fragment[2] == total
        assert fragment[3] == len(fragment[4:])
        assert len(fragment[4:]) <= 194
        payload.extend(fragment[4:])
    return bytes(payload)


def test_manager_streams_large_cat_without_full_transport_message(tmp_path):
    content = b"x" * (16 * 1024)
    source = tmp_path / "large.txt"
    source.write_bytes(content)
    core = OTACore(shared.FakeUART(), logger=shared.FakeLogger())
    core.transport.incoming_queue.append(f"CAT:{source}".encode())

    manager.poll(core)

    assert core.transport.sent_messages == []
    assert _reassemble_fragments(core.transport) == b"CAT_OK:" + content


def test_manager_streams_large_directory_without_full_transport_message(
    tmp_path,
):
    directory = tmp_path / "many"
    directory.mkdir()
    expected = set()
    for index in range(64):
        name = f"file-{index:02d}.txt"
        (directory / name).touch()
        expected.add(name.encode())
    core = OTACore(shared.FakeUART(), logger=shared.FakeLogger())
    core.transport.incoming_queue.append(f"LS:{directory}".encode())

    manager.poll(core)

    assert core.transport.sent_messages == []
    response = _reassemble_fragments(core.transport)
    assert response.startswith(b"LS_OK:")
    assert set(response[6:].split(b",")) == expected


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


def test_manager_handles_cat_directory(monkeypatch):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"CAT:lib")

    import os

    original_stat = os.stat

    def mock_stat(path, *args, **kwargs):
        path_str = str(path)
        if path_str.endswith("lib") or path_str == "lib":
            return os.stat_result(
                (0x4000, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            )  # S_IFDIR
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", mock_stat)

    manager.poll(core)
    assert core.transport.sent_messages == [b"ERROR:EISDIR"]


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


def test_manager_handles_empty_directory_rm(monkeypatch):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"RM:empty")
    removed_directories = []

    def mock_remove(_path):
        raise OSError("Is a directory")

    def mock_rmdir(path):
        removed_directories.append(path)

    import os

    monkeypatch.setattr(os, "remove", mock_remove)
    monkeypatch.setattr(os, "stat", lambda _path: (0x4000,))
    monkeypatch.setattr(os, "rmdir", mock_rmdir)

    manager.poll(core)
    assert core.transport.sent_messages == [b"RM_OK"]
    assert removed_directories == ["empty"]


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


def _poll_message(core, message):
    core.transport.incoming_queue.append(message)
    manager.poll(core)
    return core.transport.sent_messages[-1]


def test_manager_streams_and_commits_copy(tmp_path):
    import binascii
    import hashlib

    core = OTACore(shared.FakeUART(), logger=shared.FakeLogger())
    target = tmp_path / "lib" / "copied.bin"
    content = bytes(range(256)) + b"tail"
    digest = hashlib.sha256(content).hexdigest()

    response = _poll_message(
        core,
        f"CP_START:{target}:{len(content)}:{digest}".encode(),
    )
    assert response == b"CP_READY"

    for sequence, offset in enumerate(range(0, len(content), 128)):
        encoded = binascii.b2a_base64(content[offset : offset + 128]).strip()
        response = _poll_message(
            core,
            b"CP_CHUNK:" + str(sequence).encode() + b":" + encoded,
        )
        assert response == f"CP_ACK:{sequence}".encode()

    assert _poll_message(core, b"CP_END") == b"CP_OK"
    assert target.read_bytes() == content
    assert not target.with_name("copied.bin.cp").exists()
    assert not hasattr(core, "_copy_state")


def test_manager_copy_checksum_failure_preserves_target(tmp_path):
    import binascii

    core = OTACore(shared.FakeUART(), logger=shared.FakeLogger())
    target = tmp_path / "main.py"
    target.write_bytes(b"original")
    content = b"replacement"

    assert (
        _poll_message(
            core,
            f"CP_START:{target}:{len(content)}:{'0' * 64}".encode(),
        )
        == b"CP_READY"
    )
    encoded = binascii.b2a_base64(content).strip()
    assert _poll_message(core, b"CP_CHUNK:0:" + encoded) == b"CP_ACK:0"

    assert _poll_message(core, b"CP_END").startswith(b"ERROR:")
    assert target.read_bytes() == b"original"
    assert not target.with_name("main.py.cp").exists()
    assert not hasattr(core, "_copy_state")


def test_manager_copy_rejects_out_of_sequence_chunk(tmp_path):
    import binascii
    import hashlib

    core = OTACore(shared.FakeUART(), logger=shared.FakeLogger())
    target = tmp_path / "copy.py"
    content = b"content"
    digest = hashlib.sha256(content).hexdigest()

    assert (
        _poll_message(
            core,
            f"CP_START:{target}:{len(content)}:{digest}".encode(),
        )
        == b"CP_READY"
    )
    encoded = binascii.b2a_base64(content).strip()

    assert _poll_message(core, b"CP_CHUNK:1:" + encoded).startswith(b"ERROR:")
    assert not target.exists()
    assert not target.with_name("copy.py.cp").exists()
    assert not hasattr(core, "_copy_state")


def test_manager_aborts_active_copy(tmp_path):
    import hashlib

    core = OTACore(shared.FakeUART(), logger=shared.FakeLogger())
    target = tmp_path / "copy.py"
    digest = hashlib.sha256(b"content").hexdigest()

    assert (
        _poll_message(
            core,
            f"CP_START:{target}:7:{digest}".encode(),
        )
        == b"CP_READY"
    )

    assert _poll_message(core, b"CP_ABORT") == b"CP_ABORTED"
    assert not target.with_name("copy.py.cp").exists()
    assert not hasattr(core, "_copy_state")


# =============================================================================
# PHASE 3: UPDATE REQUEST HANDSHAKE TESTS
# =============================================================================


def test_manager_handles_update_request_without_callback(tmp_path):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "update_requested.flag"

    config = {"UPDATE_REQUEST_FLAG_FILE": str(flag_file)}
    core = OTACore(uart, config=config, logger=logger)

    core.transport.incoming_queue.append(b"UPDATE_REQUEST")

    machine.reset.reset_mock()

    manager.poll(core)

    assert core.transport.sent_messages == [b"REBOOTING"]
    assert flag_file.exists()
    machine.reset.assert_called_once()
    assert any(
        level == "info" and "update" in msg.lower()
        for level, msg in logger.messages
    ), "Expected a shutdown reason log message before UPDATE_REQUEST reset"


def test_manager_handles_update_request_with_callback(tmp_path):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "update_requested.flag"

    config = {"UPDATE_REQUEST_FLAG_FILE": str(flag_file)}
    core = OTACore(uart, config=config, logger=logger)

    core.transport.incoming_queue.append(b"UPDATE_REQUEST")

    machine.reset.reset_mock()

    callback_called = False

    def safe_callback():
        nonlocal callback_called
        callback_called = True

    manager.poll(core, callback=safe_callback)

    assert callback_called
    assert core.transport.sent_messages == [b"REBOOTING"]
    assert flag_file.exists()
    machine.reset.assert_called_once()
    assert any(
        level == "info" and "update" in msg.lower()
        for level, msg in logger.messages
    ), "Expected a shutdown reason log message before UPDATE_REQUEST reset"


def test_manager_handles_mem(monkeypatch):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    core.transport.incoming_queue.append(b"MEM")

    import gc
    import os

    monkeypatch.setattr(gc, "mem_free", lambda: 50000, raising=False)
    monkeypatch.setattr(gc, "mem_alloc", lambda: 30000, raising=False)

    def mock_statvfs(path):
        assert path == "/"
        return (4096, 4096, 256, 128, 128, 0, 0, 0, 0, 0)

    monkeypatch.setattr(os, "statvfs", mock_statvfs, raising=False)

    manager.poll(core)

    assert core.transport.sent_messages == [
        b"MEM_OK:50000,30000,524288,1048576"
    ]
