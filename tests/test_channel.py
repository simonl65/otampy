"""Host-side channel-mux outer-frame codec — see docs/protocol.md §1.3."""

from urst.codec_layer import cobs_encode

from otampy.channel import (
    APP_CHANNEL,
    FRAME_DELIM,
    MAX_OUTER_FRAME_BYTES,
    OTA_CHANNEL,
    ChannelCodec,
)


def _outer(channel: int, payload: bytes) -> bytes:
    """Reference outer frame, independent of ChannelCodec.encode."""
    return cobs_encode(bytes([channel]) + payload) + FRAME_DELIM


class TestChannelCodec:
    def test_round_trip_single_frame(self):
        codec = ChannelCodec()
        codec.feed(codec.encode(OTA_CHANNEL, b"\x00URST\x00"))
        assert list(codec.frames()) == [(OTA_CHANNEL, b"\x00URST\x00")]

    def test_encode_matches_reference_frame(self):
        codec = ChannelCodec()
        assert codec.encode(OTA_CHANNEL, b"hello") == _outer(
            OTA_CHANNEL, b"hello"
        )

    def test_frame_delivered_one_byte_at_a_time(self):
        codec = ChannelCodec()
        encoded = codec.encode(OTA_CHANNEL, b"\x00drip\x00")
        for byte in encoded[:-1]:
            codec.feed(bytes([byte]))
            assert list(codec.frames()) == []
        codec.feed(bytes([encoded[-1]]))
        assert list(codec.frames()) == [(OTA_CHANNEL, b"\x00drip\x00")]

    def test_two_channels_in_one_feed(self):
        codec = ChannelCodec()
        codec.feed(
            codec.encode(APP_CHANNEL, b'{"t":"drive"}')
            + codec.encode(OTA_CHANNEL, b"\x00frame\x00")
        )
        assert list(codec.frames()) == [
            (APP_CHANNEL, b'{"t":"drive"}'),
            (OTA_CHANNEL, b"\x00frame\x00"),
        ]

    def test_corrupt_cobs_dropped_next_good_frame_still_yielded(self):
        codec = ChannelCodec()
        codec.feed(b"\x05bad" + FRAME_DELIM)
        codec.feed(codec.encode(OTA_CHANNEL, b"\x00good\x00"))
        assert list(codec.frames()) == [(OTA_CHANNEL, b"\x00good\x00")]
        assert codec.frames_dropped == 1

    def test_over_long_frame_dropped(self):
        codec = ChannelCodec()
        codec.feed(b"x" * (MAX_OUTER_FRAME_BYTES + 1) + FRAME_DELIM)
        codec.feed(codec.encode(OTA_CHANNEL, b"\x00ok\x00"))
        assert list(codec.frames()) == [(OTA_CHANNEL, b"\x00ok\x00")]
        assert codec.frames_dropped == 1

    def test_delimiter_free_buffer_past_max_is_cleared(self):
        codec = ChannelCodec()
        codec.feed(b"x" * (MAX_OUTER_FRAME_BYTES + 1))
        assert list(codec.frames()) == []
        assert codec._buf == bytearray()
        codec.feed(codec.encode(OTA_CHANNEL, b"\x00after\x00"))
        assert list(codec.frames()) == [(OTA_CHANNEL, b"\x00after\x00")]

    def test_leading_empty_frame_is_skipped(self):
        codec = ChannelCodec()
        codec.feed(FRAME_DELIM + codec.encode(OTA_CHANNEL, b"\x00x\x00"))
        assert list(codec.frames()) == [(OTA_CHANNEL, b"\x00x\x00")]

    def test_reset_discards_buffer(self):
        codec = ChannelCodec()
        codec.feed(b"partial-no-delim")
        codec.reset()
        codec.feed(codec.encode(OTA_CHANNEL, b"\x00y\x00"))
        assert list(codec.frames()) == [(OTA_CHANNEL, b"\x00y\x00")]
