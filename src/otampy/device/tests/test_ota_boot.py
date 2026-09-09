import binascii
import builtins
import hashlib
import os
from unittest.mock import patch

import machine
import shared
from device_otampy import boot, restore
from device_otampy.core import OTACore


def _no_flag_core(tmp_path, uart=None, logger=None):
    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(tmp_path / "nonexistent.flag"),
        "OTA_JOURNAL_FILE": str(tmp_path / "otampy-update.journal"),
    }
    return OTACore(
        uart or shared.FakeUART(),
        config=config,
        logger=logger or shared.FakeLogger(),
    )


def test_boot_trial_rollback_restores_set_and_resets(tmp_path):
    """No flag, trial journal at the limit -> whole set back, machine.reset()."""
    machine.reset.reset_mock()
    main = tmp_path / "main.py"
    main.write_bytes(b"bad-candidate")
    (tmp_path / "main.py.bck").write_bytes(b"previous-good")
    core = _no_flag_core(tmp_path)
    core.config["OTA_TRIAL_BOOTS"] = 3
    restore.write_journal(core, 3, [str(main)])

    boot.run(core, callback=None)

    assert main.read_bytes() == b"previous-good"
    assert not (tmp_path / "otampy-update.journal").exists()
    machine.reset.assert_called_once()


def test_boot_trial_counts_without_reset(tmp_path):
    machine.reset.reset_mock()
    main = tmp_path / "main.py"
    main.write_bytes(b"candidate")
    (tmp_path / "main.py.bck").write_bytes(b"previous-good")
    core = _no_flag_core(tmp_path)
    core.config["OTA_TRIAL_BOOTS"] = 3
    restore.write_journal(core, 0, [str(main)])

    boot.run(core, callback=None)

    assert restore.read_journal(core) == (1, restore._STATE_TRIAL, [str(main)])
    assert main.read_bytes() == b"candidate"
    machine.reset.assert_not_called()


def test_boot_confirmed_journal_untouched_no_reset(tmp_path):
    machine.reset.reset_mock()
    main = tmp_path / "main.py"
    main.write_bytes(b"candidate")
    (tmp_path / "main.py.bck").write_bytes(b"previous-good")
    core = _no_flag_core(tmp_path)
    restore.write_journal(core, restore._STATE_CONFIRMED, [str(main)])

    boot.run(core, callback=None)

    assert restore.read_journal(core) == (
        0,
        restore._STATE_CONFIRMED,
        [str(main)],
    )
    machine.reset.assert_not_called()


def test_boot_imports_staged_rtc_helper(monkeypatch):
    imported = []

    def fake_import(name, *args, **kwargs):
        imported.append(name)
        if name == "_otampy_set_rtc":
            return object()
        return builtins.__import__(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    boot._apply_staged_rtc_update()

    assert imported == ["_otampy_set_rtc"]


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
        "Checking for update flag-file...",
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
        "Checking for update flag-file...",
    ) in logger.messages
    assert (
        "debug",
        "FOUND update flag-file",
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
    target_lib.parent.mkdir()
    target_main.write_bytes(b"OLD main")
    target_lib.write_bytes(b"OLD helper")
    journal = tmp_path / "otampy-update.journal"

    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(flag_file),
        "OTA_JOURNAL_FILE": str(journal),
    }
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

    # Retain-previous: each target's pre-update content survives as <target>.bck
    # and the journal records the committed set.
    assert (tmp_path / "main.py.bck").read_bytes() == b"OLD main"
    assert (tmp_path / "lib" / "helper.py.bck").read_bytes() == b"OLD helper"
    assert restore.read_journal(core) == (
        0,
        restore._STATE_TRIAL,
        [str(target_main), str(target_lib)],
    )


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
    interrupted_staging = tmp_path / "boot.py.ota"
    interrupted_staging.touch()
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

    def mock_resolve_path(path):
        if str(path).startswith(str(tmp_path)):
            return str(path)
        return str(tmp_path / path.lstrip("./"))

    monkeypatch.setattr(boot, "_resolve_path", mock_resolve_path)

    boot.run(core)

    assert core.transport.sent_messages == [
        b"READY",
        b"FILE_OK",
        b"UPDATE_ABORTED",
    ]
    assert not flag_file.exists()
    assert not staging.exists()
    assert not interrupted_staging.exists()
    assert (
        "warning",
        "OTA update timed out; aborting session",
    ) in logger.messages


# =============================================================================
# PHASE 5: FAULT-TOLERANCE & CLEANUP TESTS
# =============================================================================


def test_update_start_clears_prior_generation(tmp_path):
    """A pre-existing journal + .bck from a past update is gone after
    UPDATE_START is processed."""
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "update_requested.flag"
    flag_file.touch()
    journal = tmp_path / "otampy-update.journal"
    old_backup = tmp_path / "main.py.bck"
    old_backup.write_bytes(b"previous-generation")

    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(flag_file),
        "OTA_JOURNAL_FILE": str(journal),
        "OTA_TIMEOUT_MS": 1,
    }
    core = OTACore(uart, config=config, logger=logger)
    restore.write_journal(core, 0, [str(tmp_path / "main.py")])

    core.transport.incoming_queue.append(b"UPDATE_START:1:10")
    ticks = iter((0, 0, 5, 5))
    with patch.object(boot, "_ticks_ms", side_effect=lambda: next(ticks)):
        boot.run(core, callback=None)

    assert not journal.exists()
    assert not old_backup.exists()
    assert b"SPACE_OK" in core.transport.sent_messages


def test_boot_repairs_finished_commit_with_missing_target(tmp_path):
    """No flag, journal line 1 is 0, a target vanished -> repair restores it."""
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "nonexistent.flag"
    main = tmp_path / "main.py"
    (tmp_path / "main.py.bck").write_bytes(b"good-main")

    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(flag_file),
        "OTA_JOURNAL_FILE": str(tmp_path / "otampy-update.journal"),
    }
    core = OTACore(uart, config=config, logger=logger)
    restore.write_journal(core, 0, [str(main)])

    boot.run(core, callback=None)

    assert main.read_bytes() == b"good-main"


def test_boot_reverses_interrupted_commit(tmp_path):
    """No flag, journal line 1 'committing' -> whole set restored, line 1 -> 0."""
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "nonexistent.flag"
    main = tmp_path / "main.py"
    sensor = tmp_path / "sensor.py"
    main.write_bytes(b"half-new")
    (tmp_path / "main.py.bck").write_bytes(b"good-main")
    (tmp_path / "sensor.py.bck").write_bytes(b"good-sensor")

    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(flag_file),
        "OTA_JOURNAL_FILE": str(tmp_path / "otampy-update.journal"),
    }
    core = OTACore(uart, config=config, logger=logger)
    restore.write_journal(
        core, restore._STATE_COMMITTING, [str(main), str(sensor)]
    )

    boot.run(core, callback=None)

    assert main.read_bytes() == b"good-main"
    assert sensor.read_bytes() == b"good-sensor"
    # restore_all() removes the journal outright once the set is back.
    assert restore.read_journal(core)[1] == restore._STATE_CONFIRMED


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


def test_commit_does_not_retain_the_transient_rtc_helper(tmp_path):
    """F-05. `_otampy_set_rtc.py` ships in the manifest but is a one-shot helper
    that self-deletes on the next boot. commit() must place it, not back it up
    or journal it — otherwise repair() resurrects it from .bck the boot after."""
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "update_requested.flag"
    flag_file.touch()

    payload_main = b"print('new main')"
    payload_rtc = b"import machine  # one-shot"
    sha_main = hashlib.sha256(payload_main).hexdigest()
    sha_rtc = hashlib.sha256(payload_rtc).hexdigest()
    b64_main = binascii.b2a_base64(payload_main).strip().decode()
    b64_rtc = binascii.b2a_base64(payload_rtc).strip().decode()

    target_main = tmp_path / "main.py"
    target_main.write_bytes(b"OLD main")
    journal = tmp_path / "otampy-update.journal"

    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(flag_file),
        "OTA_JOURNAL_FILE": str(journal),
    }
    core = OTACore(uart, config=config, logger=logger)

    def mock_resolve_path(path):
        if str(path).startswith(str(tmp_path)):
            return str(path)
        return str(tmp_path / path.lstrip("/"))

    core.transport.incoming_queue.extend(
        [
            b"UPDATE_START:2:40",
            f"FILE_START:main.py:17:{sha_main}".encode(),
            f"CHUNK:0:{b64_main}".encode(),
            b"FILE_END",
            f"FILE_START:_otampy_set_rtc.py:24:{sha_rtc}".encode(),
            f"CHUNK:0:{b64_rtc}".encode(),
            b"FILE_END",
            b"UPDATE_COMMIT",
        ]
    )

    with patch(
        "device_otampy.boot._resolve_path", side_effect=mock_resolve_path
    ):
        boot.run(core, callback=None)

    assert core.transport.sent_messages[-1] == b"COMMIT_OK"
    # Helper placed so it runs once...
    assert (tmp_path / "_otampy_set_rtc.py").read_bytes() == payload_rtc
    # ...but never retained or journalled.
    assert not (tmp_path / "_otampy_set_rtc.py.bck").exists()
    assert restore.read_journal(core) == (
        0,
        restore._STATE_TRIAL,
        [str(target_main)],
    )
    # The real target still got its backup.
    assert (tmp_path / "main.py.bck").read_bytes() == b"OLD main"


def test_boot_removes_orphan_bck_but_keeps_journalled_one(tmp_path):
    """Normal boot: a .bck not in the journal is an orphan and goes; a .bck
    the journal still references is kept."""
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "nonexistent.flag"
    journal = tmp_path / "otampy-update.journal"

    orphan_bck = tmp_path / "stale.py.bck"
    orphan_bck.touch()
    kept_target = tmp_path / "keep.py"
    kept_bck = tmp_path / "keep.py.bck"
    kept_target.write_bytes(b"live")
    kept_bck.write_bytes(b"previous")

    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(flag_file),
        "OTA_JOURNAL_FILE": str(journal),
    }
    core = OTACore(uart, config=config, logger=logger)
    restore.write_journal(core, 0, [str(kept_target)])

    def mock_resolve_path(path):
        if str(path).startswith(str(tmp_path)):
            return str(path)
        if path.startswith("/"):
            path = path[1:]
        return str(tmp_path / path)

    with (
        patch(
            "device_otampy.boot._resolve_path",
            side_effect=mock_resolve_path,
        ),
        patch("device_otampy.boot._os.listdir", side_effect=os.listdir),
        patch("device_otampy.boot._os.remove", side_effect=os.remove),
        patch("device_otampy.boot._os.stat", side_effect=os.stat),
    ):
        boot.run(core, callback=None)

    assert not orphan_bck.exists()
    assert kept_bck.exists()


def test_cleanup_keeps_journalled_bck_with_real_resolve_path(tmp_path):
    """F-04 regression. `_cleanup_orphaned_ota` must compare candidates in the
    same `/dir/file` form the journal stores. This test does NOT patch
    `_resolve_path`, so the `.`-vs-`/` prefix mismatch that deleted
    `/./main.py.bck` on the device is actually exercised (on the host the real
    resolver is identity for relative paths, which is enough to expose it)."""
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    journal = tmp_path / "otampy-update.journal"
    config = {"OTA_JOURNAL_FILE": str(journal)}
    core = OTACore(uart, config=config, logger=logger)
    restore.write_journal(core, 0, ["/main.py"])

    # Virtual root: main.py + its journalled backup + an un-journalled orphan.
    entries = {"main.py", "main.py.bck", "stale.py.bck"}
    removed = []

    def fake_listdir(p):
        if p in ("/", ".", ""):
            return sorted(entries)
        raise OSError("not a dir")

    def fake_stat(p):
        return (0o100644, 0, 0, 0, 0, 0, 10, 0, 0, 0)  # regular file

    with (
        patch("device_otampy.boot._os.listdir", side_effect=fake_listdir),
        patch("device_otampy.boot._os.stat", side_effect=fake_stat),
        patch("device_otampy.boot._os.remove", side_effect=removed.append),
    ):
        boot._cleanup_orphaned_ota(core)

    assert not any(r.endswith("main.py.bck") for r in removed), removed
    assert any(r.endswith("stale.py.bck") for r in removed), removed
