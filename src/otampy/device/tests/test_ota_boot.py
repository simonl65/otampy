import binascii
import hashlib
import os
from unittest.mock import patch

import shared
from device_otampy import boot
from device_otampy.core import OTACore


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
    assert core._transport is None
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
    assert (
        "debug",
        "Update request flag FOUND",
    ) in logger.messages


def test_boot_sends_ready_when_flag_present(tmp_path):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "update_requested.flag"
    flag_file.touch()

    config = {"UPDATE_REQUEST_FLAG_FILE": str(flag_file)}
    core = OTACore(uart, config=config, logger=logger)

    boot.run(core, callback=lambda f: None)

    assert core.transport.sent_messages == [b"READY"]


def test_boot_handles_full_update_session(tmp_path):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "update_requested.flag"
    flag_file.touch()

    payload_main = b"print('hello main')"
    payload_lib = b"print('hello lib')"

    sha_main = hashlib.sha256(payload_main).hexdigest()
    sha_lib = hashlib.sha256(payload_lib).hexdigest()

    b64_main = binascii.b2a_base64(payload_main).strip()
    b64_lib = binascii.b2a_base64(payload_lib).strip()

    target_main = tmp_path / "main.py"
    target_lib = tmp_path / "lib" / "helper.py"

    config = {"UPDATE_REQUEST_FLAG_FILE": str(flag_file)}
    core = OTACore(uart, config=config, logger=logger)

    from unittest.mock import patch

    def mock_resolve_path(path):
        if str(path).startswith(str(tmp_path)):
            return str(path)
        if path.startswith("/"):
            path = path[1:]
        res = tmp_path / path
        res.parent.mkdir(parents=True, exist_ok=True)
        return str(res)

    core.transport.incoming_queue.append(b"UPDATE_START:2:37")
    core.transport.incoming_queue.append(
        f"FILE_START:main.py:19:{sha_main}".encode()
    )
    core.transport.incoming_queue.append(
        f"CHUNK:0:{b64_main.decode()}".encode()
    )
    core.transport.incoming_queue.append(b"FILE_END")
    core.transport.incoming_queue.append(
        f"FILE_START:lib/helper.py:17:{sha_lib}".encode()
    )
    core.transport.incoming_queue.append(f"CHUNK:0:{b64_lib.decode()}".encode())
    core.transport.incoming_queue.append(b"FILE_END")
    core.transport.incoming_queue.append(b"UPDATE_COMMIT")

    with patch(
        "device_otampy.boot._resolve_path",
        side_effect=mock_resolve_path,
        create=True,
    ):
        boot.run(core, callback=None)

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

    assert target_main.exists()
    assert target_main.read_bytes() == payload_main

    assert target_lib.exists()
    assert target_lib.read_bytes() == payload_lib

    assert not (tmp_path / "main.py.ota").exists()
    assert not (tmp_path / "lib" / "helper.py.ota").exists()
    assert not flag_file.exists()


def test_boot_aborts_active_update_and_cleans_staging(tmp_path):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "update_requested.flag"
    flag_file.touch()
    target = tmp_path / "main.py"
    staging = tmp_path / "main.py.ota"
    orphaned_staging = tmp_path / "lib" / "stale.py.ota"
    orphaned_staging.parent.mkdir()
    orphaned_staging.touch()
    checksum = hashlib.sha256(b"replacement").hexdigest()

    config = {"UPDATE_REQUEST_FLAG_FILE": str(flag_file)}
    core = OTACore(uart, config=config, logger=logger)
    core.transport.incoming_queue.extend(
        [
            f"FILE_START:{target}:11:{checksum}".encode(),
            b"UPDATE_ABORT",
        ]
    )

    def mock_resolve_path(path):
        if str(path).startswith(str(tmp_path)):
            return str(path)
        if path == ".":
            return str(tmp_path)
        return str(tmp_path / path.lstrip("./"))

    with (
        patch(
            "device_otampy.boot._resolve_path",
            side_effect=mock_resolve_path,
        ),
        patch("device_otampy.boot._os.listdir", side_effect=os.listdir),
        patch("device_otampy.boot._os.remove", side_effect=os.remove),
        patch("device_otampy.boot._os.stat", side_effect=os.stat),
    ):
        boot.run(core)

    assert core.transport.sent_messages == [
        b"READY",
        b"FILE_OK",
        b"UPDATE_ABORTED",
    ]
    assert not staging.exists()
    assert not orphaned_staging.exists()
    assert not flag_file.exists()


def test_boot_times_out_interrupted_update_and_cleans_staging(
    tmp_path, monkeypatch
):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "update_requested.flag"
    flag_file.touch()
    target = tmp_path / "main.py"
    staging = tmp_path / "main.py.ota"
    checksum = hashlib.sha256(b"replacement").hexdigest()

    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(flag_file),
        "OTA_TIMEOUT_MS": 1,
    }
    core = OTACore(uart, config=config, logger=logger)
    core.transport.incoming_queue.append(
        f"FILE_START:{target}:11:{checksum}".encode()
    )
    ticks = iter((0, 0, 2))
    monkeypatch.setattr(boot, "_ticks_ms", lambda: next(ticks))

    boot.run(core)

    assert core.transport.sent_messages == [
        b"READY",
        b"FILE_OK",
        b"UPDATE_ABORTED",
    ]
    assert not flag_file.exists()
    assert not staging.exists()
    assert ("warning", "OTA update timed out; aborting session") in logger.messages


# =============================================================================
# PHASE 5: FAULT-TOLERANCE & CLEANUP TESTS
# =============================================================================


def test_boot_cleans_orphaned_ota_on_normal_boot(tmp_path):
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "nonexistent.flag"

    # Set up staging files on simulated disk
    orphaned_main = tmp_path / "main.py.ota"
    orphaned_main.touch()

    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    orphaned_lib = lib_dir / "sensor.py.ota"
    orphaned_lib.touch()

    # Create a real source file that should NOT be deleted
    valid_source = tmp_path / "boot.py"
    valid_source.touch()

    config = {"UPDATE_REQUEST_FLAG_FILE": str(flag_file)}
    core = OTACore(uart, config=config, logger=logger)

    from unittest.mock import patch

    def mock_resolve_path(path):
        if str(path).startswith(str(tmp_path)):
            return str(path)
        if path.startswith("/"):
            path = path[1:]
        return str(tmp_path / path)

    # Patch resolver and listdir to work on tmp_path
    import os

    with (
        patch(
            "device_otampy.boot._resolve_path",
            side_effect=mock_resolve_path,
            create=True,
        ),
        patch("device_otampy.boot._os.listdir", side_effect=os.listdir),
        patch("device_otampy.boot._os.remove", side_effect=os.remove),
        patch("device_otampy.boot._os.stat", side_effect=os.stat),
    ):
        boot.run(core, callback=None)

    # Staging files should be cleaned up
    assert not orphaned_main.exists()
    assert not orphaned_lib.exists()

    # Valid files must be kept
    assert valid_source.exists()
