from device_otampy import mux  # type: ignore


class FakeUart:
    def __init__(self):
        self.incoming = bytearray()
        self.writes = []

    def any(self):
        return len(self.incoming)

    def read(self, size):
        data = bytes(self.incoming[:size])
        del self.incoming[:size]
        return data

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)


def outer_frame(channel, payload):
    return mux.cobs_encode(bytes([channel]) + payload) + bytes(
        [mux._FRAME_DELIM]
    )


def test_mux_uses_urst_cobs_implementation():
    from urst.codec_layer import cobs_decode, cobs_encode

    assert mux.cobs_encode is cobs_encode
    assert mux.cobs_decode is cobs_decode


def test_routes_frames_delivered_one_byte_at_a_time():
    uart = FakeUart()
    serial_mux = mux.SerialMux(uart)
    encoded = outer_frame(mux.DEFAULT_OTA_CHANNEL, b"\x00URST\x00")

    for byte in encoded:
        uart.incoming.append(byte)
        serial_mux.service()

    assert serial_mux.ota_port.read() == b"\x00URST\x00"


def test_service_finds_frame_delimiter_with_micropython_compatible_api():
    uart = FakeUart()
    serial_mux = mux.SerialMux(uart)
    uart.incoming.extend(outer_frame(mux.DEFAULT_OTA_CHANNEL, b"frame"))

    serial_mux.service()

    assert serial_mux.ota_port.read() == b"frame"


def test_ota_port_pumps_mux_while_urst_is_waiting():
    uart = FakeUart()
    serial_mux = mux.SerialMux(uart)
    uart.incoming.extend(outer_frame(mux.DEFAULT_OTA_CHANNEL, b"\x00URST\x00"))

    assert serial_mux.ota_port.any() == len(b"\x00URST\x00")
    assert serial_mux.ota_port.read() == b"\x00URST\x00"


def test_ota_readiness_requires_complete_inner_urst_frame():
    uart = FakeUart()
    serial_mux = mux.SerialMux(uart)
    uart.incoming.extend(outer_frame(mux.DEFAULT_OTA_CHANNEL, b"\x00part"))

    assert not serial_mux.ota_port.frame_ready()

    uart.incoming.extend(outer_frame(mux.DEFAULT_OTA_CHANNEL, b"ial\x00"))

    assert serial_mux.ota_port.frame_ready()
    assert serial_mux.ota_port.read() == b"\x00partial\x00"


def test_routes_multiple_channels_from_one_read():
    uart = FakeUart()
    serial_mux = mux.SerialMux(uart)
    uart.incoming.extend(
        outer_frame(mux.DEFAULT_APP_CHANNEL, b'{"type":"drive"}')
        + outer_frame(mux.DEFAULT_OTA_CHANNEL, b"\x00frame\x00")
    )

    serial_mux.service()

    assert serial_mux.poll_app() == b'{"type":"drive"}'
    assert serial_mux.ota_port.read() == b"\x00frame\x00"


def test_invalid_and_unknown_frames_are_dropped():
    uart = FakeUart()
    serial_mux = mux.SerialMux(uart)
    uart.incoming.extend(b"\x05bad\x00" + outer_frame(99, b"unknown"))

    serial_mux.service()

    assert serial_mux.poll_app() is None
    assert serial_mux.ota_port.read() is None


def test_newest_app_message_wins():
    uart = FakeUart()
    serial_mux = mux.SerialMux(uart)
    uart.incoming.extend(
        outer_frame(mux.DEFAULT_APP_CHANNEL, b"old")
        + outer_frame(mux.DEFAULT_APP_CHANNEL, b"new")
    )

    serial_mux.service()

    assert serial_mux.poll_app() == b"new"
    assert serial_mux.poll_app() is None
    assert serial_mux.app_dropped == 1


def test_oversized_unterminated_frame_is_discarded():
    uart = FakeUart()
    serial_mux = mux.SerialMux(uart)
    uart.incoming.extend(b"x" * (mux.MAX_OUTER_FRAME_BYTES + 1))

    serial_mux.service()

    assert not serial_mux._rx_buffer
    assert serial_mux.outer_frames_dropped == 1


def test_service_trims_rx_buffer_via_slice_reassignment():
    # MicroPython's bytearray doesn't support item/slice deletion at all
    # (`del buf[:n]` raises TypeError: 'bytearray' object doesn't support
    # item deletion) -- only CPython's does. service() must trim consumed
    # bytes off the front of _rx_buffer via slice reassignment instead.
    uart = FakeUart()
    serial_mux = mux.SerialMux(uart)
    uart.incoming.extend(
        outer_frame(mux.DEFAULT_OTA_CHANNEL, b"\x00one\x00")
        + outer_frame(mux.DEFAULT_OTA_CHANNEL, b"\x00two\x00")
    )

    serial_mux.service()

    assert serial_mux.ota_port.read() == b"\x00one\x00\x00two\x00"
    assert not serial_mux._rx_buffer


def test_channel_ids_are_configurable():
    uart = FakeUart()
    serial_mux = mux.SerialMux(uart, ota_channel=0x05, app_channel=0x06)
    uart.incoming.extend(
        outer_frame(0x06, b"app data") + outer_frame(0x05, b"\x00ota\x00")
    )

    serial_mux.service()

    assert serial_mux.poll_app() == b"app data"
    assert serial_mux.ota_port.read() == b"\x00ota\x00"


class TestMinTxGap:
    """`min_tx_gap_ms` (see CHANGELOG.md): an opt-in minimum gap enforced
    between the end of one physical UART write and the start of the next,
    across *both* channels -- some half-duplex transparent-mode radios
    corrupt reception when a device transmits back-to-back with no
    inter-frame gap (found bench-testing diff-drive-robot's XBee link).
    Default 0 -- zero behaviour change for existing users/hardware."""

    def test_default_gap_is_zero_and_never_sleeps(self, monkeypatch):
        sleep_calls = []
        monkeypatch.setattr(mux, "_sleep_ms", lambda ms: sleep_calls.append(ms))
        uart = FakeUart()
        serial_mux = mux.SerialMux(uart)

        serial_mux.ota_port.write(b"one")
        serial_mux.send_app(b"two")

        assert sleep_calls == []
        assert len(uart.writes) == 2

    def test_sleeps_for_the_remaining_gap_across_both_channels(
        self, monkeypatch
    ):
        sleep_calls = []
        monkeypatch.setattr(mux, "_sleep_ms", lambda ms: sleep_calls.append(ms))
        clock = [1_000]
        monkeypatch.setattr(mux, "_ticks_ms", lambda: clock[0])
        uart = FakeUart()
        serial_mux = mux.SerialMux(uart, min_tx_gap_ms=20)

        serial_mux.ota_port.write(b"ota frame")
        clock[0] += 5  # only 5ms elapsed, 15ms short of the 20ms floor
        serial_mux.send_app(b"app frame")  # different channel, same gap

        assert sleep_calls == [15]

    def test_does_not_sleep_once_the_gap_has_naturally_elapsed(
        self, monkeypatch
    ):
        sleep_calls = []
        monkeypatch.setattr(mux, "_sleep_ms", lambda ms: sleep_calls.append(ms))
        clock = [1_000]
        monkeypatch.setattr(mux, "_ticks_ms", lambda: clock[0])
        uart = FakeUart()
        serial_mux = mux.SerialMux(uart, min_tx_gap_ms=20)

        serial_mux.ota_port.write(b"first")
        clock[0] += 25  # already past the 20ms floor
        serial_mux.send_app(b"second")

        assert sleep_calls == []
