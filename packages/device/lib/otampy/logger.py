import time as _time

try:
    import uos as _os
except ImportError:
    import os as _os


_DEBUG = 0
_INFO = 1
_WARNING = 2
_ERROR = 3
_CRITICAL = 4
_ALWAYS = 5
_DISABLED = 6


def _level_value(level):
    if level is None:
        return _DISABLED
    level = level.upper()
    if level == "DEBUG":
        return _DEBUG
    if level == "INFO":
        return _INFO
    if level == "WARNING":
        return _WARNING
    if level == "CRITICAL":
        return _CRITICAL
    if level == "ALWAYS":
        return _ALWAYS
    if level == "NOTSET":
        return _DEBUG
    if level == "NONE":
        return _DISABLED
    return _ERROR


class OTALogger:
    """File logger."""

    def __init__(
        self,
        path="ota.log",
        level="ERROR",
        source="root",
        max_bytes=10240,
        backup_count=1,
        use_ticks=False,
    ):
        self.path = path
        self.source = source
        self.min_level = _level_value(level)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.use_ticks = use_ticks
        self._ensure_dir(path)

    @staticmethod
    def _ensure_dir(filename):
        idx = filename.rfind("/")
        if idx <= 0:
            return

        parts = filename[:idx].split("/")
        path = ""
        for part in parts:
            if not part:
                path = "/"
                continue
            if path == "/":
                path += part
            elif path:
                path += "/" + part
            else:
                path = part
            try:
                _os.mkdir(path)
            except OSError:
                pass

    def _rotate_files(self):
        if self.backup_count > 0:
            for index in range(self.backup_count - 1, 0, -1):
                source = f"{self.path}.{index}"
                destination = f"{self.path}.{index + 1}"
                try:
                    _os.remove(destination)
                except OSError:
                    pass
                try:
                    _os.rename(source, destination)
                except OSError:
                    pass
            destination = self.path + ".1"
            try:
                _os.remove(destination)
            except OSError:
                pass
            try:
                _os.rename(self.path, destination)
            except OSError:
                pass
        else:
            try:
                _os.remove(self.path)
            except OSError:
                pass

    def _write(self, line):
        if self.max_bytes > 0:
            try:
                size = _os.stat(self.path)[6]
            except OSError:
                size = 0
            if size >= self.max_bytes:
                self._rotate_files()

        try:
            with open(self.path, "a") as log_file:
                log_file.write(line + "\n")
        except OSError:
            print(line)

    def _log(self, level_number, level_name, msg, *args):
        if (
            self.min_level == _DISABLED
            or level_number < self.min_level
        ):
            return

        if args:
            try:
                msg = msg % args
            except Exception:
                pass

        if self.use_ticks:
            try:
                timestamp = _time.ticks_ms()
            except AttributeError:
                timestamp = int(_time.time() * 1000)
        else:
            timestamp = int(_time.time())

        self._write(
            f"{timestamp} [{level_name:8}] [{self.source:20}] {msg}"
        )

    def debug(self, msg, *args):
        self._log(_DEBUG, "DEBUG", msg, *args)

    def info(self, msg, *args):
        self._log(_INFO, "INFO", msg, *args)

    def warning(self, msg, *args):
        self._log(_WARNING, "WARNING", msg, *args)

    def error(self, msg, *args):
        self._log(_ERROR, "ERROR", msg, *args)

    def critical(self, msg, *args):
        self._log(_CRITICAL, "CRITICAL", msg, *args)

    def always(self, msg, *args):
        self._log(_ALWAYS, "ALWAYS", msg, *args)
