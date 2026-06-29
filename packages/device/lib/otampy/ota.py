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
        self._core.logger.debug("OTA Init")

    def boot(self, callback=None):
        """
        Call from boot.py. Checks for any pending updates and applies them.
        """
        self._core.logger.debug("OTA boot run")
        _boot.run(self._core, callback)

    def poll(self, callback=None):
        """
        Call from main.py loop. Polls UART transport for incoming OTA commands.
        """
        self._core.logger.debug("OTA manager poll")
        _manager.poll(self._core, callback)
