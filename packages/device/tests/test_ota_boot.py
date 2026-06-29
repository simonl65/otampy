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
