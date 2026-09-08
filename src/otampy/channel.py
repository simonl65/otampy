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

from urst.codec_layer import cobs_decode, cobs_encode  # type: ignore

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

    def __init__(self):
        self._buf = bytearray()
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
        delimiter-free buffer past ``MAX_OUTER_FRAME_BYTES`` is cleared.

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
                    if decoded:
                        yield decoded[0], bytes(decoded[1:])
                    else:
                        self.frames_dropped += 1
            idx = self._buf.find(FRAME_DELIM)

        if len(self._buf) > MAX_OUTER_FRAME_BYTES:
            self._buf = bytearray()
            self.frames_dropped += 1

    def reset(self) -> None:
        """Discard the internal reassembly buffer."""
        self._buf = bytearray()
