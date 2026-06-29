from . import boot as _boot
from . import manager as _manager
from .core import OTACore


class OTA:
    """
    OTA is the public facade for the OTAmpy library, providing clean, unified
    access to both boot-time update applications and run-time command polling.
    """

    def __init__(self, uart, config=None, logger=None):
        self._core = OTACore(uart, config, logger)

    def boot(self, callback=None):
        """
        Call from boot.py. Checks for any pending updates and applies them.
        """
        _boot.run(self._core, callback)

    def poll(self, callback=None):
        """
        Call from main.py loop. Polls UART transport for incoming OTA commands.
        """
        _manager.poll(self._core, callback)
