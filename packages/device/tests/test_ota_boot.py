import binascii
import hashlib

from device_otampy import boot
from device_otampy.core import OTACore

import shared


def test_boot_no_flag_file(tmp_path):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "nonexistent.flag"

    config = {"UPDATE_REQUEST_FLAG_FILE": str(flag_file)}
    core = OTACore(uart, config=config, logger=logger)

    callback_called = False

    def callback():
        nonlocal callback_called
        callback_called = True

    boot.run(core, callback=callback)
    assert not callback_called
    assert (
        "debug",
        "Checking for update request flag file...",
    ) in logger.messages


def test_boot_with_flag_file_runs_callback_and_removes_flag(tmp_path):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "update_requested.flag"
    flag_file.touch()

    config = {"UPDATE_REQUEST_FLAG_FILE": str(flag_file)}
    core = OTACore(uart, config=config, logger=logger)

    callback_called = False

    def callback(flag):
        nonlocal callback_called
        callback_called = True

    boot.run(core, callback=callback)

    assert callback_called
    assert not flag_file.exists()
    assert (
        "debug",
        "Checking for update request flag file...",
    ) in logger.messages
    assert ("debug", f"Update request flag found: {flag_file}") in logger.messages


def test_boot_sends_ready_when_flag_present(tmp_path):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "update_requested.flag"
    flag_file.touch()

    config = {"UPDATE_REQUEST_FLAG_FILE": str(flag_file)}
    core = OTACore(uart, config=config, logger=logger)

    boot.run(core, callback=lambda f: None)

    assert core.transport.sent_messages == [b"READY"]


# =============================================================================
# PHASE 4: ATOMIC CHUNKED FILE TRANSFER SESSION TESTS
# =============================================================================


def test_boot_handles_full_update_session(tmp_path):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "update_requested.flag"
    flag_file.touch()

    # Pre-calculate SHA-256 for test payloads
    payload_main = b"print('hello main')"
    payload_lib = b"print('hello lib')"

    sha_main = hashlib.sha256(payload_main).hexdigest()
    sha_lib = hashlib.sha256(payload_lib).hexdigest()

    # Encode payloads to base64
    b64_main = binascii.b2a_base64(payload_main).strip()
    b64_lib = binascii.b2a_base64(payload_lib).strip()

    # File paths on the simulated device
    target_main = tmp_path / "main.py"
    target_lib = tmp_path / "lib" / "helper.py"

    # Queue full update session command sequence
    # Note: we use absolute paths in test config for flag & targets
    config = {"UPDATE_REQUEST_FLAG_FILE": str(flag_file)}
    core = OTACore(uart, config=config, logger=logger)

    # Mock OS functions inside boot to resolve paths relative to tmp_path
    from unittest.mock import patch

    def mock_resolve_path(path):
        # Prevent double-prepending tmp_path if path is already absolute
        if str(path).startswith(str(tmp_path)):
            return str(path)
        if path.startswith("/"):
            path = path[1:]
        res = tmp_path / path
        # Ensure parent directories exist
        res.parent.mkdir(parents=True, exist_ok=True)
        return str(res)

    # Queue commands
    # 1. Start update manifest: 2 files, 36 bytes total
    core.transport.incoming_queue.append(b"UPDATE_START:2:36")
    # 2. Start main.py transfer
    core.transport.incoming_queue.append(
        f"FILE_START:main.py:19:{sha_main}".encode()
    )
    # 3. Send main.py chunk
    core.transport.incoming_queue.append(f"CHUNK:0:{b64_main.decode()}".encode())
    # 4. Finalize main.py
    core.transport.incoming_queue.append(b"FILE_END")
    # 5. Start lib/helper.py transfer
    core.transport.incoming_queue.append(
        f"FILE_START:lib/helper.py:17:{sha_lib}".encode()
    )
    # 6. Send lib/helper.py chunk
    core.transport.incoming_queue.append(f"CHUNK:0:{b64_lib.decode()}".encode())
    # 7. Finalize lib/helper.py
    core.transport.incoming_queue.append(b"FILE_END")
    # 8. Commit
    core.transport.incoming_queue.append(b"UPDATE_COMMIT")

    # Patch boot loader's file/directory resolver to write relative to tmp_path
    with patch("device_otampy.boot._resolve_path", side_effect=mock_resolve_path, create=True):
        boot.run(core, callback=None)

    # Assert responses sent back to the host CLI
    # READY is sent first, then response for each queued command
    assert core.transport.sent_messages == [
        b"READY",
        b"SPACE_OK",
        b"FILE_OK",
        b"CHUNK_ACK:0",
        b"FILE_OK",
        b"FILE_OK",
        b"CHUNK_ACK:0",
        b"FILE_OK",
        b"COMMIT_OK",
    ]

    # Verify committed target files exist and contain the correct content
    assert target_main.exists()
    assert target_main.read_bytes() == payload_main

    assert target_lib.exists()
    assert target_lib.read_bytes() == payload_lib

    # Verify temporary .xuip staging files have been cleaned up
    assert not (tmp_path / "main.py.xuip").exists()
    assert not (tmp_path / "lib" / "helper.py.xuip").exists()

    # Verify update flag is cleared
    assert not flag_file.exists()
