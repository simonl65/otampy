from .core import OTACore

__version__ = "1.0.0"


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

    def poll(self, callback=None, heartbeat=None):
        """
        Call from main.py loop. Polls UART transport for incoming OTA commands.

        `heartbeat`, if given, is called periodically during a large CAT/LS
        response's fragment transfer, which can otherwise legitimately take
        far longer than one `poll()` call normally would -- see
        `manager.poll`'s own docstring for how it differs from `callback`.
        """
        from .manager import poll

        poll(self._core, callback, heartbeat=heartbeat)
