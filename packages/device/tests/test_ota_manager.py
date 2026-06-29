import shared
from device_otampy import manager
from device_otampy.core import OTACore


def test_manager_poll():
    uart = shared.FakeUART()
    logger = shared.FakeLogger()
    core = OTACore(uart, logger=logger)

    manager.poll(core)
