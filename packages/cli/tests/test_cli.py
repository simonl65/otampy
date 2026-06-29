import time
import unittest.mock as mock

from click.testing import CliRunner

from otampy.cli import cli


def test_cli_help():
    """Test that running cli with -h, --help, or h displays help."""
    runner = CliRunner()

    # Test --help
    result_help = runner.invoke(cli, ["--help"])
    assert result_help.exit_code == 0
    assert (
        "Show this message and exit." in result_help.output
        or "Show helpful information" in result_help.output
    )

    # Test -h
    result_h_opt = runner.invoke(cli, ["-h"])
    assert result_h_opt.exit_code == 0
    assert (
        "Show this message and exit." in result_h_opt.output
        or "Show helpful information" in result_h_opt.output
    )

    # Test 'h' command
    result_h_cmd = runner.invoke(cli, ["h"])
    assert result_h_cmd.exit_code == 0
    assert "Show helpful information" in result_h_cmd.output


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


def test_cli_bootloader():
    """Test the 'bl' command (reboot into bootloader) with confirmation."""
    runner = CliRunner()
    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"BL_OK"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "bl"], input="y\n")
        assert result.exit_code == 0
        assert "Rebooting device into bootloader mode" in result.output
        mock_serial.assert_called_once_with(
            "/dev/ttyFake", baudrate=57600, timeout=2.0
        )
        mock_device_instance.send.assert_called_once_with(b"BL")


def test_cli_bootloader_aborted():
    """Test that the 'bl' command defaults to aborting when not confirmed."""
    runner = CliRunner()
    with (
        mock.patch("serial.Serial") as mock_serial,
        mock.patch("urst.Urst") as mock_device,
    ):
        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "bl"], input="\n")
        assert result.exit_code == 0
        assert "Aborted." in result.output
        mock_serial.assert_not_called()
        mock_device.assert_not_called()


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


def test_cli_command_missing_port():
    """Test that running connection commands without -p raises an error."""
    runner = CliRunner()
    result = runner.invoke(cli, ["ping"])
    assert result.exit_code != 0
    assert "Error: Missing serial port" in result.output


def test_cli_ls_default():
    """Test the 'ls' command without paths."""
    runner = CliRunner()
    with mock.patch("serial.Serial") as mock_serial, mock.patch(
        "urst.Urst"
    ) as mock_device:
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


def test_cli_ls_path():
    """Test the 'ls' command with a specific path."""
    runner = CliRunner(env={"NO_COLOR": "1"})
    with mock.patch("serial.Serial") as mock_serial, mock.patch(
        "urst.Urst"
    ) as mock_device:
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
    with mock.patch("serial.Serial") as mock_serial, mock.patch(
        "urst.Urst"
    ) as mock_device:
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


def test_cli_rm_file():
    """Test the 'rm' command with a file with confirmation."""
    runner = CliRunner()
    with mock.patch("serial.Serial") as mock_serial, mock.patch(
        "urst.Urst"
    ) as mock_device:
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"RM_OK"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "rm", "main.py"], input="y\n")
        assert result.exit_code == 0
        assert "Removing file: main.py" in result.output
        mock_serial.assert_called_once_with(
            "/dev/ttyFake", baudrate=57600, timeout=2.0
        )
        mock_device_instance.send.assert_called_once_with(b"RM:main.py")


def test_cli_rm_file_aborted():
    """Test that 'rm' command defaults to aborting when not confirmed."""
    runner = CliRunner()
    with mock.patch("serial.Serial") as mock_serial, mock.patch(
        "urst.Urst"
    ) as mock_device:
        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "rm", "main.py"], input="\n")
        assert result.exit_code == 0
        assert "Aborted." in result.output
        mock_serial.assert_not_called()
        mock_device.assert_not_called()


def test_cli_mem():
    """Test the 'mem' command."""
    runner = CliRunner()
    with mock.patch("serial.Serial") as mock_serial, mock.patch(
        "urst.Urst"
    ) as mock_device:
        mock_device_instance = mock_device.return_value
        # ram_free, ram_alloc, flash_free, flash_total
        mock_device_instance.read.return_value = b"MEM_OK:50000,30000,524288,1048576"

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

    # 1. LS command with ENOENT error
    with mock.patch("serial.Serial"), mock.patch("urst.Urst") as mock_device:
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"ERROR:[Errno 2] ENOENT"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "ls", "lib/Boot.py"])
        assert result.exit_code == 1
        assert "Device error: No such file or directory: 'lib/Boot.py'" in result.output

    # 2. CAT command with ENOENT error
    with mock.patch("serial.Serial"), mock.patch("urst.Urst") as mock_device:
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"ERROR:ENOENT"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "cat", "missing.py"])
        assert result.exit_code == 1
        assert "Device error: No such file or directory: 'missing.py'" in result.output

    # 3. RM command with EACCES error
    with mock.patch("serial.Serial"), mock.patch("urst.Urst") as mock_device:
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"ERROR:[Errno 13] EACCES"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "rm", "system.py"], input="y\n")
        assert result.exit_code == 1
        assert "Device error: Permission denied: 'system.py'" in result.output

    # 4. CAT command on directory (EISDIR)
    with mock.patch("serial.Serial"), mock.patch("urst.Urst") as mock_device:
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.return_value = b"ERROR:EISDIR"

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "cat", "lib"])
        assert result.exit_code == 1
        assert "Device error: Is a directory: 'lib/'" in result.output


def test_cli_update_default():
    """Test 'upd' command without parameters (update all firmware)."""
    runner = CliRunner()
    with mock.patch("serial.Serial") as _mock_serial, mock.patch(
        "urst.Urst"
    ) as mock_device, mock.patch("time.sleep") as _mock_sleep:
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.side_effect = [b"REBOOTING", b"READY"]

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "upd"])
        assert result.exit_code == 0
        assert "Initiating update handshake" in result.output
        assert "Device is READY. Handshake complete." in result.output


def test_cli_update_with_files():
    """Test 'upd' command with specific files/paths."""
    runner = CliRunner(env={"NO_COLOR": "1"})
    with mock.patch("serial.Serial") as _mock_serial, mock.patch(
        "urst.Urst"
    ) as mock_device, mock.patch(
        "time.sleep"
    ) as _mock_sleep, mock.patch(
        "otampy.cli._get_files_to_send", return_value=[], create=True
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.side_effect = [b"REBOOTING", b"READY"]

        result = runner.invoke(
            cli, ["-p", "/dev/ttyFake", "upd", ".", "main.py", "lib/lib2.py"]
        )
        assert result.exit_code == 0
        assert "Initiating update handshake" in result.output
        assert "Device is READY. Handshake complete." in result.output


def test_cli_aliases():
    """Test that aliases (e.g. 'update' for 'upd') work correctly."""
    runner = CliRunner(env={"NO_COLOR": "1"})
    with mock.patch("serial.Serial") as _mock_serial, mock.patch(
        "urst.Urst"
    ) as mock_device, mock.patch(
        "time.sleep"
    ) as _mock_sleep, mock.patch(
        "otampy.cli._get_files_to_send", return_value=[], create=True
    ):
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.side_effect = [b"REBOOTING", b"READY"]

        result = runner.invoke(
            cli, ["-p", "/dev/ttyFake", "update", ".", "main.py"]
        )
        assert result.exit_code == 0
        assert "Initiating update handshake" in result.output
        assert "Device is READY. Handshake complete." in result.output


def test_cli_deploy_forwards_to_deploy_module():
    """Test that the Click deploy command forwards options to deploy.deploy()."""
    runner = CliRunner()
    with mock.patch("otampy.cli.deploy.deploy") as mock_deploy:
        result = runner.invoke(
            cli, ["deploy", "--port", "/dev/ttyACM0", "--no-mip", "--dry-run"]
        )

    assert result.exit_code == 0
    mock_deploy.assert_called_once()  # type: ignore
    called_args = mock_deploy.call_args.args[0]  # type: ignore
    assert called_args.port == "/dev/ttyACM0"
    assert called_args.no_mip is True
    assert called_args.no_reset is False
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
    """Test the update handshake sequence."""
    runner = CliRunner()
    with mock.patch("serial.Serial") as _mock_serial, mock.patch(
        "urst.Urst"
    ) as mock_device, mock.patch("time.sleep") as _mock_sleep:
        mock_device_instance = mock_device.return_value
        mock_device_instance.read.side_effect = [b"REBOOTING", b"READY"]

        result = runner.invoke(cli, ["-p", "/dev/ttyFake", "upd"])

        assert result.exit_code == 0
        assert "Initiating update handshake" in result.output
        assert "Device acknowledged update request. Rebooting..." in result.output
        assert "Device is READY. Handshake complete." in result.output
        mock_device_instance.send.assert_any_call(b"UPDATE_REQUEST")


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

    with mock.patch("serial.Serial") as _mock_serial, mock.patch(
        "urst.Urst"
    ) as mock_device, mock.patch(
        "time.sleep"
    ) as _mock_sleep, mock.patch(
        "otampy.cli._get_files_to_send", return_value=mock_files, create=True
    ), mock.patch(
        "builtins.open", side_effect=mock_open
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

    with mock.patch("serial.Serial", side_effect=mock_serial_init), mock.patch(
        "urst.Urst"
    ) as mock_device, mock.patch("time.sleep") as mock_sleep:
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
    runner = CliRunner()

    # Mock comports
    mock_port1 = mock.MagicMock()
    mock_port1.device = "/dev/ttyFake1"
    mock_port1.description = "Fake Port 1"

    mock_port2 = mock.MagicMock()
    mock_port2.device = "/dev/ttyFake2"
    mock_port2.description = "Fake Port 2"

    with (
        mock.patch("serial.tools.list_ports.comports", return_value=[mock_port1, mock_port2]),
        mock.patch("pathlib.Path.home", return_value=tmp_path),
    ):
        # 1. Interactive choice: select 1 (ttyFake1), then select permanent 'y'
        result = runner.invoke(cli, ["port"], input="1\ny\n")
        assert result.exit_code == 0
        assert "Available serial ports:" in result.output
        assert "1: /dev/ttyFake1 (Fake Port 1)" in result.output
        assert "Permanent default port set to: /dev/ttyFake1" in result.output

        # Verify file config.json exists and has correct default_port value
        config_file = tmp_path / ".config" / "otampy" / "config.json"
        assert config_file.is_file()
        import json
        with open(config_file) as f:
            assert json.load(f)["default_port"] == "/dev/ttyFake1"

        # 2. Interactive choice: select 2, select session 'n'
        result = runner.invoke(cli, ["port"], input="2\nn\n")
        assert result.exit_code == 0
        assert "To set this default for the current terminal session, run:" in result.output
        assert "export OTAMPY_PORT=/dev/ttyFake2" in result.output

        # 3. Test non-interactive options: show, set, clear
        result_show = runner.invoke(cli, ["port", "--show"])
        assert result_show.exit_code == 0
        assert "Current default port: /dev/ttyFake1" in result_show.output

        result_clear = runner.invoke(cli, ["port", "--clear"])
        assert result_clear.exit_code == 0
        assert "Permanent default port cleared." in result_clear.output
        assert not config_file.is_file()

        result_set = runner.invoke(cli, ["port", "--set", "/dev/ttyFakeX"])
        assert result_set.exit_code == 0
        assert "Permanent default port set to: /dev/ttyFakeX" in result_set.output
        with open(config_file) as f:
            assert json.load(f)["default_port"] == "/dev/ttyFakeX"
