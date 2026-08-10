"""
mux.py

Optional helper for projects that share one physical UART between OTAmpy
and their own application traffic. Poll-based rather than threaded -- call
``mux.service()`` frequently from your main loop (or a Timer IRQ /
uasyncio task) to pump bytes in both directions. This keeps it portable
across boards without ``_thread``, and avoids adding concurrency bugs on
top of a UART you're already sharing.

Framing (COBS, matching the host-side companion in ``otampy``'s desktop
tooling):
    COBS_encode(channel_id_byte + payload) + b'\\x00'

Without this, an application that reads the shared UART directly races
the OTA transport for incoming bytes -- whichever side calls ``read()``
first on a given loop tick wins, and the loser silently never sees its
data. That's exactly the failure mode this module exists to prevent:
``OTA(mux.ota_port, ...)`` gets an isolated virtual port for URST framing,
and your own code talks to ``mux.send_app()`` / ``mux.poll_app()``
instead of touching the raw UART.
"""

from urst.codec_layer import cobs_decode, cobs_encode  # type: ignore

DEFAULT_OTA_CHANNEL = 0x00
DEFAULT_APP_CHANNEL = 0x01
_FRAME_DELIM = 0x00
_FRAME_DELIM_BYTES = b"\x00"
MAX_OUTER_FRAME_BYTES = 1024
OTA_BUFFER_BYTES = 2048


class _VirtualPort:
    """Minimal machine.UART-like object for URST's codec layer."""

    def __init__(self, writer_fn, pump_fn, max_rx_bytes=OTA_BUFFER_BYTES):
        self._writer_fn = writer_fn
        self._pump_fn = pump_fn
        self._max_rx_bytes = max_rx_bytes
        self._rx = bytearray()
        self.dropped_bytes = 0

    def _feed(self, payload):
        overflow = len(self._rx) + len(payload) - self._max_rx_bytes
        if overflow > 0:
            dropped = min(overflow, len(self._rx))
            self._rx = self._rx[dropped:]
            self.dropped_bytes += dropped
        if len(payload) > self._max_rx_bytes:
            self.dropped_bytes += len(payload) - self._max_rx_bytes
            payload = payload[-self._max_rx_bytes :]
        self._rx.extend(payload)

    def write(self, data):
        self._writer_fn(bytes(data))
        return len(data)

    def read(self, nbytes=None):
        self._pump_fn()
        if not self._rx:
            return None
        if nbytes is None or nbytes >= len(self._rx):
            out = bytes(self._rx)
            self._rx = bytearray()
        else:
            out = bytes(self._rx[:nbytes])
            self._rx = self._rx[nbytes:]
        return out

    def any(self):
        self._pump_fn()
        return len(self._rx)

    def frame_ready(self):
        """Return whether a complete URST frame is buffered."""
        self._pump_fn()
        first = self._rx.find(b"\x00")
        return first >= 0 and self._rx.find(b"\x00", first + 1) >= 0


class SerialMux:
    def __init__(
        self,
        uart,
        ota_channel=DEFAULT_OTA_CHANNEL,
        app_channel=DEFAULT_APP_CHANNEL,
    ):
        """uart: an already-configured machine.UART instance (the real one).

        ota_channel/app_channel: single-byte channel ids for the two
        logical streams. Must be distinct.
        """
        self._uart = uart
        self._rx_buffer = bytearray()
        self._ota_channel = ota_channel
        self._app_channel = app_channel
        self._app_rx = None
        self.app_dropped = 0
        self.outer_frames_dropped = 0

        self.ota_port = _VirtualPort(
            self._write_channel(ota_channel), self.service
        )
        self._app_write = self._write_channel(app_channel)

    def _write_channel(self, channel_id):
        def _write(payload):
            frame = cobs_encode(bytes([channel_id]) + payload) + b"\x00"
            self._uart.write(frame)

        return _write

    def send_app(self, data):
        self._app_write(data)

    def poll_app(self):
        """Return the newest pending app-channel payload, or ``None``."""
        payload = self._app_rx
        self._app_rx = None
        return payload

    def service(self):
        """Call this often (main loop / timer IRQ) to pump the physical UART."""
        n = self._uart.any()
        if n:
            chunk = self._uart.read(n)
            if chunk:
                self._rx_buffer.extend(chunk)

        while True:
            idx = self._rx_buffer.find(_FRAME_DELIM_BYTES)
            if idx < 0:
                break
            frame = bytes(self._rx_buffer[:idx])
            # Slice reassignment, not `del buf[:n]`: MicroPython's bytearray
            # doesn't support item/slice deletion at all (only CPython's
            # does), so `del` here crashes the device on the first frame
            # ever parsed -- see CHANGELOG.md.
            self._rx_buffer = self._rx_buffer[idx + 1 :]
            if not frame:
                continue
            if len(frame) > MAX_OUTER_FRAME_BYTES:
                self.outer_frames_dropped += 1
                continue
            decoded = cobs_decode(frame)
            if not decoded:
                # Corrupt frame: drop it and resynchronise on the delimiter.
                self.outer_frames_dropped += 1
                continue
            channel_id = decoded[0]
            payload = decoded[1:]
            if channel_id == self._ota_channel:
                self.ota_port._feed(payload)
            elif channel_id == self._app_channel:
                if self._app_rx is not None:
                    self.app_dropped += 1
                self._app_rx = payload
            # Unknown channel ids are intentionally ignored.
        if len(self._rx_buffer) > MAX_OUTER_FRAME_BYTES:
            self._rx_buffer = bytearray()
            self.outer_frames_dropped += 1
