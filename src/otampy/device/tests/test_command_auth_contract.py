"""Contract for the two channel-0 command-auth (HMAC) implementations.

``src/otampy/auth.py`` (host, CPython) and
``src/otampy/device/lib/otampy/auth.py`` (device, MicroPython) hand-roll
HMAC-SHA256 so the device -- which has no ``hmac`` module -- and the CLI
stay line-for-line comparable.

This test imports **both** and pins them against each other AND against
Python's stdlib ``hmac``, an independent oracle, so a
self-consistent-but-wrong hand-roll cannot pass. It lives in the device
tests directory because only this directory's ``conftest.py`` sets up the
``device_otampy`` virtual package needed to import the device copy.
"""

import hashlib
import hmac

import device_otampy.auth as device
import pytest

import otampy.auth as host

KEY = bytes.fromhex("0f1e2d3c4b5a6978" * 4)  # 32 bytes
COUNTER = 1788462441
COMMAND = b"CAT:main.py"

MODS = [host, device]
MOD_IDS = ["host", "device"]


def _stdlib_tag(key, payload):
    return hmac.new(key, payload, hashlib.sha256).digest()[:8]


# --- The signed-bytes contract -----------------------------------------


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
def test_signed_bytes_are_domain_counter_colon_command(mod):
    assert mod.signed_bytes(COUNTER, COMMAND) == (
        b"otampy-ch0\x00" + b"1788462441" + b":" + COMMAND
    )


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
def test_the_domain_prefix_is_the_agreed_constant(mod):
    assert mod.CH0_DOMAIN == b"otampy-ch0\x00"


def test_both_implementations_agree_on_the_signed_bytes():
    assert host.signed_bytes(COUNTER, COMMAND) == device.signed_bytes(
        COUNTER, COMMAND
    )


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
def test_a_command_containing_colons_is_signed_whole(mod):
    # The envelope is split with maxsplit=3, so the inner command keeps
    # every colon it had. Signing must cover all of it, or `CP_START:a:1:h`
    # could be truncated to `CP_START:a` without invalidating the tag.
    inner = b"CP_START:lib/robot/main.py:1024:" + b"ab" * 32
    assert mod.signed_bytes(7, inner).endswith(b":" + inner)


# --- Domain separation from channel 1 (F-15a) --------------------------


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
def test_signed_bytes_can_never_collide_with_a_channel_1_frame(mod):
    # F-15a signs `<0x81|0x82><counter u32><fields>`. Channel 0's input
    # always starts with the domain prefix, so the two input sets are
    # disjoint by first byte and no tag can cross over. This is why F-15a
    # did NOT need a matching prefix added to it.
    first = mod.signed_bytes(COUNTER, COMMAND)[0]
    assert first not in (0x81, 0x82)
    assert first == ord("o")


# --- HMAC correctness ---------------------------------------------------


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
def test_tag_matches_stdlib_hmac_sha256_truncated_to_8(mod):
    blocks = mod.derive_key_blocks(KEY)
    payload = mod.signed_bytes(COUNTER, COMMAND)
    assert mod.tag(blocks, payload) == _stdlib_tag(KEY, payload)
    assert len(mod.tag(blocks, payload)) == mod.MAC_BYTES == 8


def test_the_two_implementations_produce_an_identical_tag():
    payload = host.signed_bytes(COUNTER, COMMAND)
    assert host.tag(host.derive_key_blocks(KEY), payload) == device.tag(
        device.derive_key_blocks(KEY), payload
    )


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
def test_a_key_longer_than_the_block_is_hashed_down_like_stdlib(mod):
    long_key = b"k" * 100
    blocks = mod.derive_key_blocks(long_key)
    assert mod.tag(blocks, COMMAND) == _stdlib_tag(long_key, COMMAND)


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
def test_tag_accepts_a_memoryview_payload(mod):
    blocks = mod.derive_key_blocks(KEY)
    assert mod.tag(blocks, memoryview(COMMAND)) == _stdlib_tag(KEY, COMMAND)


# --- verify -------------------------------------------------------------


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
def test_verify_accepts_the_correct_tag(mod):
    blocks = mod.derive_key_blocks(KEY)
    payload = mod.signed_bytes(COUNTER, COMMAND)
    assert mod.verify(blocks, payload, mod.tag(blocks, payload)) is True


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
@pytest.mark.parametrize("bit", [0, 1, 7, 33, 71])
def test_verify_rejects_a_single_bit_flip_in_the_payload(mod, bit):
    blocks = mod.derive_key_blocks(KEY)
    payload = bytearray(mod.signed_bytes(COUNTER, COMMAND))
    good = mod.tag(blocks, bytes(payload))
    payload[bit // 8] ^= 1 << (bit % 8)
    assert mod.verify(blocks, bytes(payload), good) is False


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
@pytest.mark.parametrize("byte_idx", [0, 3, 7])
def test_verify_rejects_a_single_bit_flip_anywhere_in_the_tag(mod, byte_idx):
    blocks = mod.derive_key_blocks(KEY)
    payload = mod.signed_bytes(COUNTER, COMMAND)
    good = bytearray(mod.tag(blocks, payload))
    good[byte_idx] ^= 0x01
    assert mod.verify(blocks, payload, bytes(good)) is False


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
def test_verify_rejects_a_wrong_length_tag(mod):
    blocks = mod.derive_key_blocks(KEY)
    payload = mod.signed_bytes(COUNTER, COMMAND)
    assert mod.verify(blocks, payload, b"\x00" * 7) is False
    assert mod.verify(blocks, payload, b"\x00" * 9) is False
    assert mod.verify(blocks, payload, b"") is False


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
def test_a_wrong_key_does_not_verify(mod):
    payload = host.signed_bytes(COUNTER, COMMAND)
    good = host.tag(host.derive_key_blocks(KEY), payload)
    assert mod.verify(mod.derive_key_blocks(bytes(32)), payload, good) is False


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
def test_a_tag_for_one_counter_does_not_verify_for_another(mod):
    # The counter is inside the signed bytes, so it cannot be edited in
    # flight to bypass the replay guard.
    blocks = mod.derive_key_blocks(KEY)
    good = mod.tag(blocks, mod.signed_bytes(COUNTER, COMMAND))
    other = mod.signed_bytes(COUNTER + 1, COMMAND)
    assert mod.verify(blocks, other, good) is False


# --- key loading --------------------------------------------------------


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
def test_key_from_hex_accepts_64_hex_chars(mod):
    assert mod.key_from_hex("0f1e2d3c4b5a6978" * 4) == KEY
    assert mod.key_from_hex("  " + "0f1e2d3c4b5a6978" * 4 + "  ") == KEY


@pytest.mark.parametrize("mod", MODS, ids=MOD_IDS)
@pytest.mark.parametrize(
    "bad", ["", None, "abc", "zz" * 32, "ab" * 31, "ab" * 33, 12345]
)
def test_key_from_hex_returns_none_for_anything_malformed(mod, bad):
    # None, never an exception: the device caller runs under main.py's
    # loop and must fail closed rather than raise.
    assert mod.key_from_hex(bad) is None
