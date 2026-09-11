from unittest.mock import patch

import pytest
import shared
from device_otampy.core import (
    _DEFAULT_BOOT_MARK_FILE,
    _DEFAULT_BOOT_RECOVERY_LISTEN_MS,
    NullLogger,
    OTACore,
    UartRequiredError,
    _boot_mark_path,
    _boot_recovery_window_ms,
    _get_config,
)


def test_core_init_uses_provided_uart():
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)
    assert core.uart is uart
    assert core.logger is logger
    assert core._transport is None


def test_core_uses_silent_logger_by_default():
    core = OTACore(shared.FakeUART())

    assert isinstance(core.logger, NullLogger)
    assert core.logger.min_level > 0
    core.logger.debug("ignored %s", "message")
    core.logger.info("ignored")
    core.logger.warning("ignored")
    core.logger.error("ignored")
    core.logger.critical("ignored")


def test_core_creates_transport_once_on_first_access():
    uart = shared.FakeUART()
    transport = object()

    with patch("urst.Urst", return_value=transport) as factory:
        core = OTACore(uart)

        factory.assert_not_called()
        assert core.transport is transport
        assert core.transport is transport

    factory.assert_called_once_with(uart)


def test_core_allows_transport_injection_without_importing_urst():
    uart = shared.FakeUART()
    transport = object()

    with patch("urst.Urst") as factory:
        core = OTACore(uart)
        core.transport = transport

        assert core.transport is transport
        factory.assert_not_called()


def test_core_init_errors_when_no_uart_provided():
    logger = shared.FakeLogger()
    with pytest.raises(UartRequiredError, match="Must provide a UART object"):
        OTACore(None, logger=logger)
    assert ("critical", "Must provide a UART object") in logger.messages


def test_core_default_config():
    uart = shared.FakeUART()
    core = OTACore(uart)
    assert core.config["LOG_LEVEL"] == "DEBUG"
    assert core.config["LOG_FILE"] == "/logs/ota.log"
    assert core.config["UPDATE_REQUEST_FLAG_FILE"] == "update_requested.flag"


def test_core_populates_defaults_in_provided_empty_mapping():
    config = {}
    core = OTACore(shared.FakeUART(), config=config)

    assert core.config is config
    assert config == {
        "LOG_LEVEL": "DEBUG",
        "LOG_FILE": "/logs/ota.log",
        "UPDATE_REQUEST_FLAG_FILE": "update_requested.flag",
    }


def test_core_keeps_nonempty_mapping_and_custom_settings():
    custom_value = object()
    config = {
        "UPDATE_REQUEST_FLAG_FILE": "custom.flag",
        "CUSTOM_SETTING": custom_value,
    }
    core = OTACore(shared.FakeUART(), config=config)

    assert core.config is config
    assert core.config.get("UPDATE_REQUEST_FLAG_FILE") == "custom.flag"
    assert core.config["CUSTOM_SETTING"] is custom_value


def test_core_keeps_custom_mapping_type():
    class CustomConfig:
        def __init__(self):
            self.values = {"UPDATE_REQUEST_FLAG_FILE": "custom.flag"}

        def get(self, name, default=None):
            return self.values.get(name, default)

    config = CustomConfig()
    core = OTACore(shared.FakeUART(), config=config)

    assert core.config is config
    assert core.config.get("UPDATE_REQUEST_FLAG_FILE") == "custom.flag"
    assert core.config.get("MISSING", "fallback") == "fallback"


def test_core_keeps_module_like_config_without_copying():
    custom_value = object()

    class ConfigModule:
        UPDATE_REQUEST_FLAG_FILE = "update_requested.flag"
        LOG_LEVEL = "DEBUG"
        LOG_FILE = "/logs/ota.log"
        CUSTOM_SETTING = custom_value

    uart = shared.FakeUART()
    core = OTACore(uart, config=ConfigModule)

    assert core.config is ConfigModule
    assert (
        _get_config(core.config, "UPDATE_REQUEST_FLAG_FILE")
        == "update_requested.flag"
    )
    assert _get_config(core.config, "LOG_LEVEL") == "DEBUG"
    assert _get_config(core.config, "LOG_FILE") == "/logs/ota.log"
    assert _get_config(core.config, "CUSTOM_SETTING") is custom_value
    assert _get_config(core.config, "MISSING", "fallback") == "fallback"


# =============================================================================
# The boot marker: the single parse of OTA_BOOT_RECOVERY_LISTEN_MS and the
# single path resolver. Both live here so boot.py and ota.py share one
# decision about whether the wide recovery window is on at all.
# See docs/development/failsafe-update-window-reachability-spec.md.
# =============================================================================


def test_boot_recovery_window_defaults_when_unset():
    assert _boot_recovery_window_ms({}) == _DEFAULT_BOOT_RECOVERY_LISTEN_MS


def test_boot_recovery_window_honours_override():
    config = {"OTA_BOOT_RECOVERY_LISTEN_MS": 2500}
    assert _boot_recovery_window_ms(config) == 2500


@pytest.mark.parametrize(
    "value,expected", [("2500", 2500), (2500.9, 2500), (0, 0), ("-1", -1)]
)
def test_boot_recovery_window_parses_anything_int_accepts(value, expected):
    """Why "non-integer" means garbage, not "a string".

    int("2500") and int(2500.9) both succeed, so a digit-string or a float in
    configota.py is honoured rather than silently replaced by the default.
    """
    config = {"OTA_BOOT_RECOVERY_LISTEN_MS": value}
    assert _boot_recovery_window_ms(config) == expected


@pytest.mark.parametrize("value", ["8s", "", None, object()])
def test_boot_recovery_window_falls_back_on_garbage(value):
    """A value int() cannot read is a typo, not an off-switch: fail open.

    Fail-closed here would let one mistyped config key silently remove the
    only radio recovery path -- F-10 reintroduced. Matches the house rule set
    by OTA_BOOT_LISTEN_MS, OTA_TIMEOUT_MS and restore.read_journal: only an
    explicit, in-range sentinel turns something off.
    """
    config = {"OTA_BOOT_RECOVERY_LISTEN_MS": value}
    assert _boot_recovery_window_ms(config) == _DEFAULT_BOOT_RECOVERY_LISTEN_MS


def test_boot_mark_path_defaults_when_unset():
    assert _boot_mark_path({}) == _DEFAULT_BOOT_MARK_FILE


def test_boot_mark_path_honours_override():
    assert _boot_mark_path({"OTA_BOOT_MARK_FILE": "/data/mark"}) == "/data/mark"


@pytest.mark.parametrize("value", [0, -1, "0", "-250"])
def test_boot_mark_path_is_none_when_recovery_window_disabled(value):
    """0 is the documented off-switch, and it costs zero filesystem work."""
    assert _boot_mark_path({"OTA_BOOT_RECOVERY_LISTEN_MS": value}) is None


@pytest.mark.parametrize("value", ["8s", "", None])
def test_boot_mark_path_survives_garbage_recovery_window(value):
    """The amended contract: a typo must not silently disable the marker."""
    config = {"OTA_BOOT_RECOVERY_LISTEN_MS": value}
    assert _boot_mark_path(config) == _DEFAULT_BOOT_MARK_FILE
