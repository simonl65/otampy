"""Peak-heap stress matrix for FP-03.

This development-only script creates and removes only ``/fp-stress-*`` paths.
Run it on a test device with ``mpremote run``; it is not deployed by otampy.
"""

from array import array

_CAT_PATH = "/fp-stress-cat.txt"
_LS_PATH = "/fp-stress-dir"
_UPDATE_PATH = "/fp-stress-update"
_LABELS = (
    "cat_16k",
    "ls_64",
    "update_chunk_256",
    "manifest_32",
    "checksum_failure",
    "interrupted_update",
)
_VALUES_PER_SCENARIO = 4
_RESULTS = array("I", [0] * (len(_LABELS) * _VALUES_PER_SCENARIO))


class _StopProbe(Exception):
    pass


class _Logger:
    min_level = 4

    def debug(self, _message):
        pass

    def error(self, _message):
        pass

    def warning(self, _message):
        pass


class _Core:
    def __init__(self, transport):
        self.config = {"UPDATE_REQUEST_FLAG_FILE": None}
        self.logger = _Logger()
        self.transport = transport


class _Machine:
    @staticmethod
    def reset():
        pass


class _Transport:
    def __init__(self, gc):
        self._gc = gc
        self.minimum_free = gc.mem_free()
        self.file_ok = 0
        self.chunk_ack = 0
        self.commit_ok = 0
        self.checksum_error = 0

    def _sample(self):
        free = self._gc.mem_free()
        if free < self.minimum_free:
            self.minimum_free = free

    def send(self, response):
        # Sample before inspecting the response, while production temporaries
        # and the complete response are still live on the caller's stack.
        self._sample()
        if response == b"FILE_OK":
            self.file_ok += 1
        elif response.startswith(b"CHUNK_ACK:"):
            self.chunk_ack += 1
        elif response == b"COMMIT_OK":
            self.commit_ok += 1
        elif response == b"FILE_ERR:Checksum mismatch":
            self.checksum_error += 1
        elif response in (b"SPACE_OK", b"READY"):
            pass
        elif response.startswith((b"ERROR:", b"FILE_ERR:", b"CHUNK_ERR:")):
            raise RuntimeError(response)


class _FragmentProtocol:
    def __init__(self, transport):
        self._transport = transport
        self._message_id = None
        self._next_fragment = 0
        self._total_fragments = 0

    def send_reliable(self, frame_type, payload):
        transport = self._transport
        transport._sample()
        if frame_type != 0x04 or len(payload) < 4:
            raise RuntimeError("invalid streamed response frame")

        message_id = payload[0]
        fragment_number = payload[1]
        total_fragments = payload[2]
        data_length = payload[3]
        if (
            data_length != len(payload) - 4
            or fragment_number != self._next_fragment
        ):
            raise RuntimeError("invalid streamed response sequence")
        if self._message_id is None:
            self._message_id = message_id
            self._total_fragments = total_fragments
        elif (
            message_id != self._message_id
            or total_fragments != self._total_fragments
        ):
            raise RuntimeError("streamed response header changed")

        transport._accept_fragment(payload[4:])
        self._next_fragment += 1
        if self._next_fragment == self._total_fragments:
            transport._finish_fragments()
        return True


class _ManagerTransport(_Transport):
    def __init__(self, gc, packet, validator, stream_validator=None):
        super().__init__(gc)
        self._packet = packet
        self._validator = validator
        self._stream_validator = stream_validator
        self._fragment_response = (
            None if stream_validator is not None else bytearray()
        )
        self._msg_id = 0
        self.protocol = _FragmentProtocol(self)
        self.response_seen = False

    def read(self):
        self._sample()
        packet = self._packet
        self._packet = None
        return packet

    def send(self, response):
        self._sample()
        self._validator(response)
        self.response_seen = True

    def _accept_fragment(self, fragment):
        if self._stream_validator is not None:
            self._stream_validator.feed(fragment)
        else:
            self._fragment_response.extend(fragment)

    def _finish_fragments(self):
        if self._stream_validator is not None:
            self._stream_validator.finish()
        else:
            self._validator(bytes(self._fragment_response))
            self._fragment_response = None
        self.response_seen = True


class _CatStreamValidator:
    def __init__(self):
        self._offset = 0

    def feed(self, fragment):
        prefix = b"CAT_OK:"
        offset = self._offset
        for value in fragment:
            expected = prefix[offset] if offset < len(prefix) else ord("x")
            if value != expected:
                raise RuntimeError("CAT streamed-content assertion failed")
            offset += 1
        self._offset = offset

    def finish(self):
        if self._offset != 7 + 16 * 1024:
            raise RuntimeError("CAT streamed-length assertion failed")


class _PacketTransport(_Transport):
    def __init__(self, gc, packets):
        super().__init__(gc)
        self._packets = packets
        self._index = 0

    def read(self):
        self._sample()
        if self._index == len(self._packets):
            raise _StopProbe
        packet = self._packets[self._index]
        self._index += 1
        return packet


class _ManifestTransport(_Transport):
    def __init__(self, gc, digest, encoded, file_count):
        super().__init__(gc)
        self._digest = digest
        self._encoded = encoded
        self._file_count = file_count
        self._packet_index = 0

    def read(self):
        self._sample()
        index = self._packet_index
        self._packet_index += 1
        if index == 0:
            return f"UPDATE_START:{self._file_count}:{self._file_count}".encode()
        if index == 1 + self._file_count * 3:
            return b"UPDATE_COMMIT"

        file_index = (index - 1) // 3
        phase = (index - 1) % 3
        if phase == 0:
            path = f"{_UPDATE_PATH}/m{file_index:02d}"
            return f"FILE_START:{path}:1:{self._digest}".encode()
        if phase == 1:
            return b"CHUNK:0:" + self._encoded
        return b"FILE_END"


def _assert_absent(os, path):
    try:
        os.stat(path)
    except OSError:
        return
    raise RuntimeError(f"Refusing stress probe: {path} already exists")


def _remove_tree(os, path):
    try:
        mode = os.stat(path)[0]
    except OSError:
        return
    if mode & 0x4000:
        for item in os.listdir(path):
            _remove_tree(os, path.rstrip("/") + "/" + item)
        os.rmdir(path)
    else:
        os.remove(path)


def _record(index, baseline, minimum, post_cleanup):
    offset = index * _VALUES_PER_SCENARIO
    _RESULTS[offset] = baseline
    _RESULTS[offset + 1] = minimum
    _RESULTS[offset + 2] = baseline - minimum
    _RESULTS[offset + 3] = post_cleanup


def _run_measured(gc, os, index, operation, cleanup):
    gc.collect()
    baseline = gc.mem_free()
    transport = operation()
    minimum = transport.minimum_free
    cleanup()
    transport = None
    gc.collect()
    _record(index, baseline, minimum, gc.mem_free())


def _cat_scenario(gc, manager):
    def validate(response):
        if (
            len(response) != 7 + 16 * 1024
            or not response.startswith(b"CAT_OK:")
            or response[7:23] != b"x" * 16
            or response[-16:] != b"x" * 16
        ):
            raise RuntimeError("CAT functional assertion failed")

    transport = _ManagerTransport(
        gc,
        f"CAT:{_CAT_PATH}".encode(),
        validate,
        _CatStreamValidator(),
    )
    manager.poll(_Core(transport))
    if not transport.response_seen:
        raise RuntimeError("CAT did not respond")
    return transport


def _ls_scenario(gc, manager):
    def validate(response):
        if not response.startswith(b"LS_OK:"):
            raise RuntimeError("LS functional assertion failed")
        entries = response[6:].split(b",")
        if len(entries) != 64 or len(set(entries)) != 64:
            raise RuntimeError("LS entry assertion failed")
        for index in range(64):
            if f"f{index:02d}".encode() not in entries:
                raise RuntimeError("LS filename assertion failed")

    transport = _ManagerTransport(gc, f"LS:{_LS_PATH}".encode(), validate)
    manager.poll(_Core(transport))
    if not transport.response_seen:
        raise RuntimeError("LS did not respond")
    return transport


def _run_update(sys, boot, core):
    machine = sys.modules.get("machine")
    try:
        sys.modules["machine"] = _Machine()
        boot._run_default_update_loop(core)
    finally:
        if machine is None:
            del sys.modules["machine"]
        else:
            sys.modules["machine"] = machine


def _single_update_packets(binascii, hashlib, payload, digest=None):
    actual_digest = binascii.hexlify(hashlib.sha256(payload).digest()).decode()
    return [
        f"UPDATE_START:1:{len(payload)}".encode(),
        f"FILE_START:{_UPDATE_PATH}/single:{len(payload)}:{digest or actual_digest}".encode(),
        b"CHUNK:0:" + binascii.b2a_base64(payload).strip(),
        b"FILE_END",
        b"UPDATE_COMMIT",
    ]


def main():
    import binascii
    import gc
    import hashlib
    import os
    import sys

    from otampy import boot, manager

    for path in (_CAT_PATH, _LS_PATH, _UPDATE_PATH):
        _assert_absent(os, path)

    try:
        with open(_CAT_PATH, "wb") as stress_file:
            block = b"x" * 256
            for _ in range(64):
                stress_file.write(block)
        _run_measured(
            gc,
            os,
            0,
            lambda: _cat_scenario(gc, manager),
            lambda: _remove_tree(os, _CAT_PATH),
        )

        os.mkdir(_LS_PATH)
        for index in range(64):
            with open(f"{_LS_PATH}/f{index:02d}", "wb"):
                pass
        _run_measured(
            gc,
            os,
            1,
            lambda: _ls_scenario(gc, manager),
            lambda: _remove_tree(os, _LS_PATH),
        )

        os.mkdir(_UPDATE_PATH)
        payload = bytes(index & 0xFF for index in range(256))
        packets = _single_update_packets(binascii, hashlib, payload)

        def update_chunk():
            transport = _PacketTransport(gc, packets)
            _run_update(sys, boot, _Core(transport))
            if (
                transport.file_ok != 2
                or transport.chunk_ack != 1
                or transport.commit_ok != 1
            ):
                raise RuntimeError("maximum-chunk update assertion failed")
            return transport

        _run_measured(
            gc,
            os,
            2,
            update_chunk,
            lambda: _remove_tree(os, _UPDATE_PATH),
        )

        os.mkdir(_UPDATE_PATH)
        one_byte = b"x"
        digest = binascii.hexlify(hashlib.sha256(one_byte).digest()).decode()
        encoded = binascii.b2a_base64(one_byte).strip()

        def many_files():
            transport = _ManifestTransport(gc, digest, encoded, 32)
            _run_update(sys, boot, _Core(transport))
            if (
                transport.file_ok != 64
                or transport.chunk_ack != 32
                or transport.commit_ok != 1
            ):
                raise RuntimeError("many-file update assertion failed")
            for index in range(32):
                with open(f"{_UPDATE_PATH}/m{index:02d}", "rb") as manifest_file:
                    if manifest_file.read() != one_byte:
                        raise RuntimeError("many-file content assertion failed")
            return transport

        _run_measured(
            gc,
            os,
            3,
            many_files,
            lambda: _remove_tree(os, _UPDATE_PATH),
        )

        os.mkdir(_UPDATE_PATH)
        bad_packets = _single_update_packets(
            binascii,
            hashlib,
            b"bad checksum",
            "0" * 64,
        )[:-1]

        def failed_checksum():
            transport = _PacketTransport(gc, bad_packets)
            try:
                _run_update(sys, boot, _Core(transport))
            except _StopProbe:
                pass
            if transport.checksum_error != 1:
                raise RuntimeError("checksum failure assertion failed")
            try:
                os.stat(_UPDATE_PATH + "/single.ota")
            except OSError:
                return transport
            raise RuntimeError("failed checksum left its staging file")

        _run_measured(
            gc,
            os,
            4,
            failed_checksum,
            lambda: _remove_tree(os, _UPDATE_PATH),
        )

        os.mkdir(_UPDATE_PATH)
        interrupted_packets = _single_update_packets(
            binascii,
            hashlib,
            b"interrupted",
        )[:3]

        def interrupted_update():
            transport = _PacketTransport(gc, interrupted_packets)
            try:
                _run_update(sys, boot, _Core(transport))
            except _StopProbe:
                pass
            if transport.file_ok != 1 or transport.chunk_ack != 1:
                raise RuntimeError("interrupted update assertion failed")
            try:
                os.stat(_UPDATE_PATH + "/single")
                raise RuntimeError("interrupted update created its target")
            except OSError:
                pass
            if os.stat(_UPDATE_PATH + "/single.ota")[0] & 0x4000:
                raise RuntimeError("interrupted staging path is not a file")
            return transport

        _run_measured(
            gc,
            os,
            5,
            interrupted_update,
            lambda: _remove_tree(os, _UPDATE_PATH),
        )
    finally:
        for path in (_CAT_PATH, _LS_PATH, _UPDATE_PATH):
            _remove_tree(os, path)

    for index, label in enumerate(_LABELS):
        offset = index * _VALUES_PER_SCENARIO
        print(
            f"OTAMPY_STRESS|{label}|"
            f"{_RESULTS[offset]}|{_RESULTS[offset + 1]}|"
            f"{_RESULTS[offset + 2]}|{_RESULTS[offset + 3]}|PASS"
        )


main()
