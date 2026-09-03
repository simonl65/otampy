"""
auth.py -- device-side verification for authenticated channel-0 commands.

The matching signer is the CLI's ``otampy/auth.py``; the two are pinned
against each other, and against stdlib ``hmac``, by
``device/tests/test_command_auth_contract.py``.

HMAC-SHA256 is hand-rolled on ``hashlib.sha256`` rather than imported from
``hmac``, which MicroPython does not ship. Keeping the construction
line-for-line comparable with the host copy is deliberate: the whole
security property is that both ends compute the same eight bytes.

Nothing here raises. This module is reached from ``manager.poll()``, which
runs inside the application's main loop -- an exception would take the
loop down, so every malformed input returns ``None`` or ``False``.
"""

import binascii
import hashlib

# Domain separation. Channel 1 (F-15a, in the robot application) signs
# `<0x81|0x82><counter u32><fields>`; prefixing channel 0's input with a
# string keeps the two input sets disjoint by their first byte, so a tag
# from one channel can never validate on the other. Channel 1 needs no
# matching change for this to hold -- see the spec's MAC section.
CH0_DOMAIN = b"otampy-ch0\x00"

MAC_BYTES = 8
KEY_HEX_LEN = 64

_BLOCK_SIZE = 64
_IPAD = 0x36
_OPAD = 0x5C


def signed_bytes(counter, command):
    """The exact bytes the MAC covers, rebuilt from parsed fields.

    Both ends construct this from the *fields* rather than slicing the
    received line, so there is no ambiguity about what was signed. The
    inner command is included whole, colons and all.
    """
    return CH0_DOMAIN + str(counter).encode() + b":" + command


def key_from_hex(key_hex):
    """32 key bytes from 64 hex chars, or ``None`` if anything is wrong.

    Returns rather than raises so a device with a missing or corrupt key
    fails closed instead of crashing the main loop.
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
        return binascii.unhexlify(key_hex)
    except ValueError:
        return None


def _block_sized_key(key_bytes):
    if len(key_bytes) > _BLOCK_SIZE:
        key_bytes = hashlib.sha256(key_bytes).digest()
    return key_bytes + b"\x00" * (_BLOCK_SIZE - len(key_bytes))


def derive_key_blocks(key_bytes):
    """Return ``(ipad_block, opad_block)``. Call once at first use and
    cache -- this is the allocation that must never be per-command."""
    k = _block_sized_key(key_bytes)
    ipad = bytes(b ^ _IPAD for b in k)
    opad = bytes(b ^ _OPAD for b in k)
    return ipad, opad


def tag(blocks, payload):
    """HMAC-SHA256(key, payload) truncated to ``MAC_BYTES``.

    The key block and payload are fed separately with ``.update()``
    rather than concatenated: the concatenation was measured as real
    allocation pressure in the channel-1 equivalent, and feeding
    separately also lets ``payload`` be a ``memoryview``.
    """
    ipad, opad = blocks
    inner = hashlib.sha256(ipad)
    inner.update(payload)
    outer = hashlib.sha256(opad)
    outer.update(inner.digest())
    return outer.digest()[:MAC_BYTES]


def verify(blocks, payload, expected):
    """True iff ``expected`` is the correct tag for ``payload``.

    The comparison accumulates over every byte instead of returning at the
    first difference, so how long it takes reveals nothing about how much
    of a forged tag was correct.
    """
    actual = tag(blocks, payload)
    if len(actual) != len(expected):
        return False
    acc = 0
    for i in range(len(actual)):
        acc |= actual[i] ^ expected[i]
    return acc == 0
