"""
auth.py -- host-side signing for authenticated channel-0 commands.

The matching verifier is the device library's
``otampy/device/lib/otampy/auth.py``; the two are pinned against each
other, and against stdlib ``hmac``, by
``otampy/device/tests/test_command_auth_contract.py``.

HMAC is hand-rolled here rather than using ``hmac.new`` purely so this
file stays line-for-line comparable with the device copy, which cannot
use ``hmac`` because MicroPython does not ship it. The test proves the
hand-roll matches stdlib, so the duplication costs correctness nothing.

Signing is opt-in: with no key configured the CLI sends bare commands
exactly as it always has, and existing deployments are unaffected.
"""

import binascii
import hashlib
import os
import time

# Must stay byte-identical to the device copy's constant.
CH0_DOMAIN = b"otampy-ch0\x00"

MAC_BYTES = 8
KEY_HEX_LEN = 64

_BLOCK_SIZE = 64
_IPAD = 0x36
_OPAD = 0x5C

KEY_ENV = "OTAMPY_COMMAND_AUTH_KEY"
COUNTER_FILE_ENV = "OTAMPY_COUNTER_FILE"
DEFAULT_COUNTER_FILE = "~/.local/state/otampy/command-counter"

# A stored counter outside the wire's u32 range is a corrupt file, not a
# counter. Trusting one would push every subsequent command out of range.
_U32_MAX = 0xFFFFFFFF


class CommandAuthError(RuntimeError):
    """Signing is configured but cannot be performed."""


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


class CommandSigner:
    """Issues monotonic counters and wraps commands in `AUTH:` envelopes.

    One instance per CLI process. ``wrap`` raises ``CommandAuthError`` and
    nothing else -- the caller turns that into a clean user-facing error
    rather than a traceback.
    """

    def __init__(self, key_hex, state_path):
        key = key_from_hex(key_hex)
        if key is None:
            raise CommandAuthError(
                f"{KEY_ENV} must be {KEY_HEX_LEN} hex characters "
                "(32 bytes), matching the device's COMMAND_AUTH_KEY."
            )
        self._blocks = derive_key_blocks(key)
        self._state_path = state_path
        self._last = self._load_counter()

    def _load_counter(self):
        try:
            with open(self._state_path) as f:
                value = int(f.read().strip())
        except (OSError, ValueError):
            return 0
        if value < 0 or value > _U32_MAX:
            return 0
        return value

    def _persist_counter(self):
        # Atomic replace: a crash mid-write must not leave a truncated
        # file that reads back lower than what the device has accepted.
        directory = os.path.dirname(self._state_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = self._state_path + ".tmp"
        with open(tmp, "w") as f:
            f.write(str(self._last))
        os.replace(tmp, self._state_path)

    def next_counter(self):
        """The next counter: above both the last issued and the wall clock.

        Seeding from unix seconds means the first command after any device
        reboot is numerically far above anything an attacker recorded in an
        earlier session, so it floors out a whole recording at once.
        """
        candidate = max(self._last + 1, int(time.time()))
        if candidate > _U32_MAX:
            raise CommandAuthError(
                f"command counter space exhausted -- remove {self._state_path}"
            )
        self._last = candidate
        self._persist_counter()
        return self._last

    def wrap(self, command):
        """`AUTH:<counter>:<hex-mac>:<command>` for ``command``.

        A fresh counter per call, which matters: ``_query`` retries a
        failed send, and reusing a counter the device already accepted
        would make every retry look like a replay.
        """
        try:
            counter = self.next_counter()
            mac = tag(self._blocks, signed_bytes(counter, command))
            return (
                b"AUTH:"
                + str(counter).encode()
                + b":"
                + binascii.hexlify(mac)
                + b":"
                + command
            )
        except CommandAuthError:
            raise
        except (OSError, TypeError, ValueError, OverflowError) as e:
            raise CommandAuthError(f"cannot sign command: {e}") from e


def counter_file_path():
    return os.path.expanduser(
        os.environ.get(COUNTER_FILE_ENV) or DEFAULT_COUNTER_FILE
    )


def signer_from_env():
    """A ``CommandSigner``, or ``None`` when signing is not configured.

    ``None`` is the backward-compatible path: with no key set the CLI
    sends bare commands exactly as it always has.
    """
    key_hex = os.environ.get(KEY_ENV)
    if not key_hex:
        return None
    return CommandSigner(key_hex, counter_file_path())
