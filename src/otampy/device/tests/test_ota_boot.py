import binascii
import builtins
import hashlib
import itertools
import os
from unittest.mock import patch

import device_otampy.auth as device_auth
import machine
import pytest
import shared
from device_otampy import boot, restore
from device_otampy.core import OTACore


@pytest.fixture(autouse=True)
def _boot_mark_in_tmp(tmp_path, monkeypatch):
    """Keep the default boot marker out of the repo root.

    Almost every config in this file omits OTA_BOOT_MARK_FILE, so run() would
    otherwise write `otampy-boot.mark` into the working directory on each of
    them. Redirecting the default -- rather than adding the key to fifteen
    inline configs -- keeps the default path itself under test.

    Patched on the resolver's own globals, not on an imported `core` module:
    conftest glob-loads the submodules in arbitrary order, so `boot`'s
    `from .core import ...` can bind to a `device_otampy.core` instance that
    the loop later replaces in sys.modules. Setting the attribute on the
    module this file imports would land on the wrong instance.
    """
    monkeypatch.setitem(
        boot._boot_mark_path.__globals__,
        "_DEFAULT_BOOT_MARK_FILE",
        str(tmp_path / "otampy-boot.mark"),
    )


def _no_flag_core(tmp_path, uart=None, logger=None):
    # OTA_BOOT_LISTEN_MS = 0 disables the boot-time recovery window. These
    # tests cover the rest of a no-flag boot, and an open window would make
    # each of them really wait it out. The window has its own tests below.
    #
    # The recovery key must be > 0 or no marker is written at all, so it is
    # 1ms rather than 0: any test here whose journal is unproven, or that has
    # a marker from a previous boot, now selects the *wide* window, and at
    # the 8000ms default that is a real 8s wait per test.
    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(tmp_path / "nonexistent.flag"),
        "OTA_JOURNAL_FILE": str(tmp_path / "otampy-update.journal"),
        "OTA_BOOT_LISTEN_MS": 0,
        "OTA_BOOT_RECOVERY_LISTEN_MS": 1,
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
    """With the window disabled, a no-flag boot still touches no transport."""
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    flag_file = tmp_path / "nonexistent.flag"

    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(flag_file),
        "OTA_BOOT_LISTEN_MS": 0,
        "OTA_BOOT_RECOVERY_LISTEN_MS": 0,
    }
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


def test_boot_no_flag_opens_the_transport_for_the_window(tmp_path):
    """An open window necessarily costs one transport instantiation.

    The lazy-transport guarantee above only survives with the window off:
    listening requires a transport. Pinned as a test so the cost is a
    recorded decision rather than a surprise.
    """
    uart = shared.FakeUART()
    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(tmp_path / "nonexistent.flag"),
        "OTA_JOURNAL_FILE": str(tmp_path / "otampy-update.journal"),
        "OTA_BOOT_LISTEN_MS": 20,
    }
    core = OTACore(uart, config=config, logger=shared.FakeLogger())

    boot.run(core, callback=None)

    assert core._transport is not None
    assert core.transport.sent_messages == []


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
        "OTA_BOOT_LISTEN_MS": 0,
        "OTA_BOOT_RECOVERY_LISTEN_MS": 0,
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
        "OTA_BOOT_LISTEN_MS": 0,
        "OTA_BOOT_RECOVERY_LISTEN_MS": 0,
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
        "OTA_BOOT_LISTEN_MS": 0,
        "OTA_BOOT_RECOVERY_LISTEN_MS": 0,
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

    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(flag_file),
        "OTA_BOOT_LISTEN_MS": 0,
        "OTA_BOOT_RECOVERY_LISTEN_MS": 0,
    }
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
        "OTA_BOOT_LISTEN_MS": 0,
        "OTA_BOOT_RECOVERY_LISTEN_MS": 0,
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
        "OTA_BOOT_LISTEN_MS": 0,
        "OTA_BOOT_RECOVERY_LISTEN_MS": 0,
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


# =============================================================================
# The boot marker
#
# Its presence at boot means the *previous* boot never reached OTA.poll().
# run() writes it once per boot, only when absent, after trial() and before
# the flag lookup. Nothing reads it yet -- step 3 selects the window from it.
# See docs/development/failsafe-update-window-reachability-spec.md.
# =============================================================================


def _mark(tmp_path):
    return tmp_path / "otampy-boot.mark"


def test_boot_writes_marker_when_absent(tmp_path):
    core = _no_flag_core(tmp_path)

    boot.run(core, callback=None)

    assert _mark(tmp_path).exists()


def test_boot_leaves_an_existing_marker_untouched(tmp_path):
    """A stranded device in a boot loop does zero writes -- flash wear."""
    _mark(tmp_path).write_bytes(b"previous-boot")
    core = _no_flag_core(tmp_path)

    boot.run(core, callback=None)

    assert _mark(tmp_path).read_bytes() == b"previous-boot"


def test_boot_writes_marker_on_the_flagged_update_path(tmp_path):
    """Written before the flag lookup, so an update boot is marked too."""
    flag = tmp_path / "update_requested.flag"
    flag.write_text("1")
    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(flag),
        "OTA_JOURNAL_FILE": str(tmp_path / "otampy-update.journal"),
        "OTA_BOOT_LISTEN_MS": 0,
        "OTA_BOOT_RECOVERY_LISTEN_MS": 1,
    }
    core = OTACore(shared.FakeUART(), config=config, logger=shared.FakeLogger())

    boot.run(core, callback=lambda _flag: None)

    assert _mark(tmp_path).exists()


def test_boot_writes_no_marker_when_recovery_window_disabled(tmp_path):
    """OTA_BOOT_RECOVERY_LISTEN_MS = 0 is a true off-switch, filesystem too."""
    core = _no_flag_core(tmp_path)
    core.config["OTA_BOOT_RECOVERY_LISTEN_MS"] = 0

    boot.run(core, callback=None)

    assert not _mark(tmp_path).exists()


def test_boot_writes_no_marker_when_trial_rolls_back(tmp_path):
    """trial() resets onto the previous generation: leave no stale marker.

    That reset is why the marker is written after trial(), not before it.
    """
    machine.reset.reset_mock()
    main = tmp_path / "main.py"
    main.write_bytes(b"bad-candidate")
    (tmp_path / "main.py.bck").write_bytes(b"previous-good")
    core = _no_flag_core(tmp_path)
    core.config["OTA_TRIAL_BOOTS"] = 3
    restore.write_journal(core, 3, [str(main)])

    boot.run(core, callback=None)

    machine.reset.assert_called_once()
    assert not _mark(tmp_path).exists()


def test_boot_marker_write_failure_does_not_strand_the_boot(tmp_path):
    """A full or read-only filesystem degrades to the short window silently.

    A boot must never be stranded by a failed marker write.
    """
    core = _no_flag_core(tmp_path)
    real_open = builtins.open

    def _explode(path, *args, **kwargs):
        if str(path).endswith("otampy-boot.mark"):
            raise OSError(28, "No space left on device")
        return real_open(path, *args, **kwargs)

    with patch("builtins.open", _explode):
        boot.run(core, callback=None)

    assert not _mark(tmp_path).exists()


# =============================================================================
# The boot-time recovery window (_run_boot_listen)
#
# The window is how a device stranded before ota.poll() is recovered over the
# radio with no USB. It is silent -- no beacon -- so the host blind-retries
# while the operator power-cycles.
# =============================================================================

WINDOW_MS = 1000

AUTH_KEY_HEX = "0f1e2d3c4b5a6978" * 4


def _window_core(tmp_path, **extra):
    machine.reset.reset_mock()
    config = {
        "UPDATE_REQUEST_FLAG_FILE": str(tmp_path / "update_requested.flag"),
        "OTA_JOURNAL_FILE": str(tmp_path / "otampy-update.journal"),
        "OTA_REPLAY_FLOOR_FILE": str(tmp_path / "otampy-replay-floor"),
        "OTA_BOOT_LISTEN_MS": WINDOW_MS,
    }
    config.update(extra)
    return OTACore(shared.FakeUART(), config=config, logger=shared.FakeLogger())


def _fake_clock(monkeypatch, step=10):
    """Deterministic, instant clock -- no test may really sleep a window."""
    counter = itertools.count(0, step)
    monkeypatch.setattr(boot, "_ticks_ms", lambda: next(counter))
    monkeypatch.setattr(boot, "_sleep_ms", lambda _ms: None)


def _envelope(command, counter):
    """A signed AUTH: envelope, exactly as the CLI builds one."""
    blocks = device_auth.derive_key_blocks(bytes.fromhex(AUTH_KEY_HEX))
    mac = device_auth.tag(blocks, device_auth.signed_bytes(counter, command))
    return b"AUTH:%d:%s:%s" % (counter, binascii.hexlify(mac), command)


def test_boot_listen_expires_with_no_traffic(monkeypatch, tmp_path):
    """(a) Nothing arrives -> the window closes on its own, no reset."""
    core = _window_core(tmp_path)
    _fake_clock(monkeypatch)

    assert boot._run_boot_listen(core, WINDOW_MS) is False

    machine.reset.assert_not_called()
    assert core.transport.sent_messages == []


def test_boot_listen_deadline_is_absolute_not_inactivity(monkeypatch, tmp_path):
    """A stream of refused commands must not hold the window open.

    _run_default_update_loop resets its timer on every packet; the window
    deliberately does not, or a chatty peer could pin a device in it.
    """
    core = _window_core(tmp_path)
    _fake_clock(monkeypatch)
    core.transport.incoming_queue.extend([b"PING"] * 500)

    assert boot._run_boot_listen(core, WINDOW_MS) is False

    # 1000ms window / 10ms per tick -> ~100 packets served, not all 500.
    assert 0 < len(core.transport.sent_messages) < 200
    assert set(core.transport.sent_messages) == {b"ERROR:Recovery window"}
    machine.reset.assert_not_called()


@pytest.mark.parametrize("window_ms", [0, -1])
def test_boot_listen_disabled_never_reads(monkeypatch, tmp_path, window_ms):
    """(b) A window of 0 disables it outright -- not one read is issued.

    run() now chooses the duration, so this guards the argument rather than
    the config key. Which key produced the 0 is tested at run() level below.
    """
    core = _window_core(tmp_path)
    reads = []
    monkeypatch.setattr(core.transport, "read", lambda: reads.append(1) or None)

    assert boot._run_boot_listen(core, window_ms) is False

    assert reads == []
    machine.reset.assert_not_called()


def test_boot_listen_update_request_sets_flag_and_resets(monkeypatch, tmp_path):
    """(c) UPDATE_REQUEST hands the device to the existing update session."""
    core = _window_core(tmp_path)
    _fake_clock(monkeypatch)
    core.transport.incoming_queue.append(b"UPDATE_REQUEST")

    assert boot._run_boot_listen(core, WINDOW_MS) is True

    assert core.transport.sent_messages == [b"REBOOTING"]
    assert (tmp_path / "update_requested.flag").exists()
    machine.reset.assert_called_once()


def test_boot_listen_rollback_restores_and_resets(monkeypatch, tmp_path):
    """(d) ROLLBACK reverts to the retained generation and resets onto it."""
    core = _window_core(tmp_path)
    main = tmp_path / "main.py"
    main.write_bytes(b"fatal-candidate")
    (tmp_path / "main.py.bck").write_bytes(b"previous-good")
    restore.write_journal(core, restore._STATE_CONFIRMED, [str(main)])
    _fake_clock(monkeypatch)
    core.transport.incoming_queue.append(b"ROLLBACK")

    assert boot._run_boot_listen(core, WINDOW_MS) is True

    assert core.transport.sent_messages == [b"ROLLBACK_OK"]
    assert main.read_bytes() == b"previous-good"
    assert not (tmp_path / "otampy-update.journal").exists()
    machine.reset.assert_called_once()


def test_boot_listen_refusal_does_not_consume_the_window(monkeypatch, tmp_path):
    """(e) A refused ROLLBACK must not reset, and must not close the window.

    The operator who guesses wrong should not have to power-cycle again to
    get a second command into the same window.
    """
    core = _window_core(tmp_path)
    _fake_clock(monkeypatch)
    core.transport.incoming_queue.extend([b"ROLLBACK", b"UPDATE_REQUEST"])

    assert boot._run_boot_listen(core, WINDOW_MS) is True

    assert core.transport.sent_messages == [
        b"ROLLBACK_ERR:Nothing to roll back",
        b"REBOOTING",
    ]
    assert (tmp_path / "update_requested.flag").exists()
    machine.reset.assert_called_once()


def test_boot_listen_rollback_refuses_while_committing(monkeypatch, tmp_path):
    core = _window_core(tmp_path)
    main = tmp_path / "main.py"
    main.write_bytes(b"half-written")
    (tmp_path / "main.py.bck").write_bytes(b"previous-good")
    restore.write_journal(core, restore._STATE_COMMITTING, [str(main)])
    _fake_clock(monkeypatch)
    core.transport.incoming_queue.append(b"ROLLBACK")

    assert boot._run_boot_listen(core, WINDOW_MS) is False

    assert core.transport.sent_messages == [b"ROLLBACK_ERR:Commit in flight"]
    assert main.read_bytes() == b"half-written"
    machine.reset.assert_not_called()


def test_boot_listen_refuses_ping(monkeypatch, tmp_path):
    """(f) PING is deliberately unanswered: a PONG would say "healthy"."""
    core = _window_core(tmp_path)
    _fake_clock(monkeypatch)
    core.transport.incoming_queue.append(b"PING")

    assert boot._run_boot_listen(core, WINDOW_MS) is False

    assert core.transport.sent_messages == [b"ERROR:Recovery window"]
    machine.reset.assert_not_called()


def test_boot_listen_ignores_empty_and_non_utf8_packets(monkeypatch, tmp_path):
    core = _window_core(tmp_path)
    _fake_clock(monkeypatch)
    core.transport.incoming_queue.extend([b"", b"   ", b"\xff\xfe"])

    assert boot._run_boot_listen(core, WINDOW_MS) is False

    assert core.transport.sent_messages == []
    machine.reset.assert_not_called()


def test_boot_listen_rejects_unauthenticated_rollback(monkeypatch, tmp_path):
    """(g) The window is not an auth bypass.

    An unwrapped ROLLBACK is refused, nothing is restored, and a correctly
    signed one in the *same* window still succeeds.
    """
    core = _window_core(
        tmp_path, OTA_REQUIRE_AUTH=True, COMMAND_AUTH_KEY=AUTH_KEY_HEX
    )
    main = tmp_path / "main.py"
    main.write_bytes(b"fatal-candidate")
    (tmp_path / "main.py.bck").write_bytes(b"previous-good")
    restore.write_journal(core, restore._STATE_CONFIRMED, [str(main)])
    _fake_clock(monkeypatch)
    core.transport.incoming_queue.append(b"ROLLBACK")
    core.transport.incoming_queue.append(_envelope(b"ROLLBACK", 1))

    assert boot._run_boot_listen(core, WINDOW_MS) is True

    assert core.transport.sent_messages == [
        b"ERROR:Unauthenticated",
        b"ROLLBACK_OK",
    ]
    assert main.read_bytes() == b"previous-good"
    machine.reset.assert_called_once()


def test_boot_listen_rejects_replayed_counter(monkeypatch, tmp_path):
    core = _window_core(
        tmp_path, OTA_REQUIRE_AUTH=True, COMMAND_AUTH_KEY=AUTH_KEY_HEX
    )
    _fake_clock(monkeypatch)
    core.transport.incoming_queue.append(_envelope(b"PING", 5))
    core.transport.incoming_queue.append(_envelope(b"PING", 5))

    assert boot._run_boot_listen(core, WINDOW_MS) is False

    assert core.transport.sent_messages == [
        b"ERROR:Recovery window",
        b"ERROR:Replayed",
    ]
    machine.reset.assert_not_called()


# =============================================================================
# The window's wiring into boot.run()
#
# Ordering is the whole risk here: the window must open only on a healed
# tree (after repair()/trial()) and only when no update is already pending.
# =============================================================================


def _window_spy(monkeypatch, result=False):
    """Record whether run() opened the window -- and for how long.

    Returns a list of (core, window_ms) so the duration run() selected is
    observable without waiting one out.
    """
    calls = []

    def spy(core, window_ms):
        calls.append((core, window_ms))
        return result

    monkeypatch.setattr(boot, "_run_boot_listen", spy)
    return calls


def test_run_skips_the_window_when_an_update_is_pending(monkeypatch, tmp_path):
    """(a) A flagged boot is an update session; the window must not interfere."""
    machine.reset.reset_mock()
    flag_file = tmp_path / "update_requested.flag"
    flag_file.touch()
    core = OTACore(
        shared.FakeUART(),
        config={"UPDATE_REQUEST_FLAG_FILE": str(flag_file)},
        logger=shared.FakeLogger(),
    )
    calls = _window_spy(monkeypatch)

    boot.run(core, callback=lambda _flag: None)

    assert calls == []
    assert core.transport.sent_messages == [b"READY"]
    assert not flag_file.exists()


def test_run_opens_the_window_then_sweeps_orphans(monkeypatch, tmp_path):
    """(b) Window expires -> the existing no-flag cleanup still runs."""
    machine.reset.reset_mock()
    core = _no_flag_core(tmp_path)
    calls = _window_spy(monkeypatch, result=False)
    swept = []
    monkeypatch.setattr(
        boot, "_cleanup_orphaned_ota", lambda c, *a, **k: swept.append(c)
    )

    boot.run(core, callback=None)

    assert [c for c, _ in calls] == [core]
    assert swept == [core]


def test_run_returns_immediately_when_the_window_reset(monkeypatch, tmp_path):
    """(c) The window reset the board; run() must not carry on sweeping."""
    machine.reset.reset_mock()
    core = _no_flag_core(tmp_path)
    calls = _window_spy(monkeypatch, result=True)
    swept = []
    monkeypatch.setattr(
        boot, "_cleanup_orphaned_ota", lambda c, *a, **k: swept.append(c)
    )

    boot.run(core, callback=None)

    assert [c for c, _ in calls] == [core]
    assert swept == []


SHORT_MS = 111
WIDE_MS = 9999


def _selected_window(
    monkeypatch, tmp_path, marker=False, journal=None, **extra
):
    """Run a no-flag boot and return the window duration run() chose."""
    machine.reset.reset_mock()
    core = _no_flag_core(tmp_path)
    core.config["OTA_BOOT_LISTEN_MS"] = SHORT_MS
    core.config["OTA_BOOT_RECOVERY_LISTEN_MS"] = WIDE_MS
    core.config.update(extra)
    if marker:
        (tmp_path / "otampy-boot.mark").write_text("1")
    if journal is not None:
        (tmp_path / "main.py").write_bytes(b"candidate")
        (tmp_path / "main.py.bck").write_bytes(b"previous-good")
        restore.write_journal(core, journal, [str(tmp_path / "main.py")])
    calls = _window_spy(monkeypatch)

    boot.run(core, callback=None)

    assert len(calls) == 1, calls
    return calls[0][1]


def test_run_picks_the_short_window_on_a_healthy_boot(monkeypatch, tmp_path):
    """No marker, confirmed journal -> the existing ~1s cost, unchanged.

    This is the whole point of the conditional design: a healthy fleet must
    not pay the wide window.
    """
    assert _selected_window(monkeypatch, tmp_path) == SHORT_MS


def test_run_picks_the_wide_window_when_the_marker_survived(
    monkeypatch, tmp_path
):
    """The previous boot never reached OTA.poll() -- the rollback --recover
    case, which a journal-only test cannot see because the fatal generation
    was already confirmed."""
    assert _selected_window(monkeypatch, tmp_path, marker=True) == WIDE_MS


def test_run_picks_the_wide_window_for_a_candidate_on_trial(
    monkeypatch, tmp_path
):
    """An unconfirmed candidate can strand the device on its very first boot,
    before any marker has ever survived one."""
    assert _selected_window(monkeypatch, tmp_path, journal=0) == WIDE_MS


def test_a_stray_committing_journal_never_reaches_the_selection(
    monkeypatch, tmp_path
):
    """The spec's `committing -> wide` row is unreachable through run().

    repair() runs first and reverses a stray committing marker, so by the
    time the duration is chosen the journal reads confirmed and the short
    window is the correct answer. restore.state() still maps committing to a
    non-stable label, which is why `!= _LABEL_STABLE` -- rather than an
    equality test against "trial" -- remains the right defensive form should
    repair() ever leave one behind.
    """
    assert (
        _selected_window(
            monkeypatch, tmp_path, journal=restore._STATE_COMMITTING
        )
        == SHORT_MS
    )

    stray = _no_flag_core(tmp_path)
    restore.write_journal(
        stray, restore._STATE_COMMITTING, [str(tmp_path / "main.py")]
    )
    assert restore.state(stray)[0] != restore._LABEL_STABLE


def test_run_opens_no_window_at_all_when_the_wide_key_is_zero(
    monkeypatch, tmp_path
):
    """0 disables the wide window for a boot that qualifies for it -- it does
    not fall back to the short one."""
    assert (
        _selected_window(
            monkeypatch,
            tmp_path,
            journal=0,
            **{"OTA_BOOT_RECOVERY_LISTEN_MS": 0},
        )
        == 0
    )


def test_run_falls_back_to_the_default_on_a_garbage_wide_key(
    monkeypatch, tmp_path
):
    """A typo must not silently shorten the only radio recovery path."""
    from device_otampy.core import _DEFAULT_BOOT_RECOVERY_LISTEN_MS

    assert (
        _selected_window(
            monkeypatch,
            tmp_path,
            marker=True,
            **{"OTA_BOOT_RECOVERY_LISTEN_MS": "8s"},
        )
        == _DEFAULT_BOOT_RECOVERY_LISTEN_MS
    )


def test_run_keeps_the_two_keys_independent(monkeypatch, tmp_path):
    """A short key of 0 does not disable the wide window."""
    assert (
        _selected_window(
            monkeypatch, tmp_path, marker=True, **{"OTA_BOOT_LISTEN_MS": 0}
        )
        == WIDE_MS
    )


def test_run_auto_restores_before_the_window_opens(monkeypatch, tmp_path):
    """(d) A failed trial still auto-restores and resets ahead of the window.

    The window must never pre-empt trial()'s own recovery path.
    """
    machine.reset.reset_mock()
    main = tmp_path / "main.py"
    main.write_bytes(b"bad-candidate")
    (tmp_path / "main.py.bck").write_bytes(b"previous-good")
    core = _no_flag_core(tmp_path)
    core.config["OTA_TRIAL_BOOTS"] = 3
    restore.write_journal(core, 3, [str(main)])
    calls = _window_spy(monkeypatch)

    boot.run(core, callback=None)

    assert calls == []
    assert main.read_bytes() == b"previous-good"
    machine.reset.assert_called_once()
