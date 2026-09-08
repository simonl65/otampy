"""Host-side implementation of the optional channel-mux outer frame.

See ``docs/protocol.md`` §1.3 for the wire contract. The frame is
byte-identical to what the device ``otampy.mux.SerialMux`` emits:

    frame = COBS_encode( channel_id ‖ payload ) ‖ 0x00

``ChannelCodec`` is pure bytes-in/bytes-out (no IO) so it can be shared and
conformance-tested against the device ``mux.py``. ``ChannelSerial`` wraps a
real ``serial.Serial`` and surfaces only channel 0 to URST's codec layer.

Ported from the frame core of the device ``mux.py`` (``_write_channel`` for
encode, ``service()`` for deframe); the daemon concerns of
``diff-drive-robot``'s ``mux_host.py`` (threading, telemetry queue,
auto-reconnect, ``port_resolver``) are intentionally not ported -- the CLI
is a short-lived single-command process.
"""

import time

from urst.codec_layer import cobs_decode, cobs_encode  # type: ignore


def _now_ms() -> float:
    return time.monotonic() * 1000.0  # type: ignore[attr-defined]


def _sleep_ms(ms: float) -> None:
    time.sleep(ms / 1000.0)


# Channel ids -- mirror device mux.DEFAULT_OTA_CHANNEL / DEFAULT_APP_CHANNEL.
OTA_CHANNEL = 0x00
APP_CHANNEL = 0x01

# Outer-frame delimiter -- mirror device mux._FRAME_DELIM_BYTES.
FRAME_DELIM = b"\x00"

# Largest outer frame accepted on receive -- mirror device
# mux.MAX_OUTER_FRAME_BYTES.
MAX_OUTER_FRAME_BYTES = 1024

# Cap on the decoded channel-0 (URST) receive buffer -- mirror device
# mux.OTA_BUFFER_BYTES.
OTA_BUFFER_BYTES = 2048

# Minimum gap enforced between physical writes -- mirror device / mux_host
# default. Opt-in; 0 means no gap enforcement.
DEFAULT_MIN_TX_GAP_MS = 0


class ChannelCodec:
    """Pure encode + stateful deframe of the channel-mux outer frame."""

    def __init__(
        self, ota_channel: int = OTA_CHANNEL, app_channel: int = APP_CHANNEL
    ):
        self._buf = bytearray()
        self._known_channels = (ota_channel, app_channel)
        self.frames_dropped = 0

    def encode(self, channel_id: int, payload: bytes) -> bytes:
        """Return one complete outer frame for ``payload`` on ``channel_id``."""
        return cobs_encode(bytes([channel_id]) + payload) + FRAME_DELIM

    def feed(self, data: bytes) -> None:
        """Append raw received bytes to the internal reassembly buffer."""
        self._buf.extend(data)

    def frames(self):
        """Yield ``(channel_id, payload)`` for every complete outer frame
        currently buffered, consuming them from the buffer.

        Corrupt COBS or an over-long frame is dropped (``frames_dropped``
        incremented) and reception resynchronises on the next delimiter. A
        frame on an unknown channel is silently skipped (matching the
        device ``SerialMux.service()``; no counter bump). A delimiter-free
        buffer past ``MAX_OUTER_FRAME_BYTES`` is cleared.

        The loop is bounded: each pass consumes at least one delimiter byte
        from a finite buffer, and it returns as soon as no delimiter remains.
        """
        idx = self._buf.find(FRAME_DELIM)
        while idx >= 0:
            frame = bytes(self._buf[:idx])
            # Slice reassignment (not `del self._buf[:n]`) to stay aligned
            # with the device mux.py, whose bytearray has no slice deletion.
            self._buf = self._buf[idx + 1 :]
            if frame:
                if len(frame) > MAX_OUTER_FRAME_BYTES:
                    self.frames_dropped += 1
                else:
                    decoded = cobs_decode(frame)
                    if not decoded:
                        self.frames_dropped += 1
                    elif decoded[0] in self._known_channels:
                        yield decoded[0], bytes(decoded[1:])
            idx = self._buf.find(FRAME_DELIM)

        if len(self._buf) > MAX_OUTER_FRAME_BYTES:
            self._buf = bytearray()
            self.frames_dropped += 1

    def reset(self) -> None:
        """Discard the internal reassembly buffer."""
        self._buf = bytearray()


class ChannelSerial:
    """Synchronous serial-like adapter that surfaces only the OTA channel.

    Wraps a real ``serial.Serial`` (``self._ser``) and a ``ChannelCodec``.
    Duck-types the members URST's codec layer and the CLI call on a serial
    object (``write`` / ``flush`` / ``read`` / ``in_waiting`` /
    ``reset_input_buffer`` / ``reset_output_buffer`` / ``close``), applying
    the channel-mux outer frame on the way out and stripping it on the way
    in. Everything not on ``OTA_CHANNEL`` is dropped.

    Single-threaded and synchronous by design -- no locks. ``dtr`` / ``rts``
    are the caller's job on the raw port before wrapping.
    """

    def __init__(
        self, ser, codec=None, min_tx_gap_ms: int = DEFAULT_MIN_TX_GAP_MS
    ):
        self._ser = ser
        self._codec = codec if codec is not None else ChannelCodec()
        self.min_tx_gap_ms = min_tx_gap_ms
        self._decoded = bytearray()
        # Set by flush(); the min-tx-gap is measured from the previous
        # write's flush() return, matching URST's write_frame() (write then
        # flush). No flush => no gap enforcement.
        self._last_write_done_ms: float | None = None

    def write(self, data: bytes) -> int:
        if self.min_tx_gap_ms and self._last_write_done_ms is not None:
            remaining = self.min_tx_gap_ms - (
                _now_ms() - self._last_write_done_ms
            )
            if remaining > 0:
                _sleep_ms(remaining)
        self._ser.write(self._codec.encode(OTA_CHANNEL, data))
        # URST expects the count of application bytes accepted, not the
        # framed length.
        return len(data)

    def flush(self):
        result = self._ser.flush()
        self._last_write_done_ms = _now_ms()
        return result

    def _pump(self) -> None:
        pending = getattr(self._ser, "in_waiting", 0) or 1
        chunk = self._ser.read(pending)
        if chunk:
            self._codec.feed(chunk)
            for channel_id, payload in self._codec.frames():
                if channel_id == OTA_CHANNEL:
                    self._decoded.extend(payload)
        if len(self._decoded) > OTA_BUFFER_BYTES:
            self._decoded = self._decoded[
                len(self._decoded) - OTA_BUFFER_BYTES :
            ]

    def read(self, n: int = 1) -> bytes:
        self._pump()
        if not self._decoded:
            return b""
        out = bytes(self._decoded[:n])
        self._decoded = self._decoded[n:]
        return out

    @property
    def in_waiting(self) -> int:
        self._pump()
        return len(self._decoded)

    def reset_input_buffer(self):
        self._ser.reset_input_buffer()
        self._codec.reset()
        self._decoded = bytearray()

    def reset_output_buffer(self):
        return self._ser.reset_output_buffer()

    def close(self):
        return self._ser.close()
