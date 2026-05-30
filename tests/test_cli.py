import pytest
from click.testing import CliRunner
from otampy.OTAmpy import cli

def test_cli_help():
    """Test that running cli with -h, --help, or h displays help."""
    runner = CliRunner()
    
    # Test --help
    result_help = runner.invoke(cli, ["--help"])
    assert result_help.exit_code == 0
    assert "Show this message and exit." in result_help.output or "Show helpful information" in result_help.output

    # Test -h
    result_h_opt = runner.invoke(cli, ["-h"])
    assert result_h_opt.exit_code == 0
    assert "Show this message and exit." in result_h_opt.output or "Show helpful information" in result_h_opt.output

    # Test 'h' command
    result_h_cmd = runner.invoke(cli, ["h"])
    assert result_h_cmd.exit_code == 0
    assert "Show helpful information" in result_h_cmd.output

def test_cli_bootloader():
    """Test the 'bl' command (reboot into bootloader)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["bl"])
    assert result.exit_code == 0
    assert "Rebooting device into bootloader mode" in result.output

def test_cli_hard_reboot():
    """Test the 'rb' command (hard reboot)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["rb"])
    assert result.exit_code == 0
    assert "Hard rebooting the device" in result.output

def test_cli_soft_reset():
    """Test the 'sr' command (soft reset)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["sr"])
    assert result.exit_code == 0
    assert "Soft resetting the device" in result.output

def test_cli_ls_default():
    """Test the 'ls' command without paths."""
    runner = CliRunner()
    result = runner.invoke(cli, ["ls"])
    assert result.exit_code == 0
    assert "Listing content of" in result.output

def test_cli_ls_path():
    """Test the 'ls' command with a specific path."""
    runner = CliRunner()
    result = runner.invoke(cli, ["ls", "/lib"])
    assert result.exit_code == 0
    assert "Listing content of /lib" in result.output

def test_cli_cat_missing_arg():
    """Test that 'cat' without required file argument fails."""
    runner = CliRunner()
    result = runner.invoke(cli, ["cat"])
    assert result.exit_code != 0
    assert "Error: Missing argument" in result.output

def test_cli_cat_file():
    """Test the 'cat' command with a file."""
    runner = CliRunner()
    result = runner.invoke(cli, ["cat", "boot.py"])
    assert result.exit_code == 0
    assert "Showing content of specified file: boot.py" in result.output

def test_cli_rm_missing_arg():
    """Test that 'rm' without required file argument fails."""
    runner = CliRunner()
    result = runner.invoke(cli, ["rm"])
    assert result.exit_code != 0
    assert "Error: Missing argument" in result.output

def test_cli_rm_file():
    """Test the 'rm' command with a file."""
    runner = CliRunner()
    result = runner.invoke(cli, ["rm", "main.py"])
    assert result.exit_code == 0
    assert "Removing file: main.py" in result.output

def test_cli_update_default():
    """Test 'upd' command without parameters (update all firmware)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["upd"])
    assert result.exit_code == 0
    assert "Updating all application firmware" in result.output

def test_cli_update_with_files():
    """Test 'upd' command with specific files/paths."""
    runner = CliRunner()
    result = runner.invoke(cli, ["upd", ".", "main.py", "lib/lib2.py"])
    assert result.exit_code == 0
    assert "Updating firmware with arguments: ('.', 'main.py', 'lib/lib2.py')" in result.output

def test_cli_aliases():
    """Test that aliases (e.g. 'update' for 'upd') work correctly."""
    runner = CliRunner()
    result = runner.invoke(cli, ["update", ".", "main.py"])
    assert result.exit_code == 0
    assert "Updating firmware with arguments: ('.', 'main.py')" in result.output
