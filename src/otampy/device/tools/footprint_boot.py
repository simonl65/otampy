"""Temporary boot.py probe for repeatable OTAmpy RAM checkpoints.

This file is a development tool. It is not copied by ``otampy deploy``.
Temporarily install it as ``/boot.py``, enter a raw soft reset, capture its
output, and restore the production boot file immediately afterward.
"""

from array import array

_LABELS = (
    "clean_boot",
    "import_otampy",
    "ota_inputs_ready",
    "ota_constructed",
    "no_flag_boot",
    "first_poll",
    "idle_poll",
)
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

    import micropython

    micropython.mem_info(1)


def _assert_update_flag_absent(config):
    import os

    flag = config.UPDATE_REQUEST_FLAG_FILE
    try:
        os.stat(flag)
    except OSError:
        return
    raise RuntimeError("Refusing footprint probe: update flag exists")


def main():
    import gc

    _checkpoint(gc)

    from src.otampy import OTA

    _checkpoint(gc)

    import src.otampy.device.examples.config as config
    from machine import UART, Pin

    _assert_update_flag_absent(config)
    uart = UART(
        config.OTA_PORT,
        baudrate=config.OTA_BAUDRATE,
        tx=Pin(config.OTA_TX_PIN),
        rx=Pin(config.OTA_RX_PIN),
    )
    _checkpoint(gc)

    ota = OTA(uart, config=config)
    _checkpoint(gc)

    ota.boot()
    _checkpoint(gc)

    ota.poll()
    _checkpoint(gc)

    ota.poll()
    _checkpoint(gc)


main()
