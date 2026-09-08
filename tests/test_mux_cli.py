"""Channel-mux CLI mode — see docs/development/channel-mux-cli-mode-spec.md."""

import json
import unittest.mock as mock
from contextlib import contextmanager

import click
import pytest
from click.testing import CliRunner

from otampy.cli import cli, get_mux_enabled, set_mux_enabled


@contextmanager
def _isolated_config(tmp_path, ppid=7777, env=None):
    """Point every config location at tmp_path and control OTAMPY_MUX."""
    with (
        mock.patch("pathlib.Path.home", return_value=tmp_path),
        mock.patch("tempfile.gettempdir", return_value=str(tmp_path)),
        mock.patch("os.getppid", return_value=ppid),
        mock.patch("otampy.cli._detect_project_root", return_value=tmp_path),
        mock.patch.dict("os.environ", {}, clear=False),
    ):
        import os

        os.environ.pop("OTAMPY_MUX", None)
        for key, value in (env or {}).items():
            os.environ[key] = value
        yield


class TestMuxSetting:
    def test_default_is_false(self, tmp_path):
        with _isolated_config(tmp_path):
            assert get_mux_enabled() is False

    def test_project_setting_round_trips(self, tmp_path):
        with _isolated_config(tmp_path):
            set_mux_enabled(True)
            assert get_mux_enabled() is True
            config = json.loads(
                (tmp_path / ".config" / "otampy" / "config.json").read_text()
            )
            assert config["projects"][str(tmp_path)]["mux"] is True

    def test_session_setting_beats_project(self, tmp_path):
        with _isolated_config(tmp_path):
            set_mux_enabled(True)  # project
            set_mux_enabled(False, session=True)  # session
            assert get_mux_enabled() is False

    def test_env_beats_saved_setting(self, tmp_path):
        with _isolated_config(tmp_path):
            set_mux_enabled(False)
        with _isolated_config(tmp_path, env={"OTAMPY_MUX": "1"}):
            assert get_mux_enabled() is True

    @pytest.mark.parametrize(
        "token, expected",
        [
            ("1", True),
            ("true", True),
            ("YES", True),
            ("on", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("off", False),
            ("", False),
        ],
    )
    def test_env_token_parsing(self, tmp_path, token, expected):
        with _isolated_config(tmp_path, env={"OTAMPY_MUX": token}):
            assert get_mux_enabled() is expected

    def test_invalid_env_token_raises(self, tmp_path):
        with (
            _isolated_config(tmp_path, env={"OTAMPY_MUX": "maybe"}),
            pytest.raises(click.ClickException),
        ):
            get_mux_enabled()

    def test_clear_removes_project_and_session(self, tmp_path):
        with _isolated_config(tmp_path):
            set_mux_enabled(True)
            set_mux_enabled(True, session=True)
            set_mux_enabled(None)
            set_mux_enabled(None, session=True)
            assert get_mux_enabled() is False


class TestMuxFlag:
    def _run(self, tmp_path, args):
        with (
            mock.patch("serial.Serial"),
            mock.patch("urst.Urst") as urst,
            _isolated_config(tmp_path),
        ):
            urst.return_value.read.return_value = b"PONG"
            return CliRunner().invoke(cli, args)

    def test_mux_flag_parses(self, tmp_path):
        result = self._run(tmp_path, ["-p", "/dev/ttyFake", "--mux", "ping"])
        assert result.exit_code == 0

    def test_no_mux_flag_parses(self, tmp_path):
        result = self._run(tmp_path, ["-p", "/dev/ttyFake", "--no-mux", "ping"])
        assert result.exit_code == 0
