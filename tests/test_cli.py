import json
import logging
import re
import time
import unittest.mock as mock
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from otampy.cli import (
    DeviceError,
    cli,
    get_config_value,
    get_default_log_level,
    set_default_port,
)

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def test_cli_help():
    """Test that running cli with -h, --help, or h displays help."""
    runner = CliRunner()

    # Test --help
    result_help = runner.invoke(cli, ["--help"])
    assert result_help.exit_code == 0
    assert (
        "Show this message and exit." in result_help.output
        or "Over the Air (OTA) File Management CLI" in result_help.output
    )
    assert "--log-level" in result_help.output

    # Test -h
    result_h_opt = runner.invoke(cli, ["-h"])
    assert result_h_opt.exit_code == 0
    assert (
        "Show this message and exit." in result_h_opt.output
        or "Over the Air (OTA) File Management CLI" in result_h_opt.output
    )


def test_init_slash_path_is_project_relative(tmp_path):
    runner = CliRunner()
    project_root = tmp_path / "project"
    project_root.mkdir()

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=12345),
        mock.patch(
            "otampy.cli._detect_project_root", return_value=project_root
        ),
    ):
        result = runner.invoke(cli, ["init", "/device"])

    assert result.exit_code == 0
    assert (project_root / "device" / "boot.py").is_file()


def test_deploy_device_dir_is_project_relative(tmp_path):
    runner = CliRunner()
    project_root = tmp_path / "project"
    project_root.mkdir()

    with (
        mock.patch(
            "otampy.cli._detect_project_root", return_value=project_root
        ),
        mock.patch("otampy.cli.deploy.deploy") as deploy,
    ):
        result = runner.invoke(cli, ["deploy", "--device-dir", "/device"])

    assert result.exit_code == 0
    assert deploy.call_args.args[0].device_dir == project_root / "device"


def test_deploy_uses_saved_absolute_device_dir(tmp_path):
    runner = CliRunner()
    project_root = tmp_path / "project"
    device_dir = tmp_path / "saved-device"
    project_root.mkdir()
    deploy_command = cli.commands["deploy"]
    device_dir_option = next(
        param
        for param in deploy_command.params
        if param.name == "device_dir"
    )

    with (
        mock.patch(
            "otampy.cli._detect_project_root", return_value=project_root
        ),
        mock.patch.object(device_dir_option, "default", lambda: str(device_dir)),
        mock.patch("otampy.cli.deploy.deploy") as deploy,
    ):
        result = runner.invoke(cli, ["deploy"])

    assert result.exit_code == 0
    assert deploy.call_args.args[0].device_dir == device_dir


def test_cli_log_level_for_current_command():
    runner = CliRunner()
    previous_level = logging.getLogger().level

    try:
        # --log-level now applies silently for the current command only,
        # with no interactive save prompt.
        result = runner.invoke(
            cli,
            ["--log-level", "DEBUG", "ports", "--show"],
        )

        assert result.exit_code == 0
        assert "Keep DEBUG as the log level?" not in result.output
        assert logging.getLogger().level == logging.DEBUG
    finally:
        logging.getLogger().setLevel(previous_level)


def test_cli_log_level_can_be_saved_permanently(tmp_path):
    runner = CliRunner()
    previous_level = logging.getLogger().level

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=123),
    ):
        try:
            config_file = tmp_path / ".config" / "otampy" / "config.json"
            config_file.parent.mkdir(parents=True)
            # Write pre-existing port in new project-scoped format
            fake_root = "/fake/project"
            config_file.write_text(
                json.dumps(
                    {"projects": {fake_root: {"default_port": "/dev/ttySaved"}}}
                )
            )

            # Use the log-level command to save permanently.
            result = runner.invoke(cli, ["log-level", "--set", "DEBUG"])

            assert result.exit_code == 0
            assert "Permanent log level set to: DEBUG" in result.output
            saved = json.loads(config_file.read_text())
            assert saved.get("global", {}).get("log_level") == "DEBUG"
            # Pre-existing project port must be preserved
            assert (
                saved["projects"][fake_root]["default_port"] == "/dev/ttySaved"
            )

            # Next plain invocation uses the saved level with no prompt.
            result = runner.invoke(cli, ["ports", "--show"])

            assert result.exit_code == 0
            assert "Keep DEBUG as the log level?" not in result.output
            assert logging.getLogger().level == logging.DEBUG
        finally:
            logging.getLogger().setLevel(previous_level)


def test_cli_log_level_can_be_saved_for_session(tmp_path):
    runner = CliRunner()
    previous_level = logging.getLogger().level

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=456),
    ):
        try:
            # Use the log-level command in interactive mode, choose session.
            result = runner.invoke(
                cli,
                ["log-level"],
                input="INFO\ns\n",
            )

            assert result.exit_code == 0
            assert "Session log level set to: INFO" in result.output
            session_file = tmp_path / "otampy_session_456.json"
            assert json.loads(session_file.read_text())["log_level"] == "INFO"

            # Next plain invocation uses the saved level with no prompt.
            result = runner.invoke(cli, ["ports", "--show"])

            assert result.exit_code == 0
            assert "Keep INFO as the log level?" not in result.output
            assert logging.getLogger().level == logging.INFO
        finally:
            logging.getLogger().setLevel(previous_level)


def test_cli_rejects_invalid_log_level():
    result = CliRunner().invoke(
        cli, ["--log-level", "VERBOSE", "ports", "--show"]
    )

    assert result.exit_code == 2
    assert "Invalid value for '--log-level'" in result.output


# =============================================================================
# log-level command tests
# =============================================================================


def test_log_level_cmd_show(tmp_path):
    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=1),
    ):
        result = CliRunner().invoke(cli, ["log-level", "--show"])
        assert result.exit_code == 0
        assert "ERROR" in result.output  # default when nothing saved


def test_log_level_cmd_show_reflects_saved_level(tmp_path):
    config_file = tmp_path / ".config" / "otampy" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(json.dumps({"global": {"log_level": "WARNING"}}))

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=1),
    ):
        result = CliRunner().invoke(cli, ["log-level", "--show"])
        assert result.exit_code == 0
        assert "WARNING" in result.output


def test_log_level_cmd_set_saves_permanently(tmp_path):
    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=1),
    ):
        result = CliRunner().invoke(cli, ["log-level", "--set", "INFO"])
        assert result.exit_code == 0
        assert "Permanent log level set to: INFO" in result.output

        config_file = tmp_path / ".config" / "otampy" / "config.json"
        assert (
            json.loads(config_file.read_text())["global"]["log_level"] == "INFO"
        )


def test_log_level_cmd_set_clears_session_shadow(tmp_path):
    """--set must clear any session file so it no longer shadows the permanent config."""
    fake_ppid = 77777
    session_file = tmp_path / f"otampy_session_{fake_ppid}.json"

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=fake_ppid),
    ):
        # Plant a session log level.
        session_file.write_text(json.dumps({"log_level": "DEBUG"}))

        result = CliRunner().invoke(cli, ["log-level", "--set", "WARNING"])
        assert result.exit_code == 0
        assert "Permanent log level set to: WARNING" in result.output

        # Session file must have had the log_level key removed (or file gone).
        if session_file.exists():
            assert "log_level" not in json.loads(session_file.read_text())


def test_log_level_cmd_clear(tmp_path):
    config_file = tmp_path / ".config" / "otampy" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(json.dumps({"global": {"log_level": "DEBUG"}}))

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=1),
    ):
        result = CliRunner().invoke(cli, ["log-level", "--clear"])
        assert result.exit_code == 0
        assert "cleared" in result.output.lower()

        # File gone (no remaining keys) or log_level key removed.
        if config_file.exists():
            data = json.loads(config_file.read_text())
            assert "log_level" not in data.get("global", {})


def test_log_level_cmd_interactive_permanent(tmp_path):
    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=1),
    ):
        result = CliRunner().invoke(cli, ["log-level"], input="DEBUG\np\n")
        assert result.exit_code == 0
        assert "Permanent log level set to: DEBUG" in result.output

        config_file = tmp_path / ".config" / "otampy" / "config.json"
        assert (
            json.loads(config_file.read_text())["global"]["log_level"]
            == "DEBUG"
        )


def test_log_level_cmd_interactive_session(tmp_path):
    fake_ppid = 88888
    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=fake_ppid),
    ):
        result = CliRunner().invoke(cli, ["log-level"], input="INFO\ns\n")
        assert result.exit_code == 0
        assert "Session log level set to: INFO" in result.output

        session_file = tmp_path / f"otampy_session_{fake_ppid}.json"
        assert json.loads(session_file.read_text())["log_level"] == "INFO"


def test_log_level_cmd_interactive_cancel(tmp_path):
    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=1),
    ):
        # Cancel at level prompt.
        result = CliRunner().invoke(cli, ["log-level"], input="\n")
        assert result.exit_code == 0
        assert "Cancelled" in result.output

        # Cancel at save prompt.
        result = CliRunner().invoke(cli, ["log-level"], input="DEBUG\nc\n")
        assert result.exit_code == 0
        assert "Cancelled" in result.output


def test_log_level_cmd_interactive_rejects_invalid_level(tmp_path):
    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=1),
    ):
        result = CliRunner().invoke(cli, ["log-level"], input="VERBOSE\n")
        assert result.exit_code != 0
        assert "Invalid" in result.output or "invalid" in result.output


def test_log_level_cmd_loglevel_alias(tmp_path):
    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=1),
    ):
        result = CliRunner().invoke(cli, ["loglevel", "--show"])
        assert result.exit_code == 0
        assert "ERROR" in result.output


def test_log_level_precedence_is_environment_session_permanent(tmp_path):
    config_file = tmp_path / ".config" / "otampy" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(json.dumps({"global": {"log_level": "DEBUG"}}))
    (tmp_path / "otampy_session_789.json").write_text(
        json.dumps({"log_level": "INFO"})
    )

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=789),
    ):
        assert get_default_log_level() == "INFO"
        with mock.patch.dict("os.environ", {"OTAMPY_LOG_LEVEL": "WARNING"}):
            assert get_default_log_level() == "WARNING"


def test_clearing_port_preserves_permanent_log_level(tmp_path):
    fake_root = "/fake/project"
    config_file = tmp_path / ".config" / "otampy" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        json.dumps(
            {
                "projects": {fake_root: {"default_port": "/dev/ttyFake"}},
                "global": {"log_level": "DEBUG"},
            }
        )
    )

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch(
            "otampy.cli._detect_project_root", return_value=Path(fake_root)
        ),
    ):
        set_default_port(None)

    saved = json.loads(config_file.read_text())
    assert saved.get("global", {}).get("log_level") == "DEBUG"
    assert "default_port" not in saved.get("projects", {}).get(fake_root, {})


# =============================================================================
# config command tests
# =============================================================================


def test_config_cmd_show_lists_advanced_defaults(tmp_path):
    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=1),
    ):
        result = CliRunner().invoke(cli, ["config", "--show"])

    assert result.exit_code == 0
    assert "serial-timeout" in result.output
    assert "query-retries" in result.output
    assert "update-ready-timeout" in result.output
    assert "transfer-chunk-size" in result.output
    assert "default" in result.output


def test_config_cmd_set_saves_project_value_and_clears_session_shadow(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    session_file = tmp_path / "otampy_session_42.json"
    session_file.write_text(json.dumps({"serial_timeout_seconds": 9.0}))

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=42),
        mock.patch(
            "otampy.cli._detect_project_root", return_value=project_root
        ),
    ):
        result = CliRunner().invoke(
            cli, ["config", "--set", "serial-timeout", "3.5"]
        )

    assert result.exit_code == 0
    assert "Permanent config set: serial-timeout=3.5" in result.output

    config_file = tmp_path / ".config" / "otampy" / "config.json"
    data = json.loads(config_file.read_text())
    assert (
        data["projects"][str(project_root)]["serial_timeout_seconds"] == 3.5
    )
    if session_file.exists():
        assert "serial_timeout_seconds" not in json.loads(
            session_file.read_text()
        )


def test_config_cmd_session_value_takes_precedence(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=77),
        mock.patch(
            "otampy.cli._detect_project_root", return_value=project_root
        ),
    ):
        permanent = CliRunner().invoke(
            cli, ["config", "--set", "query-retries", "2"]
        )
        session = CliRunner().invoke(
            cli, ["config", "--session", "--set", "query-retries", "4"]
        )
        assert permanent.exit_code == 0
        assert session.exit_code == 0
        assert get_config_value("query-retries") == 4

        with mock.patch.dict("os.environ", {"OTAMPY_QUERY_RETRIES": "5"}):
            assert get_config_value("query-retries") == 5


def test_config_cmd_clear_removes_saved_and_session_values(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=88),
        mock.patch(
            "otampy.cli._detect_project_root", return_value=project_root
        ),
    ):
        CliRunner().invoke(cli, ["config", "--set", "query-retries", "2"])
        CliRunner().invoke(
            cli, ["config", "--session", "--set", "query-retries", "4"]
        )
        result = CliRunner().invoke(cli, ["config", "--clear", "query-retries"])

    assert result.exit_code == 0
    assert "Saved config cleared: query-retries" in result.output

    config_file = tmp_path / ".config" / "otampy" / "config.json"
    if config_file.exists():
        data = json.loads(config_file.read_text())
        project = data.get("projects", {}).get(str(project_root), {})
        assert "query_retries" not in project

    session_file = tmp_path / "otampy_session_88.json"
    if session_file.exists():
        assert "query_retries" not in json.loads(session_file.read_text())


def test_config_cmd_rejects_invalid_values(tmp_path):
    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=1),
    ):
        result = CliRunner().invoke(
            cli, ["config", "--set", "transfer-chunk-size", "0"]
        )

    assert result.exit_code != 0
    assert "between 1 and " in result.output


def test_cli_ping():
    """Test the 'ping' command."""
    runner = CliRunner()
    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"PONG"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "ping"])
        assert result.exit_code == 0
        assert "Sending PING to device" in result.output
        assert "Success: Received PONG from device" in result.output
        mock_serial.assert_called_once_with(
            "/dev/ttyFake", baudrate=57600, timeout=2.0
        )
        mock_device_instance.send.assert_called_once_with(b"PING")


def test_cli_rtc_displays_device_timestamp():
    """Test the read-only 'rtc' command."""
    runner = CliRunner()
    with (
        mock.patch("serial.Serial"),
        mock.patch("urst.Urst") as mock_device,
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"RTC_OK:(2026, 7, 21, 0, 12, 34, 56, 789)"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "rtc"])

    assert result.exit_code == 0
    assert "Device RTC: 2026-07-21 12:34:56" in result.output
    mock_device_instance.send.assert_called_once_with(b"RTC")


def test_cli_ping_response_within_timeout():
    """Test delayed PONG reception within the transport timeout."""
    runner = CliRunner()

    def delayed_read():
        time.sleep(1)
        return b"PONG"

    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.side_effect = delayed_read

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "ping"])

    assert result.exit_code == 0
    assert "Success: Received PONG from device" in result.output
    mock_serial.assert_called_once_with(
        "/dev/ttyFake", baudrate=57600, timeout=2.0
    )
    mock_device_instance.send.assert_called_once_with(b"PING")


def test_cli_ping_response_timeout():
    """Test ping failure when no response is received within the timeout."""
    runner = CliRunner()

    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
        mock.patch("time.sleep") as mock_sleep,
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b""

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "ping"])

    assert result.exit_code != 0
    assert "Timeout waiting for response to command: PING" in result.output
    assert mock_serial.call_count == 3
    mock_serial.assert_any_call("/dev/ttyFake", baudrate=57600, timeout=2.0)
    assert mock_device_instance.send.call_count == 3
    assert mock_sleep.call_count == 2


def test_cli_hard_reboot():
    """Test the 'rb' command (hard reboot) with confirmation."""
    runner = CliRunner()
    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"RB_OK"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "rb"], input="y\n")
        assert result.exit_code == 0
        assert "Hard rebooting the device" in result.output
        mock_serial.assert_called_once_with(
            "/dev/ttyFake", baudrate=57600, timeout=2.0
        )
        mock_device_instance.send.assert_called_once_with(b"RB")


def test_cli_hard_reboot_aborted():
    """Test that 'rb' command defaults to aborting when not confirmed."""
    runner = CliRunner()
    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "rb"], input="\n")
        assert result.exit_code == 0
        assert "Aborted." in result.output
        mock_serial.assert_not_called()
        mock_device.assert_not_called()


def test_cli_soft_reset():
    """Test the 'sr' command (soft reset) with confirmation."""
    runner = CliRunner()
    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"SR_OK"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "sr"], input="y\n")
        assert result.exit_code == 0
        assert "Soft resetting the device" in result.output
        mock_serial.assert_called_once_with(
            "/dev/ttyFake", baudrate=57600, timeout=2.0
        )
        mock_device_instance.send.assert_called_once_with(b"SR")


def test_cli_soft_reset_aborted():
    """Test that 'sr' command defaults to aborting when not confirmed."""
    runner = CliRunner()
    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "sr"], input="\n")
        assert result.exit_code == 0
        assert "Aborted." in result.output
        mock_serial.assert_not_called()
        mock_device.assert_not_called()


def test_cli_reboot_set_time_stages_before_reboot():
    runner = CliRunner()
    with (
        mock.patch("otampy.cli._stage_rtc_update") as stage_time,
        mock.patch("otampy.cli._send_command") as send_command,
    ):
        result = runner.invoke(cli, ["rb", "--set-time"], input="y\n")

    assert result.exit_code == 0
    stage_time.assert_called_once()
    send_command.assert_called_once_with(mock.ANY, b"RB", b"RB_OK")


def test_cli_command_missing_port(tmp_path):
    """Test that running connection commands without -p raises an error."""
    runner = CliRunner()
    with (
        mock.patch.dict("os.environ", {}, clear=True),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("pathlib.Path.home", return_value=tmp_path),
    ):
        result = runner.invoke(cli, ["ping"])
    assert result.exit_code != 0
    assert "Error: Missing serial port" in result.output


def test_cli_ls_default():
    """Test the 'ls' command without paths."""
    runner = CliRunner()
    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"LS_OK:boot.py,main.py"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "ls"])
        assert result.exit_code == 0
        assert "boot.py" in result.output
        assert "main.py" in result.output
        mock_serial.assert_called_once_with(
            "/dev/ttyFake", baudrate=57600, timeout=2.0
        )
        mock_device_instance.send.assert_called_once_with(b"LS")


def test_session_port_is_available_to_later_command(tmp_path):
    runner = CliRunner()
    port = mock.MagicMock()
    port.device = "COM3"
    port.description = "USB Serial Device"
    port.serial_number = None
    port.vid = None
    port.pid = None
    port.manufacturer = None
    port.product = None
    port.hwid = "USB"

    with (
        mock.patch("serial.tools.list_ports.comports", return_value=[port]),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("otampy.cli._session_id", return_value="win-42"),
    ):
        result = runner.invoke(cli, ["ports"], input="1\ns\n")
        assert result.exit_code == 0
        assert "Session default port set to: COM3" in result.output

        with (
            mock.patch("serial.Serial") as serial,
            mock.patch("urst.Urst") as urst,
        ):
            urst.return_value.read.return_value = b"LS_OK:main.py"
            result = runner.invoke(cli, ["ls"])

    assert result.exit_code == 0
    assert "main.py" in result.output
    serial.assert_called_once_with("COM3", baudrate=57600, timeout=2.0)


def test_cli_ls_path():
    """Test the 'ls' command with a specific path."""
    runner = CliRunner(env={"NO_COLOR": "1"})
    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"LS_OK:sensor.py"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "ls", "/lib"])
        assert result.exit_code == 0
        assert "sensor.py" in result.output
        mock_serial.assert_called_once_with(
            "/dev/ttyFake", baudrate=57600, timeout=2.0
        )
        mock_device_instance.send.assert_called_once_with(b"LS:/lib")


def test_cli_cat_missing_arg():
    """Test that 'cat' without required file argument fails."""
    runner = CliRunner()
    result = runner.invoke(cli, ["cat"])
    assert result.exit_code != 0
    assert "Error: Missing argument" in result.output


def test_cli_cat_file():
    """Test the 'cat' command with a file."""
    runner = CliRunner()
    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"CAT_OK:import config"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "cat", "boot.py"])
        assert result.exit_code == 0
        assert "import config" in result.output
        mock_serial.assert_called_once_with(
            "/dev/ttyFake", baudrate=57600, timeout=2.0
        )
        mock_device_instance.send.assert_called_once_with(b"CAT:boot.py")


def test_cli_rm_missing_arg():
    """Test that 'rm' without required file argument fails."""
    runner = CliRunner()
    result = runner.invoke(cli, ["rm"])
    assert result.exit_code != 0
    assert "Error: Missing argument" in result.output


def test_cli_rm_rejects_arguments_matching_local_paths(tmp_path, monkeypatch):
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "alpha.txt"
    second = tmp_path / "folder"
    first.write_text("keep me")
    second.mkdir()

    with mock.patch("otampy.cli._send_command") as send_command:
        result = runner.invoke(
            cli,
            [
                "-p",
                "/dev/ttyFake",
                "rm",
                first.name,
                second.name,
            ],
        )

    assert result.exit_code != 0
    assert "RM only deletes paths on the remote device" in result.output
    assert "No local files were changed" in result.output
    assert "otampy rm '*'" in result.output
    assert first.read_text() == "keep me"
    assert second.is_dir()
    send_command.assert_not_called()


def test_cli_rm_literal_remote_paths_never_delete_local_matches(
    tmp_path, monkeypatch
):
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "alpha.txt"
    second = tmp_path / "beta.txt"
    first.write_text("local alpha")
    second.write_text("local beta")

    with mock.patch("otampy.cli._send_command") as send_command:
        result = runner.invoke(
            cli,
            [
                "-p",
                "/dev/ttyFake",
                "rm",
                "--literal-remote-paths",
                first.name,
                second.name,
            ],
            input="y\n",
        )

    assert result.exit_code == 0
    assert "from the remote device?" in result.output
    assert first.read_text() == "local alpha"
    assert second.read_text() == "local beta"
    assert send_command.call_args_list == [
        mock.call(mock.ANY, b"RM:alpha.txt", b"RM_OK"),
        mock.call(mock.ANY, b"RM:beta.txt", b"RM_OK"),
    ]


def test_cli_rm_colon_prefix_marks_matching_local_name_as_remote(
    tmp_path, monkeypatch
):
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    local_file = tmp_path / "notes.txt"
    local_file.write_text("keep local")

    with mock.patch("otampy.cli._send_command") as send_command:
        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "rm", ":notes.txt"],
            input="y\n",
        )

    assert result.exit_code == 0
    assert local_file.read_text() == "keep local"
    send_command.assert_called_once_with(
        mock.ANY,
        b"RM:notes.txt",
        b"RM_OK",
    )


@pytest.mark.parametrize(
    "path",
    (
        "boot.py",
        "/main.py",
        "./configota.py",
        "lib/otampy/manager.py",
        "/lib/urst/core.py",
        "lib",
        "/",
        ":/main.py",
        "lib/plugins/../../main.py",
    ),
)
def test_cli_rm_rejects_protected_recovery_paths(path):
    runner = CliRunner()
    with mock.patch("otampy.cli._send_command") as send_command:
        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "rm", path],
        )

    assert result.exit_code != 0
    assert "Refusing to remove protected recovery path" in result.output
    assert "otampy cp" in result.output
    assert "Are you sure" not in result.output
    send_command.assert_not_called()


def test_cli_rm_preflights_all_targets_before_deleting_any():
    runner = CliRunner()
    with mock.patch("otampy.cli._send_command") as send_command:
        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "rm", "scratch.txt", "main.py"],
        )

    assert result.exit_code != 0
    assert "main.py" in result.output
    send_command.assert_not_called()


def test_cli_rm_preflights_expanded_wildcard_before_deleting_any():
    runner = CliRunner()
    with (
        mock.patch(
            "otampy.cli._query",
            return_value=(b"notes.py,main.py", None),
        ),
        mock.patch("otampy.cli._send_command") as send_command,
    ):
        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "rm", "*.py"],
        )

    assert result.exit_code != 0
    assert "main.py" in result.output
    send_command.assert_not_called()


def test_cli_rm_colon_root_glob_reports_protected_paths_before_prompt():
    runner = CliRunner()
    with (
        mock.patch(
            "otampy.cli._query",
            return_value=(b"boot.py,configota.py,lib/,logs/,main.py", None),
        ) as query,
        mock.patch("otampy.cli._send_command") as send_command,
    ):
        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "rm", ":/*"],
        )

    assert result.exit_code != 0
    assert "Refusing to remove protected recovery path" in result.output
    assert "/boot.py" in result.output
    assert "/main.py" in result.output
    assert "Missing filename" not in result.output
    assert "Are you sure" not in result.output
    query.assert_called_once_with(mock.ANY, b"LS:/", b"LS_OK")
    send_command.assert_not_called()


def test_cli_rm_file():
    """Test the 'rm' command with a file with confirmation."""
    runner = CliRunner()
    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"RM_OK"

        result = runner.invoke(
            cli, ["-p", "/dev/ttyFake", "rm", "temp.py"], input="y\n"
        )
        assert result.exit_code == 0
        assert "Removing remote path: temp.py" in result.output
        mock_serial.assert_called_once_with(
            "/dev/ttyFake", baudrate=57600, timeout=2.0
        )
        mock_device_instance.send.assert_called_once_with(b"RM:temp.py")


def test_cli_rm_multiple_files():
    runner = CliRunner()
    with mock.patch("otampy.cli._send_command") as send_command:
        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "rm", "temp.py", "data.json"],
            input="y\n",
        )

    assert result.exit_code == 0
    assert "these 2 paths: temp.py, data.json" in result.output
    assert send_command.call_args_list == [
        mock.call(mock.ANY, b"RM:temp.py", b"RM_OK"),
        mock.call(mock.ANY, b"RM:data.json", b"RM_OK"),
    ]


def test_cli_rm_expands_remote_wildcards():
    runner = CliRunner()
    with (
        mock.patch(
            "otampy.cli._query",
            return_value=(b"boot.py,core.py,README.txt,helpers/", None),
        ) as query,
        mock.patch("otampy.cli._send_command") as send_command,
    ):
        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "rm", "lib/plugins/*.py"],
            input="y\n",
        )

    assert result.exit_code == 0
    query.assert_called_once_with(mock.ANY, b"LS:lib/plugins", b"LS_OK")
    assert send_command.call_args_list == [
        mock.call(mock.ANY, b"RM:lib/plugins/boot.py", b"RM_OK"),
        mock.call(mock.ANY, b"RM:lib/plugins/core.py", b"RM_OK"),
    ]


def test_cli_rm_rejects_unmatched_remote_wildcard():
    runner = CliRunner()
    with (
        mock.patch("otampy.cli._query", return_value=(b"main.py", None)),
        mock.patch("otampy.cli._send_command") as send_command,
    ):
        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "rm", "*.txt"],
        )

    assert result.exit_code != 0
    assert "No remote paths matched: *.txt" in result.output
    send_command.assert_not_called()


def test_cli_rm_expands_recursive_wildcard_in_deletion_order():
    runner = CliRunner()
    listings = {
        b"LS:logs": b"current.log,archive/",
        b"LS:logs/archive": b"old.log",
    }

    def query(_ctx, command, _expected):
        return listings[command], None

    with (
        mock.patch("otampy.cli._query", side_effect=query),
        mock.patch("otampy.cli._send_command") as send_command,
    ):
        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "rm", "logs/**"],
            input="y\n",
        )

    assert result.exit_code == 0
    assert [call.args[1] for call in send_command.call_args_list] == [
        b"RM:logs/current.log",
        b"RM:logs/archive/old.log",
        b"RM:logs/archive",
    ]


def test_cli_rm_recursively_removes_nested_directory_with_one_connection():
    runner = CliRunner()
    responses = {
        b"LS:cache": b"file.txt,sub/",
        b"RM:cache/file.txt": b"",
        b"LS:cache/sub": b"nested.txt",
        b"RM:cache/sub/nested.txt": b"",
        b"RM:cache/sub": b"",
        b"RM:cache": b"",
    }

    def query(_ctx, command, _expected, transport=None):
        assert transport is not None
        return responses[command], None

    with (
        mock.patch(
            "otampy.cli._send_command",
            side_effect=DeviceError("ENOTEMPTY", b"RM:cache"),
        ),
        mock.patch("otampy.cli._query", side_effect=query) as query_mock,
        mock.patch("serial.Serial") as serial,
        mock.patch("urst.Urst"),
    ):
        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "rm", "cache"],
            input="y\ny\n",
        )

    assert result.exit_code == 0
    assert "Directory removed successfully." in result.output
    serial.assert_called_once_with("/dev/ttyFake", baudrate=57600, timeout=2.0)
    assert [call.args[1] for call in query_mock.call_args_list] == [
        b"LS:cache",
        b"RM:cache/file.txt",
        b"LS:cache/sub",
        b"RM:cache/sub/nested.txt",
        b"RM:cache/sub",
        b"RM:cache",
    ]


def test_cli_rm_file_aborted():
    """Test that 'rm' command defaults to aborting when not confirmed."""
    runner = CliRunner()
    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        result = runner.invoke(
            cli, ["-p", "/dev/ttyFake", "rm", "temp.py"], input="\n"
        )
        assert result.exit_code == 0
        assert "Aborted." in result.output
        mock_serial.assert_not_called()
        mock_device.assert_not_called()


def test_cli_mem():
    """Test the 'mem' command."""
    runner = CliRunner()
    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        mock_device_instance = mock_device.return_value
        # ram_free, ram_alloc, flash_free, flash_total
        mock_device_instance.read.return_value = (
            b"MEM_OK:50000,30000,524288,1048576"
        )

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "mem"])
        assert result.exit_code == 0
        assert "RAM (Random Access Memory)" in result.output
        assert "Free:" in result.output
        assert "48.8 KB" in result.output  # 50000 / 1024 = 48.828 KB -> 48.8 KB
        assert "Allocated:" in result.output
        assert "29.3 KB" in result.output  # 30000 / 1024 = 29.296 KB -> 29.3 KB
        assert "Flash (Storage)" in result.output
        assert "512.0 KB" in result.output
        assert "1.0 MB" in result.output
        mock_serial.assert_called_once_with(
            "/dev/ttyFake", baudrate=57600, timeout=2.0
        )
        mock_device_instance.send.assert_called_once_with(b"MEM")


def test_cli_friendly_errors():
    """Test that _friendly_error maps raw OS errors to human-friendly strings."""
    runner = CliRunner()

    with mock.patch("time.sleep"):
        # 1. LS command with ENOENT error
        with (
            mock.patch("serial.Serial"),
            mock.patch("urst.Urst") as mock_device,
        ):
            mock_device_instance = mock_device.return_value
            mock_device_instance.read.return_value = b"ERROR:[Errno 2] ENOENT"

            result = runner.invoke(
                cli, ["-p", "/dev/ttyFake", "ls", "lib/Boot.py"]
            )
            assert result.exit_code == 1
            assert (
                "Error: No such file or directory: 'lib/Boot.py'"
                in result.output
            )

        # 2. CAT command with ENOENT error
        with (
            mock.patch("serial.Serial"),
            mock.patch("urst.Urst") as mock_device,
        ):
            mock_device_instance = mock_device.return_value
            mock_device_instance.read.return_value = b"ERROR:ENOENT"

            result = runner.invoke(
                cli, ["-p", "/dev/ttyFake", "cat", "missing.py"]
            )
            assert result.exit_code == 1
            assert (
                "Error: No such file or directory: 'missing.py'"
                in result.output
            )

        # 3. RM command with EACCES error
        with (
            mock.patch("serial.Serial"),
            mock.patch("urst.Urst") as mock_device,
        ):
            mock_device_instance = mock_device.return_value
            mock_device_instance.read.return_value = b"ERROR:[Errno 13] EACCES"

            result = runner.invoke(
                cli, ["-p", "/dev/ttyFake", "rm", "system.py"], input="y\n"
            )
            assert result.exit_code == 1
            assert "Error: Permission denied: 'system.py'" in result.output

        # 4. CAT command on directory (EISDIR)
        with (
            mock.patch("serial.Serial"),
            mock.patch("urst.Urst") as mock_device,
        ):
            mock_device_instance = mock_device.return_value
            mock_device_instance.read.return_value = b"ERROR:EISDIR"

            result = runner.invoke(cli, ["-p", "/dev/ttyFake", "cat", "lib"])
            assert result.exit_code == 1
            assert "Error: Is a directory: 'lib/'" in result.output


def test_cli_update_default():
    """Test 'upd' command without parameters and no local files exits early."""
    runner = CliRunner()
    result = runner.invoke(cli, ["-p", "/dev/ttyFake", "upd"])
    assert result.exit_code == 0
    assert "No files found to transfer" in result.output


def test_cli_update_with_files():
    """Test 'upd' command with no matching files exits early without touching device."""
    runner = CliRunner(env={"NO_COLOR": "1"})
    with mock.patch("otampy.cli._get_files_to_send", return_value=[]):
        result = runner.invoke(
            cli, ["-p", "/dev/ttyFake", "upd", ".", "main.py", "lib/lib2.py"]
        )
        assert result.exit_code == 0
        assert "No files found to transfer" in result.output


def test_get_files_to_send_keeps_multiple_mappings(tmp_path, monkeypatch):
    from otampy.cli import _get_files_to_send

    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    for name in ("boot.py", "main.py", "configota.py"):
        (source / name).write_text(f"# {name}\n")

    files = _get_files_to_send(
        (
            "source/boot.py:lib/otampy/boot.py",
            "source/main.py:lib/otampy/main.py",
            "source/configota.py:lib/otampy/configota.py",
        )
    )

    assert [target for target, _source in files] == [
        "lib/otampy/boot.py",
        "lib/otampy/main.py",
        "lib/otampy/configota.py",
    ]


def test_get_files_to_send_expands_mapped_wildcard(tmp_path, monkeypatch):
    from otampy.cli import _get_files_to_send

    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    (source / "boot.py").write_text("# boot\n")
    (source / "main.py").write_text("# main\n")
    (source / "README.md").write_text("# docs\n")

    files = _get_files_to_send(("source/*.py:lib/otampy/",))

    assert [target for target, _source in files] == [
        "lib/otampy/boot.py",
        "lib/otampy/main.py",
    ]


def test_get_files_to_send_resolves_slash_source_from_project_root(
    tmp_path, monkeypatch
):
    from otampy.cli import _get_files_to_send

    project_root = tmp_path / "project"
    device = project_root / "device"
    device.mkdir(parents=True)
    (device / "main.py").write_text("# main\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "otampy.cli._detect_project_root", lambda: project_root
    )

    files = _get_files_to_send(("/device/*.py:/",), python_only=False)

    assert files == [("/main.py", device / "main.py")]


def test_get_files_to_send_defaults_to_saved_device_dir(tmp_path, monkeypatch):
    from otampy.cli import _get_files_to_send

    project_root = tmp_path / "project"
    device = project_root / "device"
    (device / "lib" / "nested").mkdir(parents=True)
    (project_root / "main.py").parent.mkdir(exist_ok=True)
    (project_root / "main.py").write_text("# project main\n")
    (device / "boot.py").write_text("# device boot\n")
    (device / "main.py").write_text("# device main\n")
    (device / "configota.py").write_text("# device config\n")
    helper = device / "lib" / "nested" / "helper.py"
    helper.write_text("# helper\n")
    monkeypatch.setattr(
        "otampy.cli._detect_project_root", lambda: project_root
    )
    monkeypatch.setattr(
        "otampy.cli.get_default_device_dir", lambda: str(device)
    )

    files = _get_files_to_send(())

    assert files == [
        ("boot.py", device / "boot.py"),
        ("main.py", device / "main.py"),
        ("configota.py", device / "configota.py"),
        ("lib/nested/helper.py", helper),
    ]


def test_get_files_to_send_all_files_uses_saved_device_dir(tmp_path, monkeypatch):
    from otampy.cli import _get_files_to_send

    device = tmp_path / "device"
    (device / "assets").mkdir(parents=True)
    (device / "main.py").write_text("# main\n")
    asset = device / "assets" / "settings.json"
    asset.write_text("{}\n")
    monkeypatch.setattr("otampy.cli.get_default_device_dir", lambda: str(device))

    files = _get_files_to_send((), all_files=True)

    assert files == [
        ("assets/settings.json", asset),
        ("main.py", device / "main.py"),
    ]


def test_cli_update_all_files_lists_and_confirms_before_connecting():
    runner = CliRunner()

    with (
        mock.patch(
            "otampy.cli._get_files_to_send",
            return_value=[("main.py", Path("/tmp/main.py"))],
        ),
        mock.patch("serial.Serial") as serial,
    ):
        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "upd", "--all-files"], input="n\n")

    assert result.exit_code == 0
    assert "The following files will be uploaded:" in result.output
    assert "main.py" in result.output
    assert "Cancelled." in result.output
    serial.assert_not_called()


def test_get_files_to_send_rejects_missing_explicit_sources(
    tmp_path, monkeypatch
):
    from otampy.cli import _get_files_to_send

    monkeypatch.chdir(tmp_path)
    (tmp_path / "boot.py").write_text("# boot\n")

    with pytest.raises(click.ClickException, match="main.py, configota.py"):
        _get_files_to_send(
            (
                "boot.py:lib/otampy/boot.py",
                "main.py:lib/otampy/main.py",
                "configota.py:lib/otampy/configota.py",
            )
        )


def test_get_files_to_send_copies_all_folder_files(tmp_path, monkeypatch):
    from otampy.cli import _get_files_to_send

    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "module.py").write_text("# module\n")
    (source / "data.json").write_text("{}\n")
    (source / "nested" / "payload.bin").write_bytes(b"payload")

    files = _get_files_to_send(
        ("source:assets/",),
        python_only=False,
    )

    assert [target for target, _source in files] == [
        "assets/data.json",
        "assets/module.py",
        "assets/nested/payload.bin",
    ]


def test_cli_cp_streams_multiple_files_without_reboot(tmp_path):
    runner = CliRunner()
    main = tmp_path / "main.py"
    data = tmp_path / "data.bin"
    main.write_bytes(b"print('replacement')\n")
    data.write_bytes(b"\x00\x01\x02")

    with (
        mock.patch(
            "otampy.cli._get_files_to_send",
            return_value=[
                ("main.py", main),
                ("lib/data.bin", data),
            ],
        ),
        mock.patch("serial.Serial") as serial,
        mock.patch("urst.Urst") as urst,
    ):
        transport = urst.return_value
        transport.read.side_effect = [
            b"CP_READY",
            b"CP_ACK:0",
            b"CP_OK",
            b"CP_READY",
            b"CP_ACK:0",
            b"CP_OK",
        ]

        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "cp", "ignored"],
        )

    assert result.exit_code == 0
    assert "Copied main.py successfully." in result.output
    assert "Copied lib/data.bin successfully." in result.output
    assert "Reboot required: /main.py" in result.output
    serial.assert_called_once_with("/dev/ttyFake", baudrate=57600, timeout=2.0)
    sent = [call.args[0] for call in transport.send.call_args_list]
    assert sum(command.startswith(b"CP_START:") for command in sent) == 2
    assert sent.count(b"CP_END") == 2
    assert b"RB" not in sent
    assert b"SR" not in sent


def test_cli_cp_omits_reboot_notice_for_non_boot_files(tmp_path):
    runner = CliRunner()
    source = tmp_path / "main.py"
    source.write_bytes(b"library main")

    with (
        mock.patch(
            "otampy.cli._get_files_to_send",
            return_value=[("lib/main.py", source)],
        ),
        mock.patch("serial.Serial"),
        mock.patch("urst.Urst") as urst,
    ):
        urst.return_value.read.side_effect = [
            b"CP_READY",
            b"CP_ACK:0",
            b"CP_OK",
        ]

        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "copy", "ignored"],
        )

    assert result.exit_code == 0
    assert "Reboot required" not in result.output


def test_cli_cp_aborts_active_transfer_on_device_error(tmp_path):
    runner = CliRunner()
    main = tmp_path / "main.py"
    main.write_bytes(b"replacement")
    source = tmp_path / "file.bin"
    source.write_bytes(b"content")

    with (
        mock.patch(
            "otampy.cli._get_files_to_send",
            return_value=[
                ("main.py", main),
                ("file.bin", source),
            ],
        ),
        mock.patch("serial.Serial"),
        mock.patch("urst.Urst") as urst,
    ):
        transport = urst.return_value
        transport.read.side_effect = [
            b"CP_READY",
            b"CP_ACK:0",
            b"CP_OK",
            b"CP_READY",
            b"ERROR:write failed",
            b"CP_ABORTED",
        ]

        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "cp", "ignored"],
        )

    assert result.exit_code != 0
    assert "write failed" in result.output
    assert "Reboot required: /main.py" in result.output
    sent = [call.args[0] for call in transport.send.call_args_list]
    assert sent[-1] == b"CP_ABORT"


def test_cli_aliases():
    """Test that aliases (e.g. 'update' for 'upd') work correctly."""
    runner = CliRunner(env={"NO_COLOR": "1"})
    with mock.patch("otampy.cli._get_files_to_send", return_value=[]):
        result = runner.invoke(
            cli, ["-p", "/dev/ttyFake", "update", ".", "main.py"]
        )
        assert result.exit_code == 0
        # Alias 'update' resolves to 'upd' command
        assert "No files found to transfer" in result.output


def test_cli_deploy_forwards_to_deploy_module():
    """Test that the Click deploy command forwards options to deploy.deploy()."""
    runner = CliRunner()
    with mock.patch("otampy.cli.deploy.deploy") as mock_deploy:
        result = runner.invoke(
            cli,
            [
                "deploy",
                "--port",
                "/dev/ttyACM0",
                "--bytecode",
                "--minify",
                "--mpy-cross",
                "uvx custom-cross",
                "--set-time",
                "--dry-run",
            ],
        )

    assert result.exit_code == 0
    mock_deploy.assert_called_once()  # type: ignore
    called_args = mock_deploy.call_args.args[0]  # type: ignore
    assert called_args.port == "/dev/ttyACM0"
    assert called_args.no_mip is False
    assert called_args.with_logger is False
    assert called_args.bytecode is True
    assert called_args.minify is True
    assert called_args.mpy_cross == "uvx custom-cross"
    assert called_args.no_reset is False
    assert called_args.set_time is True
    assert called_args.dry_run is True


def test_cli_deploy_reports_missing_mpremote_as_click_exception():
    """Test that a missing mpremote error becomes a ClickException."""
    runner = CliRunner()
    missing_file_error = FileNotFoundError("mpremote")

    with mock.patch("otampy.cli.deploy.deploy", side_effect=missing_file_error):
        result = runner.invoke(cli, ["deploy", "--dry-run"])

    assert result.exit_code != 0
    assert "Could not find" in result.output
    assert "Install mpremote" in result.output


def test_cli_update_handshake():
    """Test the update handshake sequence with mocked files."""
    runner = CliRunner()
    from pathlib import Path

    mock_files = [("test.py", Path("/tmp/test.py"))]
    mock_content = b"print('test')"

    class MockFile:
        def read(self):
            return mock_content

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with (
        mock.patch("serial.Serial") as _mock_serial,
        mock.patch("urst.Urst") as mock_device,
        mock.patch("time.sleep") as _mock_sleep,
        mock.patch("otampy.cli._get_files_to_send", return_value=mock_files),
        mock.patch("builtins.open", return_value=MockFile()),
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.side_effect = [
            b"REBOOTING",
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

        result = runner.invoke(
            cli,
            ["-p", "/dev/ttyFake", "upd", "--set-time"],
        )

        assert result.exit_code == 0
        assert "Initiating update handshake" in result.output
        assert (
            "Device acknowledged update request. Rebooting..." in result.output
        )
        assert "Device is READY. Handshake complete." in result.output
        mock_device_instance.send.assert_any_call(b"UPDATE_REQUEST")
        assert any(
            call.args[0].startswith(b"FILE_START:_otampy_set_rtc.py:")
            for call in mock_device_instance.send.call_args_list
        )


def test_cli_update_full_transfer():
    """Test full Click 'upd' command multi-file transfer sequence."""
    runner = CliRunner()
    from pathlib import Path

    mock_files = [
        ("main.py", Path("/tmp/main.py")),
        ("lib/helper.py", Path("/tmp/lib/helper.py")),
    ]

    payloads = {
        "/tmp/main.py": b"print('hello main')",
        "/tmp/lib/helper.py": b"print('hello lib')",
    }

    class MockFile:
        def __init__(self, path):
            self.content = payloads[str(path)]

        def read(self):
            return self.content

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def mock_open(path, mode="r"):
        if "b" in mode:
            return MockFile(path)
        return MockFile(path)

    with (
        mock.patch("serial.Serial") as _mock_serial,
        mock.patch("urst.Urst") as mock_device,
        mock.patch("time.sleep") as _mock_sleep,
        mock.patch(
            "otampy.cli._get_files_to_send",
            return_value=mock_files,
            create=True,
        ),
        mock.patch("builtins.open", side_effect=mock_open),
    ):
        mock_device_instance = mock_device.return_value

        # Expected responses:
        # 1. Handshake UPDATE_REQUEST -> REBOOTING
        # 2. Handshake Wait READY -> READY
        # 3. UPDATE_START -> SPACE_OK
        # 4. FILE_START (main) -> FILE_OK
        # 5. CHUNK 0 -> CHUNK_ACK:0
        # 6. FILE_END -> FILE_OK
        # 7. FILE_START (lib/helper) -> FILE_OK
        # 8. CHUNK 0 -> CHUNK_ACK:0
        # 9. FILE_END -> FILE_OK
        # 10. UPDATE_COMMIT -> COMMIT_OK
        mock_device_instance.read.side_effect = [
            b"REBOOTING",
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

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "upd"])

        assert result.exit_code == 0
        assert "Initiating update handshake" in result.output
        assert "Device is READY. Handshake complete." in result.output
        assert "Sending manifest" in result.output
        assert "Transferring main.py" in result.output
        assert "Transferring lib/helper.py" in result.output
        assert "Update completed successfully!" in result.output

        # Verify command sequencing sent to device
        mock_device_instance.send.assert_any_call(b"UPDATE_REQUEST")
        mock_device_instance.send.assert_any_call(b"UPDATE_START:2:37")
        mock_device_instance.send.assert_any_call(b"UPDATE_COMMIT")


def test_cli_update_aborts_before_commit_on_transfer_failure():
    runner = CliRunner()
    source = Path("/tmp/main.py")

    class MockFile:
        def read(self):
            return b"print('replacement')"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with (
        mock.patch("serial.Serial"),
        mock.patch("urst.Urst") as urst,
        mock.patch("time.sleep"),
        mock.patch(
            "otampy.cli._get_files_to_send",
            return_value=[("main.py", source)],
        ),
        mock.patch("builtins.open", return_value=MockFile()),
    ):
        transport = urst.return_value
        transport.read.side_effect = [
            b"REBOOTING",
            b"READY",
            b"SPACE_OK",
            None,
            b"UPDATE_ABORTED",
        ]

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "upd"])

    assert result.exit_code != 0
    sent = [call.args[0] for call in transport.send.call_args_list]
    assert b"UPDATE_ABORT" in sent
    assert b"UPDATE_COMMIT" not in sent


def test_cli_query_connection_retry():
    """Test that _query connection handler retries opening Serial when busy."""
    runner = CliRunner()
    import serial

    # Mock Serial to fail twice, then succeed
    call_count = 0

    def mock_serial_init(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise serial.SerialException("Port busy")
        # Return mock serial instance on third attempt
        return mock.MagicMock()

    with (
        mock.patch("serial.Serial", side_effect=mock_serial_init),
        mock.patch("urst.Urst") as mock_device,
        mock.patch("time.sleep") as mock_sleep,
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"PONG"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "ping"])

        assert result.exit_code == 0
        assert "Sending PING to device" in result.output
        assert "Success: Received PONG from device" in result.output

        # Serial should have been called 3 times
        assert call_count == 3
        # Should have slept twice (exponential backoff)
        assert mock_sleep.call_count == 2


def test_cli_port_interactive(tmp_path):
    runner = CliRunner(env={"NO_COLOR": "1"})

    # Mock comports
    mock_port1 = mock.MagicMock()
    mock_port1.device = "/dev/ttyFake1"
    mock_port1.description = "Fake Port 1"
    mock_port1.serial_number = "SERIAL1"
    mock_port1.vid = 0x2E8A
    mock_port1.pid = 0x0005
    mock_port1.manufacturer = "MicroPython"
    mock_port1.product = "Board in FS mode"

    mock_port2 = mock.MagicMock()
    mock_port2.device = "/dev/ttyFake2"
    mock_port2.description = "Fake Port 2"
    mock_port2.serial_number = "SERIAL2"
    mock_port2.vid = 0x0403
    mock_port2.pid = 0x6001
    mock_port2.manufacturer = "FTDI"
    mock_port2.product = "FT232R USB UART"

    with (
        mock.patch(
            "serial.tools.list_ports.comports",
            return_value=[mock_port1, mock_port2],
        ),
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch(
            "otampy.cli._detect_project_root",
            return_value=Path("/fake/project"),
        ),
    ):
        fake_root = "/fake/project"

        # 1. Interactive choice: select 1 (ttyFake1), then select permanent 'p'
        result = runner.invoke(cli, ["ports"], input="1\np\n")
        plain = _ANSI_ESCAPE.sub("", result.output)
        assert result.exit_code == 0
        assert "Available serial ports:" in plain
        assert (
            "1: /dev/ttyFake1 SERIAL1 2e8a:0005 MicroPython Board in FS mode"
        ) in plain
        assert "Permanent default port set to: /dev/ttyFake1" in plain

        # Verify file config.json exists and has correct default_port value
        config_file = tmp_path / ".config" / "otampy" / "config.json"
        assert config_file.is_file()

        with open(config_file) as f:
            assert (
                json.load(f)["projects"][fake_root]["default_port"]
                == "/dev/ttyFake1"
            )

        # The effective selected port is marked, including a --port override.
        result = runner.invoke(
            cli,
            ["--port", "/dev/ttyFake2", "ports"],
            input="\n",
        )
        plain = _ANSI_ESCAPE.sub("", result.output)
        assert result.exit_code == 0
        assert (
            "    1: /dev/ttyFake1 SERIAL1 2e8a:0005 MicroPython Board in FS mode"
        ) in plain
        assert (
            "  * 2: /dev/ttyFake2 SERIAL2 0403:6001 FTDI FT232R USB UART"
        ) in plain

        # 2. Interactive choice: select 2, select session 's'
        result = runner.invoke(cli, ["ports"], input="2\ns\n")
        assert result.exit_code == 0
        assert "Session default port set to: /dev/ttyFake2" in result.output

        # 3. Test non-interactive options: show, set, clear
        result_show = runner.invoke(cli, ["ports", "--show"])
        assert result_show.exit_code == 0
        assert "Current default port: /dev/ttyFake2" in result_show.output

        result_clear = runner.invoke(cli, ["ports", "--clear"])
        assert result_clear.exit_code == 0
        assert "Default ports cleared." in result_clear.output
        assert not config_file.is_file()

        result_set = runner.invoke(cli, ["ports", "--set", "/dev/ttyFakeX"])
        assert result_set.exit_code == 0
        assert (
            "Permanent default port set to: /dev/ttyFakeX" in result_set.output
        )
        with open(config_file) as f:
            assert (
                json.load(f)["projects"][fake_root]["default_port"]
                == "/dev/ttyFakeX"
            )


def test_permanent_port_clears_session_shadow(tmp_path):
    """Saving a port permanently must clear any session port so it no longer
    shadows the permanent config on the next invocation."""
    runner = CliRunner()

    mock_port1 = mock.MagicMock()
    mock_port1.device = "/dev/ttyFake1"
    mock_port1.description = "Fake Port 1"
    mock_port1.serial_number = "SERIAL1"
    mock_port1.vid = 0x2E8A
    mock_port1.pid = 0x0005
    mock_port1.manufacturer = "MicroPython"
    mock_port1.product = "Board in FS mode"
    mock_port1.hwid = "USB"

    mock_port2 = mock.MagicMock()
    mock_port2.device = "/dev/ttyFake2"
    mock_port2.description = "Fake Port 2"
    mock_port2.serial_number = "SERIAL2"
    mock_port2.vid = 0x0403
    mock_port2.pid = 0x6001
    mock_port2.manufacturer = "FTDI"
    mock_port2.product = "FT232R USB UART"
    mock_port2.hwid = "USB"

    fake_ppid = 99999
    fake_root = "/fake/project"
    session_file = tmp_path / f"otampy_session_{fake_ppid}.json"

    with (
        mock.patch(
            "serial.tools.list_ports.comports",
            return_value=[mock_port1, mock_port2],
        ),
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=fake_ppid),
        mock.patch(
            "otampy.cli._detect_project_root", return_value=Path(fake_root)
        ),
    ):
        # Step 1: Save ttyFake2 as the session port.
        result = runner.invoke(cli, ["ports"], input="2\ns\n")
        assert result.exit_code == 0
        assert "Session default port set to: /dev/ttyFake2" in result.output
        assert session_file.is_file()
        assert (
            json.loads(session_file.read_text()).get("default_port")
            == "/dev/ttyFake2"
        )

        # Step 2: Save ttyFake1 permanently — must also clear the session shadow.
        result = runner.invoke(cli, ["ports"], input="1\np\n")
        assert result.exit_code == 0
        assert "Permanent default port set to: /dev/ttyFake1" in result.output

        # Session file must no longer carry default_port.
        if session_file.exists():
            assert "default_port" not in json.loads(session_file.read_text()), (
                "Session file was not cleared when saving permanent port."
            )

        # Permanent config must have ttyFake1 under the project key.
        config_file = tmp_path / ".config" / "otampy" / "config.json"
        assert config_file.is_file()
        with open(config_file) as f:
            assert (
                json.load(f)["projects"][fake_root]["default_port"]
                == "/dev/ttyFake1"
            )

        # Step 3: get_default_port() must return ttyFake1, not ttyFake2.
        result = runner.invoke(cli, ["ports"], input="\n")
        assert result.exit_code == 0
        assert "* 1: /dev/ttyFake1" in result.output
        assert "* 2: /dev/ttyFake2" not in result.output

        # Step 3: On the next invocation (no --port flag), get_default_port()
        # must return ttyFake1 (permanent), not ttyFake2 (cleared session).
        # The * marker must appear next to ttyFake1.
        result = runner.invoke(cli, ["ports"], input="\n")
        assert result.exit_code == 0
        assert "* 1: /dev/ttyFake1" in result.output
        assert "* 2: /dev/ttyFake2" not in result.output


def test_ports_set_flag_clears_session_shadow(tmp_path):
    """--set flag saving a permanent port must also clear the session shadow."""
    runner = CliRunner()

    fake_ppid = 99998
    fake_root = "/fake/project"
    session_file = tmp_path / f"otampy_session_{fake_ppid}.json"

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=fake_ppid),
        mock.patch(
            "otampy.cli._detect_project_root", return_value=Path(fake_root)
        ),
    ):
        # Plant a session JSON file with ttyFake2 as the port.
        session_file.write_text(json.dumps({"default_port": "/dev/ttyFake2"}))
        assert session_file.is_file()

        # Use --set to permanently set ttyFake1.
        result = runner.invoke(cli, ["ports", "--set", "/dev/ttyFake1"])
        assert result.exit_code == 0
        assert "Permanent default port set to: /dev/ttyFake1" in result.output

        # Session file must no longer carry default_port.
        if session_file.exists():
            assert "default_port" not in json.loads(session_file.read_text()), (
                "--set did not clear the session port shadow."
            )

        # Permanent config must have ttyFake1 under the project key.
        config_file = tmp_path / ".config" / "otampy" / "config.json"
        with open(config_file) as f:
            assert (
                json.load(f)["projects"][fake_root]["default_port"]
                == "/dev/ttyFake1"
            )


def test_device_dir_set_creates_missing_directory(tmp_path):
    runner = CliRunner()
    fake_ppid = 99997
    project_root = tmp_path / "project"
    project_root.mkdir()
    session_file = tmp_path / f"otampy_session_{fake_ppid}.json"
    session_file.write_text(
        json.dumps({"device_dir": str(project_root / "old")})
    )

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=fake_ppid),
        mock.patch(
            "otampy.cli._detect_project_root", return_value=project_root
        ),
    ):
        result = runner.invoke(
            cli, ["device-dir", "--set", "/xyz"], input="y\n"
        )

    assert result.exit_code == 0
    assert (project_root / "xyz").is_dir()
    assert "Permanent device directory set to: /xyz" in result.output

    config_file = tmp_path / ".config" / "otampy" / "config.json"
    saved = json.loads(config_file.read_text())
    assert saved["projects"][str(project_root)]["device_dir"] == "xyz"
    if session_file.exists():
        assert "device_dir" not in json.loads(session_file.read_text())


def test_device_dir_set_does_not_save_when_creation_declined(tmp_path):
    runner = CliRunner()
    project_root = tmp_path / "project"
    project_root.mkdir()

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=99996),
        mock.patch(
            "otampy.cli._detect_project_root", return_value=project_root
        ),
    ):
        result = runner.invoke(
            cli, ["device-dir", "--set", "/xyz"], input="n\n"
        )

    assert result.exit_code == 0
    assert not (project_root / "xyz").exists()
    assert "Cancelled." in result.output
    assert not (tmp_path / ".config" / "otampy" / "config.json").exists()


def test_device_dir_interactive_creates_missing_directory_and_saves_session(
    tmp_path,
):
    runner = CliRunner()
    fake_ppid = 99995
    project_root = tmp_path / "project"
    project_root.mkdir()

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=fake_ppid),
        mock.patch(
            "otampy.cli._detect_project_root", return_value=project_root
        ),
    ):
        result = runner.invoke(
            cli, ["device-dir"], input="/nested/device\ny\ns\n"
        )

    assert result.exit_code == 0
    created = project_root / "nested" / "device"
    assert created.is_dir()
    assert "Session device directory set to: /nested/device" in result.output

    session_file = tmp_path / f"otampy_session_{fake_ppid}.json"
    assert json.loads(session_file.read_text())["device_dir"] == str(created)


def test_device_dir_set_rejects_existing_file(tmp_path):
    runner = CliRunner()
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "not-a-dir").write_text("content")

    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=99994),
        mock.patch(
            "otampy.cli._detect_project_root", return_value=project_root
        ),
    ):
        result = runner.invoke(cli, ["device-dir", "--set", "/not-a-dir"])

    assert result.exit_code != 0
    assert "Device directory is not a directory" in result.output
