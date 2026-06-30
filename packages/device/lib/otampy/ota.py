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
        from .boot import run

        try:
            run(self._core, callback)
        finally:
            import gc
            import sys

            package_name = __package__
            module_name = package_name + ".boot"
            package = sys.modules.get(package_name)

            try:
                del sys.modules[module_name]
            except KeyError:
                pass

            if package is not None:
                try:
                    delattr(package, "boot")
                except AttributeError:
                    pass

            del run
            gc.collect()

    def poll(self, callback=None):
        """
        Call from main.py loop. Polls UART transport for incoming OTA commands.
        """
        from .manager import poll

        poll(self._core, callback)
