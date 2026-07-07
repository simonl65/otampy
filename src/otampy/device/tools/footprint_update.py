"""Controlled OTA update RAM probe for FP-01.

This development-only script writes and removes ``/footprint-probe.txt`` and
its staging/flag files. Run it only on a test device after explicit approval.
It is not copied by ``otampy deploy``.
"""

from array import array

_FLAG_PATH = "/footprint-update.flag"
_TARGET_PATH = "/footprint-probe.txt"
_LABELS = ("flagged_boot", "update_chunk", "update_commit")
_VALUES_PER_CHECKPOINT = 4
_RAM_RESULTS = array(
    "I",
    [0] * (len(_LABELS) * _VALUES_PER_CHECKPOINT),
)
_result_index = 0


def _checkpoint(gc):
    global _result_index

    before_alloc = gc.mem_alloc()
    before_free = gc.mem_free()
    gc.collect()
    after_alloc = gc.mem_alloc()
    after_free = gc.mem_free()

    offset = _result_index * _VALUES_PER_CHECKPOINT
    _RAM_RESULTS[offset] = before_alloc
    _RAM_RESULTS[offset + 1] = before_free
    _RAM_RESULTS[offset + 2] = after_alloc
    _RAM_RESULTS[offset + 3] = after_free
    _result_index += 1


def print_results():
    for index, label in enumerate(_LABELS):
        offset = index * _VALUES_PER_CHECKPOINT
        print(
            f"OTAMPY_RAM|{label}|"
            f"{_RAM_RESULTS[offset]}|{_RAM_RESULTS[offset + 1]}|"
            f"{_RAM_RESULTS[offset + 2]}|{_RAM_RESULTS[offset + 3]}"
        )


class _Logger:
    min_level = 4

    def debug(self, _message):
        pass

    def error(self, _message):
        pass


class _Transport:
    def __init__(self, packets, gc):
        self._packets = packets
        self._index = 0
        self._gc = gc

    def read(self):
        packet = self._packets[self._index]
        self._index += 1
        return packet

    def send(self, response):
        if (
            response == b"READY"
            or response.startswith(b"CHUNK_ACK:")
            or response == b"COMMIT_OK"
        ):
            _checkpoint(self._gc)


class _Core:
    def __init__(self, transport):
        self.config = {"UPDATE_REQUEST_FLAG_FILE": _FLAG_PATH}
        self.logger = _Logger()
        self.transport = transport


class _Machine:
    @staticmethod
    def reset():
        pass


def _remove_if_present(os, path):
    try:
        os.remove(path)
    except OSError:
        pass


def _assert_absent(os, path):
    try:
        os.stat(path)
    except OSError:
        return
    raise RuntimeError(f"Refusing update probe: {path} already exists")


def main():
    import binascii
    import gc
    import hashlib
    import os
    import sys

    from src.otampy import boot

    payload = b"probe"
    digest = binascii.hexlify(hashlib.sha256(payload).digest()).decode()
    encoded = binascii.b2a_base64(payload).strip()
    packets = [
        b"UPDATE_START:1:5",
        f"FILE_START:{_TARGET_PATH}:5:{digest}".encode(),
        b"CHUNK:0:" + encoded,
        b"FILE_END",
        b"UPDATE_COMMIT",
    ]
    core = _Core(_Transport(packets, gc))

    _assert_absent(os, _FLAG_PATH)
    _assert_absent(os, _TARGET_PATH)
    _assert_absent(os, _TARGET_PATH + ".ota")
    with open(_FLAG_PATH, "w") as flag_file:
        flag_file.write("1")

    machine = sys.modules.get("machine")
    try:
        sys.modules["machine"] = _Machine()
        boot.run(core)
    finally:
        if machine is None:
            del sys.modules["machine"]
        else:
            sys.modules["machine"] = machine
        _remove_if_present(os, _FLAG_PATH)
        _remove_if_present(os, _TARGET_PATH)
        _remove_if_present(os, _TARGET_PATH + ".ota")


main()
