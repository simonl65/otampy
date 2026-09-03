"""Authenticated channel-0 command dispatch in ``manager.poll()``.

Kept in its own file so ``test_ota_manager.py`` stays literally untouched
-- "every existing command still works with auth off" is a much stronger
claim when the existing suite is byte-for-byte unmodified.

The three states under test:

* ``OTA_REQUIRE_AUTH`` off  -> today's behaviour exactly (backward compat)
* on + valid key            -> envelope required, verified, replay-checked
* on + missing/bad key      -> everything rejected (fail closed)
"""

import binascii

import device_otampy.auth as auth
import machine
import pytest
import shared
from device_otampy import manager
from device_otampy.core import OTACore

KEY_HEX = "0f1e2d3c4b5a6978" * 4
KEY = bytes.fromhex(KEY_HEX)
BLOCKS = auth.derive_key_blocks(KEY)

FLAG_FILE = "update_requested.flag"


def _config(tmp_path, require_auth=True, key_hex=KEY_HEX):
    config = {
        "LOG_LEVEL": "DEBUG",
        "UPDATE_REQUEST_FLAG_FILE": str(tmp_path / FLAG_FILE),
        "OTA_REPLAY_FLOOR_FILE": str(tmp_path / "otampy-replay-floor"),
    }
    if require_auth:
        config["OTA_REQUIRE_AUTH"] = True
    if key_hex is not None:
        config["COMMAND_AUTH_KEY"] = key_hex
    return config


def _core(tmp_path, **kwargs):
    machine.reset.reset_mock()
    machine.soft_reset.reset_mock()
    return OTACore(
        shared.FakeUART(), config=_config(tmp_path, **kwargs), logger=shared.FakeLogger()
    )


def _envelope(command, counter, blocks=BLOCKS):
    """Build a signed `AUTH:` envelope exactly as the CLI will."""
    mac = auth.tag(blocks, auth.signed_bytes(counter, command))
    return b"AUTH:%d:%s:%s" % (counter, binascii.hexlify(mac), command)


# --- backward compatibility: the flag defaults off ----------------------


def test_with_auth_off_a_bare_command_still_works(tmp_path):
    core = _core(tmp_path, require_auth=False)
    core.transport.incoming_queue.append(b"PING")
    manager.poll(core)
    assert core.transport.sent_messages == [b"PONG"]


def test_a_config_with_no_auth_keys_at_all_behaves_as_before():
    # An existing deployment's configota.py has none of the new settings.
    core = OTACore(shared.FakeUART(), logger=shared.FakeLogger())
    core.transport.incoming_queue.append(b"PING")
    manager.poll(core)
    assert core.transport.sent_messages == [b"PONG"]


def test_with_auth_off_no_replay_state_is_created(tmp_path):
    core = _core(tmp_path, require_auth=False)
    core.transport.incoming_queue.append(b"PING")
    manager.poll(core)
    assert getattr(core, "_replay_guard", None) is None


# --- happy path ---------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "expected"),
    [(b"PING", b"PONG"), (b"MEM", b"MEM_OK:"), (b"RTC", b"RTC_OK:")],
)
def test_a_signed_command_reaches_its_existing_handler(tmp_path, command, expected):
    core = _core(tmp_path)
    core.transport.incoming_queue.append(_envelope(command, 1000))
    manager.poll(core)
    assert core.transport.sent_messages[0].startswith(expected)


def test_a_signed_command_keeps_every_colon_in_its_arguments(tmp_path):
    # The envelope splits with maxsplit=3, so `CAT:a:b` must arrive whole.
    core = _core(tmp_path)
    core.transport.incoming_queue.append(_envelope(b"CAT:does/not/exist:x", 1000))
    manager.poll(core)
    # Reaches CAT and fails on the filesystem, not on parsing.
    assert core.transport.sent_messages[0].startswith(b"ERROR:")
    assert b"Unauthenticated" not in core.transport.sent_messages[0]


def test_counters_may_skip_ahead(tmp_path):
    core = _core(tmp_path)
    for counter in (10, 5000, 5001, 900000):
        core.transport.incoming_queue.append(_envelope(b"PING", counter))
        manager.poll(core)
    assert core.transport.sent_messages == [b"PONG"] * 4


# --- rejection paths ----------------------------------------------------


def test_a_bare_unwrapped_command_is_rejected(tmp_path):
    core = _core(tmp_path)
    core.transport.incoming_queue.append(b"PING")
    manager.poll(core)
    assert core.transport.sent_messages == [b"ERROR:Unauthenticated"]


def test_a_command_signed_with_the_wrong_key_is_rejected(tmp_path):
    core = _core(tmp_path)
    wrong = auth.derive_key_blocks(bytes(32))
    core.transport.incoming_queue.append(_envelope(b"PING", 1000, blocks=wrong))
    manager.poll(core)
    assert core.transport.sent_messages == [b"ERROR:Unauthenticated"]


def test_a_replayed_counter_is_rejected(tmp_path):
    core = _core(tmp_path)
    frame = _envelope(b"PING", 1000)
    core.transport.incoming_queue.append(frame)
    manager.poll(core)
    core.transport.incoming_queue.append(frame)
    manager.poll(core)
    assert core.transport.sent_messages == [b"PONG", b"ERROR:Replayed"]


def test_a_lower_counter_is_rejected(tmp_path):
    core = _core(tmp_path)
    core.transport.incoming_queue.append(_envelope(b"PING", 1000))
    manager.poll(core)
    core.transport.incoming_queue.append(_envelope(b"PING", 999))
    manager.poll(core)
    assert core.transport.sent_messages[-1] == b"ERROR:Replayed"


def test_editing_the_counter_in_flight_invalidates_the_tag(tmp_path):
    # The counter is inside the signed bytes, so it cannot be raised to
    # bypass the replay guard without breaking the MAC.
    core = _core(tmp_path)
    good = _envelope(b"PING", 1000)
    tampered = good.replace(b"AUTH:1000:", b"AUTH:9999:")
    core.transport.incoming_queue.append(tampered)
    manager.poll(core)
    assert core.transport.sent_messages == [b"ERROR:Unauthenticated"]


def test_editing_the_command_in_flight_invalidates_the_tag(tmp_path):
    core = _core(tmp_path)
    good = _envelope(b"PING", 1000)
    tampered = good[: -len(b"PING")] + b"MEM."
    core.transport.incoming_queue.append(tampered)
    manager.poll(core)
    assert core.transport.sent_messages == [b"ERROR:Unauthenticated"]


@pytest.mark.parametrize(
    "frame",
    [
        b"AUTH",
        b"AUTH:",
        b"AUTH:1000",
        b"AUTH:1000:deadbeefdeadbeef",  # no inner command
        b"AUTH:1000:deadbeefdeadbeef:",  # empty inner command
        b"AUTH:notanumber:deadbeefdeadbeef:PING",
        b"AUTH:1000:nothexatall!!!!!:PING",
        b"AUTH:1000:abc:PING",  # odd-length hex
        b"AUTH:1000::PING",  # empty tag
        b"AUTH:1000:deadbeef:PING",  # tag too short
        b"AUTH:1000:deadbeefdeadbeefdead:PING",  # tag too long
        b"AUTH::deadbeefdeadbeef:PING",  # empty counter
        b"AUTH:-1:deadbeefdeadbeef:PING",
        b"auth:1000:deadbeefdeadbeef:PING",  # wrong case
    ],
)
def test_a_malformed_envelope_is_rejected_without_raising(tmp_path, frame):
    core = _core(tmp_path)
    core.transport.incoming_queue.append(frame)
    manager.poll(core)  # must not raise
    assert core.transport.sent_messages == [b"ERROR:Unauthenticated"]


def test_a_rejected_forgery_does_not_advance_the_replay_guard(tmp_path):
    # The ordering trap: verify must happen BEFORE the replay guard
    # accepts, or one forged high counter locks the real host out.
    core = _core(tmp_path)
    wrong = auth.derive_key_blocks(bytes(32))
    core.transport.incoming_queue.append(_envelope(b"PING", 10**9, blocks=wrong))
    manager.poll(core)
    core.transport.incoming_queue.append(_envelope(b"PING", 1000))
    manager.poll(core)
    assert core.transport.sent_messages == [b"ERROR:Unauthenticated", b"PONG"]


# --- fail closed --------------------------------------------------------


@pytest.mark.parametrize("key_hex", [None, "", "abc", "zz" * 32, "ab" * 31])
def test_auth_on_with_no_usable_key_rejects_everything(tmp_path, key_hex):
    core = _core(tmp_path, key_hex=key_hex)
    core.transport.incoming_queue.append(_envelope(b"PING", 1000))
    manager.poll(core)
    assert core.transport.sent_messages == [b"ERROR:Unauthenticated"]


def test_a_bad_key_is_reported_loudly(tmp_path):
    core = _core(tmp_path, key_hex="nope")
    core.transport.incoming_queue.append(b"PING")
    manager.poll(core)
    assert any(
        level == "error" and "COMMAND_AUTH_KEY" in message
        for level, message in core.logger.messages
    )


# --- the reset commands persist a replay floor --------------------------


@pytest.mark.parametrize(
    ("command", "reset_fn"),
    [(b"RB", "reset"), (b"SR", "soft_reset"), (b"UPDATE_REQUEST", "reset")],
)
def test_a_signed_reset_persists_the_floor_then_resets(tmp_path, command, reset_fn):
    import device_otampy.replay as replay

    core = _core(tmp_path)
    core.transport.incoming_queue.append(_envelope(command, 4242))
    manager.poll(core)

    getattr(machine, reset_fn).assert_called_once()
    assert replay.load_floor(str(tmp_path / "otampy-replay-floor")) == 4242


def test_the_persisted_floor_blocks_a_replay_after_a_reboot(tmp_path):
    # The case a RAM-only counter cannot cover.
    core = _core(tmp_path)
    frame = _envelope(b"RB", 4242)
    core.transport.incoming_queue.append(frame)
    manager.poll(core)

    rebooted = _core(tmp_path)  # fresh core, as after machine.reset()
    rebooted.transport.incoming_queue.append(frame)
    manager.poll(rebooted)
    assert rebooted.transport.sent_messages == [b"ERROR:Replayed"]


def test_a_reset_still_happens_when_the_floor_write_fails(tmp_path, monkeypatch):
    core = _core(tmp_path)
    core.transport.incoming_queue.append(_envelope(b"RB", 4242))

    import device_otampy.replay as replay

    def boom(self, _path):
        raise OSError("flash is full")

    monkeypatch.setattr(replay.ReplayGuard, "persist_floor", boom)
    manager.poll(core)  # must not raise
    machine.reset.assert_called_once()


def test_an_envelope_built_by_the_host_signer_is_accepted_by_the_device(
    tmp_path,
):
    """End-to-end: the CLI's wire format is what the device parses.

    Everything else here builds envelopes with a local helper, which
    would happily keep passing if the CLI and the device drifted apart.
    This drives the real ``otampy.auth.CommandSigner`` -- the code the CLI
    actually calls -- straight into ``manager.poll()``.
    """
    from otampy.auth import CommandSigner

    signer = CommandSigner(KEY_HEX, str(tmp_path / "host-counter"))
    core = _core(tmp_path)
    core.transport.incoming_queue.append(signer.wrap(b"PING"))
    manager.poll(core)
    assert core.transport.sent_messages == [b"PONG"]


def test_a_host_signed_command_with_the_wrong_key_is_rejected(tmp_path):
    from otampy.auth import CommandSigner

    signer = CommandSigner("ab" * 32, str(tmp_path / "host-counter"))
    core = _core(tmp_path)
    core.transport.incoming_queue.append(signer.wrap(b"PING"))
    manager.poll(core)
    assert core.transport.sent_messages == [b"ERROR:Unauthenticated"]


def test_with_auth_off_a_reset_writes_no_floor(tmp_path):
    import device_otampy.replay as replay

    core = _core(tmp_path, require_auth=False)
    core.transport.incoming_queue.append(b"RB")
    manager.poll(core)
    machine.reset.assert_called_once()
    assert replay.load_floor(str(tmp_path / "otampy-replay-floor")) == 0
