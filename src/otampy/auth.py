"""
auth.py -- host-side signing for authenticated channel-0 commands.

The matching verifier is the device library's
``otampy/device/lib/otampy/auth.py``; the two are pinned against each
other, and against stdlib ``hmac``, by
``otampy/device/tests/test_command_auth.py``.

HMAC is hand-rolled here rather than using ``hmac.new`` purely so this
file stays line-for-line comparable with the device copy, which cannot
use ``hmac`` because MicroPython does not ship it. The test proves the
hand-roll matches stdlib, so the duplication costs correctness nothing.

Signing is opt-in: with no key configured the CLI sends bare commands
exactly as it always has, and existing deployments are unaffected.
"""

import hashlib

# Must stay byte-identical to the device copy's constant.
CH0_DOMAIN = b"otampy-ch0\x00"

MAC_BYTES = 8
KEY_HEX_LEN = 64

_BLOCK_SIZE = 64
_IPAD = 0x36
_OPAD = 0x5C


def signed_bytes(counter, command):
    """The exact bytes the MAC covers, built from the fields.

    Mirrors the device's reconstruction from parsed fields, so both ends
    agree on the covered range without either slicing the wire line.
    """
    return CH0_DOMAIN + str(counter).encode() + b":" + command


def key_from_hex(key_hex):
    """32 key bytes from 64 hex chars, or ``None`` if anything is wrong.

    Returns rather than raises to match the device copy exactly; the CLI
    turns a ``None`` into its own clear, user-facing error naming the
    environment variable.
    """
    if not key_hex:
        return None
    try:
        key_hex = key_hex.strip()
    except AttributeError:
        return None
    if len(key_hex) != KEY_HEX_LEN:
        return None
    try:
        return bytes.fromhex(key_hex)
    except ValueError:
        return None


def _block_sized_key(key_bytes):
    if len(key_bytes) > _BLOCK_SIZE:
        key_bytes = hashlib.sha256(key_bytes).digest()
    return key_bytes + b"\x00" * (_BLOCK_SIZE - len(key_bytes))


def derive_key_blocks(key_bytes):
    """Return ``(ipad_block, opad_block)`` for ``key_bytes``."""
    k = _block_sized_key(key_bytes)
    ipad = bytes(b ^ _IPAD for b in k)
    opad = bytes(b ^ _OPAD for b in k)
    return ipad, opad


def tag(blocks, payload):
    """HMAC-SHA256(key, payload) truncated to ``MAC_BYTES``.

    Fed with ``.update()`` rather than a concatenation, matching the
    device copy so the two remain trivially comparable.
    """
    ipad, opad = blocks
    inner = hashlib.sha256(ipad)
    inner.update(payload)
    outer = hashlib.sha256(opad)
    outer.update(inner.digest())
    return outer.digest()[:MAC_BYTES]


def verify(blocks, payload, expected):
    """True iff ``expected`` is the correct tag for ``payload``, compared
    in constant time. Present for symmetry and for the roundtrip test;
    the device is where verification actually matters."""
    actual = tag(blocks, payload)
    if len(actual) != len(expected):
        return False
    acc = 0
    for i in range(len(actual)):
        acc |= actual[i] ^ expected[i]
    return acc == 0
