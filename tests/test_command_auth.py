"""Host-side command signing: counter persistence and the CLI wiring.

The cross-implementation contract (host tag == device tag == stdlib hmac)
lives in ``src/otampy/device/tests/test_command_auth_contract.py``, which is where
the ``device_otampy`` virtual package is available. This file covers what
is host-only: the monotonic counter, its state file, and the fact that
``_query`` signs every command exactly once per send attempt.
"""

from __future__ import annotations

import time
from unittest import mock

import pytest
from click.testing import CliRunner

import otampy.auth as auth
from otampy.cli import _command_signer, cli

KEY_HEX = "0f1e2d3c4b5a6978" * 4


@pytest.fixture(autouse=True)
def _isolated_signer(tmp_path, monkeypatch):
    """Every test starts with no key and a private counter file."""
    monkeypatch.delenv(auth.KEY_ENV, raising=False)
    monkeypatch.setenv(auth.COUNTER_FILE_ENV, str(tmp_path / "command-counter"))
    monkeypatch.setenv("OTAMPY_QUERY_RETRY_BACKOFF", "0.001")
    _command_signer.cache_clear()
    yield
    _command_signer.cache_clear()


def _signer(tmp_path, key_hex=KEY_HEX):
    return auth.CommandSigner(key_hex, str(tmp_path / "command-counter"))


# --- the counter --------------------------------------------------------


def test_counters_strictly_increase_across_calls(tmp_path):
    signer = _signer(tmp_path)
    seen = [signer.next_counter() for _ in range(5)]
    assert seen == sorted(seen)
    assert len(set(seen)) == 5


def test_the_counter_is_persisted_after_each_issue(tmp_path):
    state = tmp_path / "command-counter"
    signer = _signer(tmp_path)
    issued = signer.next_counter()
    assert int(state.read_text()) == issued


def test_a_restarted_signer_never_re_issues_below_the_persisted_value(tmp_path):
    # The deadlock regression: a CLI restart must not re-seed below what
    # the device has already accepted, or every command is rejected as a
    # replay until the device reboots.
    state = tmp_path / "command-counter"
    state.write_text(str(int(time.time()) + 10_000))
    high = int(state.read_text())
    assert _signer(tmp_path).next_counter() == high + 1


def test_next_counter_seeds_from_wall_clock_when_state_is_fresh(tmp_path):
    before = int(time.time())
    assert _signer(tmp_path).next_counter() >= before


@pytest.mark.parametrize("contents", ["", "garbage", "-5", str(2**40), "1.5"])
def test_a_corrupt_counter_state_file_is_treated_as_zero(tmp_path, contents):
    (tmp_path / "command-counter").write_text(contents)
    assert _signer(tmp_path).next_counter() >= int(time.time())


def test_next_counter_raises_cleanly_when_the_space_is_exhausted(tmp_path):
    signer = _signer(tmp_path)
    signer._last = 0xFFFFFFFF
    with pytest.raises(auth.CommandAuthError, match="exhausted"):
        signer.next_counter()


def test_the_state_directory_is_created_on_demand(tmp_path):
    state = tmp_path / "nested" / "dir" / "command-counter"
    signer = auth.CommandSigner(KEY_HEX, str(state))
    signer.next_counter()
    assert state.exists()


# --- wrap() -------------------------------------------------------------


def test_wrap_produces_a_verifiable_envelope(tmp_path):
    signer = _signer(tmp_path)
    envelope = signer.wrap(b"CAT:main.py")

    prefix, counter, mac_hex, inner = envelope.split(b":", 3)
    assert prefix == b"AUTH"
    assert inner == b"CAT:main.py"
    assert len(mac_hex) == 2 * auth.MAC_BYTES

    blocks = auth.derive_key_blocks(bytes.fromhex(KEY_HEX))
    payload = auth.signed_bytes(int(counter), inner)
    assert auth.verify(blocks, payload, bytes.fromhex(mac_hex.decode()))


def test_wrap_issues_a_fresh_counter_every_call(tmp_path):
    signer = _signer(tmp_path)
    first = signer.wrap(b"PING").split(b":")[1]
    second = signer.wrap(b"PING").split(b":")[1]
    assert int(second) > int(first)


def test_a_command_containing_colons_survives_wrapping(tmp_path):
    inner = b"CP_START:lib/x.py:1024:" + b"ab" * 32
    assert _signer(tmp_path).wrap(inner).split(b":", 3)[3] == inner


@pytest.mark.parametrize("bad", [None, "PING", 42, ["PING"]])
def test_wrap_raises_only_command_auth_error_for_a_bad_command(tmp_path, bad):
    with pytest.raises(auth.CommandAuthError):
        _signer(tmp_path).wrap(bad)


def test_wrap_raises_command_auth_error_when_the_state_file_is_unwritable(
    tmp_path, monkeypatch
):
    signer = _signer(tmp_path)

    def boom(*_args, **_kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr("otampy.auth.os.replace", boom)
    with pytest.raises(auth.CommandAuthError):
        signer.wrap(b"PING")


@pytest.mark.parametrize("bad", ["", "abc", "zz" * 32, "ab" * 31, "ab" * 33])
def test_a_malformed_key_raises_an_error_naming_the_env_var(tmp_path, bad):
    with pytest.raises(auth.CommandAuthError, match=auth.KEY_ENV):
        _signer(tmp_path, key_hex=bad)


# --- signer_from_env ----------------------------------------------------


def test_signer_from_env_is_none_when_no_key_is_set():
    assert auth.signer_from_env() is None


def test_signer_from_env_uses_the_env_key(monkeypatch):
    monkeypatch.setenv(auth.KEY_ENV, KEY_HEX)
    assert auth.signer_from_env().next_counter() >= 1


# --- the CLI wiring -----------------------------------------------------


def _run_ping():
    with (
        mock.patch("serial.Serial"),
        mock.patch("urst.Urst") as mock_device,
    ):
        instance = mock_device.return_value
        instance.read.return_value = b"PONG"
        result = CliRunner().invoke(cli, ["-p", "/dev/ttyFake", "ping"])
        return result, instance


def test_with_no_key_the_command_goes_out_unchanged():
    # The backward-compatibility guarantee, asserted rather than assumed.
    result, instance = _run_ping()
    assert result.exit_code == 0
    instance.send.assert_called_once_with(b"PING")


def test_with_a_key_the_command_goes_out_wrapped(monkeypatch):
    monkeypatch.setenv(auth.KEY_ENV, KEY_HEX)
    result, instance = _run_ping()
    assert result.exit_code == 0
    sent = instance.send.call_args[0][0]
    assert sent.startswith(b"AUTH:")
    assert sent.endswith(b":PING")


def test_a_malformed_key_fails_fast_with_a_clear_message(monkeypatch):
    monkeypatch.setenv(auth.KEY_ENV, "not-a-key")
    result, instance = _run_ping()
    assert result.exit_code != 0
    assert auth.KEY_ENV in result.output
    instance.send.assert_not_called()  # no pointless retries


def test_each_retry_attempt_carries_a_fresh_counter(monkeypatch):
    """The replay bug this design nearly shipped with.

    `_query` retries a failed send. If the envelope were built once and
    reused, a first attempt that reached the device but lost its reply
    would leave the counter already consumed, so every retry would be
    rejected as a replay and the command would fail permanently -- only
    ever on a marginal link.
    """
    monkeypatch.setenv(auth.KEY_ENV, KEY_HEX)
    with (
        mock.patch("serial.Serial"),
        mock.patch("urst.Urst") as mock_device,
    ):
        instance = mock_device.return_value
        instance.send.side_effect = [0, 1]  # first attempt fails to send
        instance.read.return_value = b"PONG"

        result = CliRunner().invoke(cli, ["-p", "/dev/ttyFake", "ping"])

        assert result.exit_code == 0
        assert instance.send.call_count == 2
        first, second = (c[0][0] for c in instance.send.call_args_list)
        assert int(first.split(b":")[1]) < int(second.split(b":")[1])
        # Old (broken) behaviour would have sent identical bytes twice.
        assert first != second
