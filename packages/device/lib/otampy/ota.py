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


# =============================================================================
# Legacy Support (Backward Compatibility)
# =============================================================================


class OTABoot:
    """
    Legacy wrapper for boot-time logic.
    """

    def __init__(self, uart, config=None, logger=None):
        self._ota = OTA(uart, config, logger)

    def check_for_update_file(self, callback=None):
        self._ota.boot(callback)


class OTAManager:
    """
    Legacy wrapper for run-time logic.
    """

    def __init__(self, uart, config=None, logger=None):
        self._ota = OTA(uart, config, logger)
        self.uart = self._ota._core.uart
        self.transport = self._ota._core.transport

    def check_for_update(self, callback=None):
        self._ota.poll(callback)

    def ready_for_update(self):
        print("TODO: Implement ready_for_update")
