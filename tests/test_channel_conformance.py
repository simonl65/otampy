"""Cross-implementation conformance for the channel-mux outer frame.

Pins the host ``ChannelCodec`` against the exact frame bytes the device
suite builds and consumes (``src/otampy/device/tests/test_mux.py``'s
``outer_frame`` helper). This test lives in the host ``tests/`` dir and
must NOT import the device lib (loaded as ``device_otampy`` by the device
conftest) — the frame bytes are replicated / hard-coded here instead, so a
regression on either side shows up as a byte mismatch rather than being
hidden by a shared code path.
"""

from urst.codec_layer import cobs_encode

from otampy.channel import APP_CHANNEL, OTA_CHANNEL, ChannelCodec


def outer_frame(channel: int, payload: bytes) -> bytes:
    """Byte-for-byte replica of device test_mux.py::outer_frame.

    Device: ``mux.cobs_encode(bytes([channel]) + payload) + bytes([mux._FRAME_DELIM])``
    where ``mux.cobs_encode is urst.codec_layer.cobs_encode`` and
    ``mux._FRAME_DELIM == 0``.
    """
    return cobs_encode(bytes([channel]) + payload) + b"\x00"


# Concrete expected bytes — captured once, not re-derived at test time.
_URST_INNER = b"\x00URST\x00"
_EXPECTED_OTA_FRAME = bytes.fromhex("010105555253540100")
_EXPECTED_APP_FRAME = bytes.fromhex("070168656c6c6f00")


def test_hardcoded_frame_bytes_match_the_reference_helper():
    # Guards the replica helper itself against COBS drift.
    assert outer_frame(OTA_CHANNEL, _URST_INNER) == _EXPECTED_OTA_FRAME
    assert outer_frame(APP_CHANNEL, b"hello") == _EXPECTED_APP_FRAME


def test_host_encode_matches_device_frame_bytes():
    codec = ChannelCodec()
    # (a) representative inner frames, including one with embedded zeros.
    assert codec.encode(OTA_CHANNEL, _URST_INNER) == _EXPECTED_OTA_FRAME

    big = bytes(range(256)) * 3  # 768 bytes, many embedded 0x00
    assert codec.encode(OTA_CHANNEL, big) == outer_frame(OTA_CHANNEL, big)


def test_host_deframe_accepts_device_ota_frame():
    codec = ChannelCodec()
    codec.feed(outer_frame(OTA_CHANNEL, _URST_INNER))
    assert list(codec.frames()) == [(OTA_CHANNEL, _URST_INNER)]

    big = bytes(range(256)) * 3
    codec.feed(outer_frame(OTA_CHANNEL, big))
    assert list(codec.frames()) == [(OTA_CHANNEL, big)]


def test_host_deframe_routes_app_channel_and_drops_unknown():
    codec = ChannelCodec()
    codec.feed(outer_frame(APP_CHANNEL, b'{"type":"drive"}'))
    codec.feed(outer_frame(99, b"unknown-channel"))
    assert list(codec.frames()) == [(APP_CHANNEL, b'{"type":"drive"}')]
