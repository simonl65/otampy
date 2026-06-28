import pytest
from shared import FakeLogger, FakeUART, Boot, fake_config


@pytest.mark.skip("TODO: Implement test test_do_we_have_update_flag_yes")
def test__do_we_have_update_flag__returns_true_when_flag_file_is_present(
    monkeypatch, tmp_path
):
    pass


def test__check_for_update_file__logs_flag_found(monkeypatch, tmp_path):
    logger = FakeLogger()
    boot = Boot.setup(monkeypatch, logger=logger)

    # Create a temporary flag file
    flag_file = tmp_path / "update_requested.flag"
    flag_file.write_text("")
    boot.config["UPDATE_REQUEST_FLAG_FILE"] = str(flag_file)

    boot.check_for_update_file(callback=None)

    assert (
        "debug",
        f"Update request flag found: {flag_file}",
    ) in logger.messages


def test__check_for_update_flag__returns_false_if_flag_not_found(
    monkeypatch, tmp_path
):
    logger = FakeLogger()
    boot = Boot.setup(monkeypatch, logger=logger)
    flag_file = tmp_path / "update_requested.flag"
    boot.config["UPDATE_REQUEST_FLAG_FILE"] = str(flag_file)

    boot.check_for_update_file(callback=None)

    assert (
        "debug",
        f"Update request flag found: {flag_file}",
    ) not in logger.messages
