"""Provides logging functionality that sends messages to a serial port using the URST protocol."""

# TODO: Get the original from XOTA?
import sys


class Logger:
    def __init__(self, port):
        self.port = port

    def _get_caller_name(self):
        try:
            # We look for the first frame outside this module
            frame = sys._getframe(1)
            module_name = self.__class__.__module__
            while frame:
                name = frame.f_globals.get("__name__")
                if name != module_name:
                    if name == "__main__":
                        filename = frame.f_code.co_filename
                        if filename and not filename.startswith("<"):
                            return filename.split("/")[-1].split("\\")[-1]
                    return name
                frame = frame.f_back
        except Exception:
            pass
        return __name__

    def _send(self, level, message, source):
        print(f"[{level}] [{source}] {message}")
        pass

    def critical(self, message, source=None):
        if source is None:
            source = self._get_caller_name()
        self._send("CRITICAL", message, source)

    def debug(self, message, source=None):
        if source is None:
            source = self._get_caller_name()
        self._send("DEBUG", message, source)

    def error(self, message, source=None):
        if source is None:
            source = self._get_caller_name()
        self._send("ERROR", message, source)

    def warn(self, message, source=None):
        if source is None:
            source = self._get_caller_name()
        self._send("WARN ", message, source)

    def info(self, message, source=None):
        if source is None:
            source = self._get_caller_name()
        self._send("INFO ", message, source)
