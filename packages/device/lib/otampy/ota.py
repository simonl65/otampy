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

        # boot.py and main.py share an interpreter, so always release the
        # boot-only module after this call. Removing both import references
        # lets GC reclaim its bytecode; a later boot() call can re-import it.
        try:
            run(self._core, callback)
        finally:
            import gc
            import sys

            ota_module_name = OTA.__module__
            package_name = ota_module_name[: ota_module_name.rfind(".")]
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
