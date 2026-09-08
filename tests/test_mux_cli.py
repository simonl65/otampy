"""Channel-mux CLI mode — see docs/development/channel-mux-cli-mode-spec.md."""

import json
import unittest.mock as mock
from contextlib import contextmanager

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

    def test_invalid_env_token_is_ignored_with_warning(self, tmp_path, capsys):
        # A typo in OTAMPY_MUX must NOT raise -- that would block every command,
        # including the `otampy mux` command needed to fix it (F-03).
        with _isolated_config(tmp_path):
            set_mux_enabled(True)  # project config says on
        with _isolated_config(tmp_path, env={"OTAMPY_MUX": "maybe"}):
            assert get_mux_enabled() is True  # falls through to config
        assert "ignoring OTAMPY_MUX='maybe'" in capsys.readouterr().err

    def test_invalid_env_falls_through_to_default(self, tmp_path):
        with _isolated_config(tmp_path, env={"OTAMPY_MUX": "maybe"}):
            assert get_mux_enabled() is False

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


class TestMuxWiring:
    def test_mux_on_wraps_serial_in_channelserial(self, tmp_path):
        from otampy.channel import ChannelSerial

        with (
            mock.patch("serial.Serial") as mock_serial,
            mock.patch("urst.Urst") as urst,
            _isolated_config(tmp_path),
        ):
            urst.return_value.read.return_value = b"PONG"
            result = CliRunner().invoke(
                cli, ["-p", "/dev/ttyFake", "--mux", "ping"]
            )

        assert result.exit_code == 0
        port_obj = urst.call_args[0][0]
        assert isinstance(port_obj, ChannelSerial)
        assert port_obj._ser is mock_serial.return_value

    def test_mux_off_passes_raw_serial(self, tmp_path):
        with (
            mock.patch("serial.Serial") as mock_serial,
            mock.patch("urst.Urst") as urst,
            _isolated_config(tmp_path),
        ):
            urst.return_value.read.return_value = b"PONG"
            result = CliRunner().invoke(cli, ["-p", "/dev/ttyFake", "ping"])

        assert result.exit_code == 0
        assert urst.call_args[0][0] is mock_serial.return_value

    def test_mux_ping_roundtrip_returns_pong(self, tmp_path):
        """End-to-end: CLI `--mux ping` against a real Urst mux device."""
        import threading

        from test_channel import _cross_pipe
        from urst.core_handler import Urst

        from otampy.channel import ChannelSerial

        host_raw, dev_raw = _cross_pipe()
        errors = []

        def device():
            try:
                dev = Urst(ChannelSerial(dev_raw), timeout=1.0)
                for _ in range(50):
                    if dev.read() == b"PING":
                        dev.reply(b"PONG")
                        return
                errors.append("no PING seen")
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        t = threading.Thread(target=device, daemon=True)
        t.start()
        with (
            # The device test-suite conftest swaps sys.modules["urst"] for a
            # fake; pin the CLI's `from urst import Urst` back to the real one.
            mock.patch("urst.Urst", Urst),
            mock.patch("serial.Serial", return_value=host_raw),
            _isolated_config(tmp_path),
        ):
            result = CliRunner().invoke(
                cli, ["-p", "/dev/ttyFake", "--mux", "ping"]
            )
        t.join(timeout=10)

        assert result.exit_code == 0, result.output
        assert "Received PONG" in result.output
        assert errors == []

    def test_mux_against_direct_device_times_out_cleanly(self, tmp_path):
        """One-sided mismatch: --mux host, unframed device -> clean timeout."""
        from urst.core_handler import Urst

        class _DirectFake:
            """Replies with raw (un-mux-framed) bytes."""

            def __init__(self):
                self.rx = bytearray(b"\x00PONG\x00")

            def write(self, data):
                return len(data)

            def flush(self):
                pass

            @property
            def in_waiting(self):
                return len(self.rx)

            def read(self, n=1):
                out = bytes(self.rx[:n])
                self.rx = self.rx[n:]
                return out

            def reset_input_buffer(self):
                self.rx = bytearray()

            def reset_output_buffer(self):
                pass

            def close(self):
                pass

        with (
            mock.patch("urst.Urst", Urst),
            mock.patch("serial.Serial", return_value=_DirectFake()),
            _isolated_config(
                tmp_path,
                env={
                    "OTAMPY_QUERY_RETRIES": "1",
                    "OTAMPY_SERIAL_TIMEOUT": "0.1",
                },
            ),
        ):
            result = CliRunner().invoke(
                cli, ["-p", "/dev/ttyFake", "--mux", "ping"]
            )

        # A one-sided mismatch fails cleanly (non-zero, no traceback) -- the
        # host never completes the URST handshake through the outer frame.
        assert result.exit_code != 0
        assert result.exception is None or isinstance(
            result.exception, SystemExit
        )
        assert any(
            msg in result.output
            for msg in (
                "Timeout waiting for response",
                "Failed to send command over transport",
            )
        )


class TestMuxCommand:
    def _run(self, tmp_path, args, env=None, stdin=None):
        with _isolated_config(tmp_path, env=env):
            return CliRunner().invoke(cli, ["mux", *args], input=stdin)

    def test_show_default_reports_direct(self, tmp_path):
        result = self._run(tmp_path, ["--show"])
        assert result.exit_code == 0
        assert "direct" in result.output.lower()

    def test_enable_then_show_reports_project(self, tmp_path):
        assert self._run(tmp_path, ["--enable"]).exit_code == 0
        result = self._run(tmp_path, ["--show"])
        assert result.exit_code == 0
        out = result.output.lower()
        assert "mux" in out and "project" in out

    def test_disable(self, tmp_path):
        self._run(tmp_path, ["--enable"])
        assert self._run(tmp_path, ["--disable"]).exit_code == 0
        with _isolated_config(tmp_path):
            assert get_mux_enabled() is False

    def test_clear(self, tmp_path):
        self._run(tmp_path, ["--enable"])
        assert self._run(tmp_path, ["--clear"]).exit_code == 0
        with _isolated_config(tmp_path):
            config_file = tmp_path / ".config" / "otampy" / "config.json"
            data = (
                json.loads(config_file.read_text())
                if config_file.exists()
                else {}
            )
        assert "mux" not in data.get("projects", {}).get(str(tmp_path), {})

    def test_show_reports_env_source(self, tmp_path):
        result = self._run(tmp_path, ["--show"], env={"OTAMPY_MUX": "1"})
        assert result.exit_code == 0
        assert "OTAMPY_MUX" in result.output

    def test_show_still_works_with_a_malformed_env_var(self, tmp_path):
        # F-03: a bad OTAMPY_MUX must not lock the user out of `otampy mux`.
        result = self._run(tmp_path, ["--show"], env={"OTAMPY_MUX": "maybe"})
        assert result.exit_code == 0
        flat = " ".join(result.output.split())
        assert "invalid, ignored" in flat
        assert "ignoring OTAMPY_MUX='maybe'" in flat

    def test_interactive_session_choice(self, tmp_path):
        result = self._run(tmp_path, [], stdin="y\ns\n")
        assert result.exit_code == 0
        session_file = tmp_path / "otampy_session_7777.json"
        assert json.loads(session_file.read_text())["mux"] is True
