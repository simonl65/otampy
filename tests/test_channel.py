"""Host-side channel-mux outer-frame codec — see docs/protocol.md §1.3."""

import threading

from urst.codec_layer import cobs_encode

import otampy.channel as channel
from otampy.channel import (
    APP_CHANNEL,
    FRAME_DELIM,
    MAX_OUTER_FRAME_BYTES,
    OTA_BUFFER_BYTES,
    OTA_CHANNEL,
    ChannelCodec,
    ChannelSerial,
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

    def test_unknown_channel_frame_is_skipped(self):
        codec = ChannelCodec()
        codec.feed(_outer(99, b"mystery"))
        codec.feed(codec.encode(OTA_CHANNEL, b"\x00ok\x00"))
        assert list(codec.frames()) == [(OTA_CHANNEL, b"\x00ok\x00")]
        assert codec.frames_dropped == 0

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


class _FakeSerial:
    """Minimal serial-like double for ChannelSerial."""

    def __init__(self, data: bytes = b""):
        self.rx = bytearray(data)
        self.tx = bytearray()
        self.flushed = 0
        self.input_resets = 0
        self.output_resets = 0
        self.closed = False

    def write(self, data: bytes) -> int:
        self.tx.extend(data)
        return len(data)

    def flush(self):
        self.flushed += 1

    @property
    def in_waiting(self) -> int:
        return len(self.rx)

    def read(self, n: int = 1) -> bytes:
        out = bytes(self.rx[:n])
        self.rx = self.rx[n:]
        return out

    def reset_input_buffer(self):
        self.rx = bytearray()
        self.input_resets += 1

    def reset_output_buffer(self):
        self.output_resets += 1

    def close(self):
        self.closed = True

    def feed(self, data: bytes):
        """Simulate bytes arriving on the wire."""
        self.rx.extend(data)


class TestChannelSerial:
    def test_write_frames_on_channel_zero(self):
        fake = _FakeSerial()
        cs = ChannelSerial(fake)
        assert cs.write(b"PING") == 4
        assert bytes(fake.tx) == _outer(OTA_CHANNEL, b"PING")

    def test_read_returns_only_channel_zero_payload(self):
        fake = _FakeSerial()
        cs = ChannelSerial(fake)
        fake.feed(_outer(APP_CHANNEL, b"telemetry"))
        fake.feed(_outer(OTA_CHANNEL, b"\x00URST\x00"))
        got = b""
        for _ in range(20):
            chunk = cs.read(64)
            if not chunk:
                break
            got += chunk
        assert got == b"\x00URST\x00"

    def test_in_waiting_reports_decoded_count_and_pumps(self):
        fake = _FakeSerial()
        cs = ChannelSerial(fake)
        assert cs.in_waiting == 0
        fake.feed(_outer(OTA_CHANNEL, b"abcde"))
        assert cs.in_waiting == 5
        assert cs.read(5) == b"abcde"
        assert cs.in_waiting == 0

    def test_decoded_buffer_is_bounded(self):
        fake = _FakeSerial()
        cs = ChannelSerial(fake)
        for _ in range(30):  # 30 × 100 decoded bytes = 3000 > OTA_BUFFER_BYTES
            fake.feed(_outer(OTA_CHANNEL, b"A" * 100))
        assert cs.in_waiting == OTA_BUFFER_BYTES

    def test_reset_input_buffer_clears_half_received_frame(self):
        fake = _FakeSerial()
        cs = ChannelSerial(fake)
        frame = _outer(OTA_CHANNEL, b"\x00whole\x00")
        fake.feed(frame[:4])
        cs.read(64)  # pump the partial frame into the codec
        cs.reset_input_buffer()
        assert fake.input_resets == 1
        fake.feed(_outer(OTA_CHANNEL, b"\x00next\x00"))
        assert cs.read(64) == b"\x00next\x00"

    def test_pump_does_not_read_when_port_is_empty(self):
        # A real serial.Serial.in_waiting never blocks; ChannelSerial must not
        # either. When the raw port reports nothing pending, _pump must not fall
        # back to a blocking read(1) -- URST's own read_frame loop does the
        # waiting.
        class _RaisingWhenEmpty:
            in_waiting = 0
            reads = 0

            def read(self, n):
                self.__class__.reads += 1
                raise AssertionError("read() called on an empty port")

            def reset_input_buffer(self):
                pass

            def reset_output_buffer(self):
                pass

        fake = _RaisingWhenEmpty()
        cs = ChannelSerial(fake)
        assert cs.in_waiting == 0
        assert cs.read(16) == b""
        assert _RaisingWhenEmpty.reads == 0

    def test_pump_reads_only_what_is_pending(self):
        fake = _FakeSerial()
        cs = ChannelSerial(fake)
        frame = _outer(OTA_CHANNEL, b"\x00hi\x00")
        fake.feed(frame)
        # in_waiting reports the raw pending count; ChannelSerial reads exactly
        # that many bytes, no blocking 1-byte fallback.
        assert cs.in_waiting == len(b"\x00hi\x00")
        assert cs.read(64) == b"\x00hi\x00"

    def test_delegates_output_reset_and_close(self):
        fake = _FakeSerial()
        cs = ChannelSerial(fake)
        cs.reset_output_buffer()
        cs.close()
        assert fake.output_resets == 1
        assert fake.closed is True

    def test_min_tx_gap_sleeps_remaining_then_not(self, monkeypatch):
        slept = []
        clock = [1000.0]
        monkeypatch.setattr(channel, "_now_ms", lambda: clock[0])
        monkeypatch.setattr(channel, "_sleep_ms", lambda ms: slept.append(ms))
        cs = ChannelSerial(_FakeSerial(), min_tx_gap_ms=20)

        cs.write(b"one")
        cs.flush()  # records last-write-done at t=1000
        clock[0] += 5  # 15 ms short of the 20 ms floor
        cs.write(b"two")
        assert slept == [15]

        cs.flush()  # records last-write-done at t=1005
        clock[0] += 25  # already past the floor
        cs.write(b"three")
        assert slept == [15]


def _cross_pipe():
    """Two thread-safe one-directional byte pipes wired as a serial pair."""

    class _Pipe:
        def __init__(self):
            self._buf = bytearray()
            self._lock = threading.Lock()

        def push(self, data):
            with self._lock:
                self._buf.extend(data)

        def pull(self, n):
            with self._lock:
                out = bytes(self._buf[:n])
                self._buf = self._buf[n:]
                return out

        def clear(self):
            with self._lock:
                self._buf = bytearray()

        def pending(self):
            with self._lock:
                return len(self._buf)

    class _End:
        def __init__(self, rx, tx):
            self._rx, self._tx = rx, tx

        def write(self, data):
            self._tx.push(data)
            return len(data)

        def flush(self):
            pass

        @property
        def in_waiting(self):
            return self._rx.pending()

        def read(self, n=1):
            return self._rx.pull(n)

        def reset_input_buffer(self):
            self._rx.clear()

        def reset_output_buffer(self):
            pass

        def close(self):
            pass

    a, b = _Pipe(), _Pipe()
    return _End(a, b), _End(b, a)


class TestChannelSerialUrstRoundtrip:
    def test_urst_roundtrip(self):
        # `from urst import Urst` resolves to the device-test conftest's
        # FakeUrst once the device suite is collected; the real class is
        # still reachable via its unshadowed submodule.
        from urst.core_handler import Urst

        host_raw, dev_raw = _cross_pipe()
        host = Urst(ChannelSerial(host_raw), timeout=1.0)
        dev = Urst(ChannelSerial(dev_raw), timeout=1.0)

        errors = []

        def device_side():
            try:
                for _ in range(50):
                    msg = dev.read()
                    if msg == b"PING":
                        dev.reply(b"PONG")
                        return
                errors.append("device never received PING")
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        t = threading.Thread(target=device_side, daemon=True)
        t.start()
        assert host.send(b"PING") == 4
        assert host.read() == b"PONG"
        t.join(timeout=10)
        assert not t.is_alive()
        assert errors == []
