"""Temporary boot.py probe for repeatable OTAmpy RAM checkpoints.

This file is a development tool. It is not copied by ``otampy deploy``.
Temporarily install it as ``/boot.py``, enter a raw soft reset, capture its
output, and restore the production boot file immediately afterward.
"""


def _checkpoint(label, gc):
    before_alloc = gc.mem_alloc()
    before_free = gc.mem_free()
    gc.collect()
    after_alloc = gc.mem_alloc()
    after_free = gc.mem_free()
    print(
        f"OTAMPY_RAM|{label}|{before_alloc}|{before_free}|{after_alloc}|{after_free}"
    )


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

    _checkpoint("clean_boot", gc)

    from otampy import OTA, OTALogger

    _checkpoint("import_otampy", gc)

    import config
    from log_to_file import Logger
    from machine import UART, Pin

    _assert_update_flag_absent(config)
    logger = Logger(
        config.LOG_FILE,
        "footprint",
        level=config.LOG_LEVEL,
    ) or OTALogger(config.LOG_FILE, level=config.LOG_LEVEL)
    uart = UART(
        config.OTA_PORT,
        baudrate=config.OTA_BAUDRATE,
        tx=Pin(config.OTA_TX_PIN),
        rx=Pin(config.OTA_RX_PIN),
    )
    _checkpoint("ota_inputs_ready", gc)

    ota = OTA(uart, config=config, logger=logger)
    _checkpoint("ota_constructed", gc)

    ota.boot()
    _checkpoint("no_flag_boot", gc)

    ota.poll()
    _checkpoint("first_poll", gc)

    ota.poll()
    _checkpoint("idle_poll", gc)

    import micropython

    micropython.mem_info(1)


main()
