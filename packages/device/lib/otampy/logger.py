from time import time

try:
    import uos as _os
except ImportError:
    import os as _os


def _make_parent_dirs(path):
    parts = path.split("/")
    if len(parts) < 2:
        return

    current = "/" if path.startswith("/") else ""
    for part in parts[:-1]:
        if not part:
            continue
        if current in ("", "/"):
            current += part
        else:
            current += "/" + part
        try:
            _os.mkdir(current)
        except OSError:
            pass


class OTALogger:
    """
    Fallback logging - Logs messages to a file or stdout on failure
    """

    log_levels = {
        "DEBUG": 0,
        "INFO": 1,
        "WARNING": 2,
        "ERROR": 3,
        "CRITICAL": 4,
    }

    def __init__(self, path="ota.log", level="ERROR"):
        self.path = path
        self.min_level = self.log_levels.get(level, 3)

    def _log(self, level, msg):
        current_level_num = self.log_levels.get(level, 3)
        if current_level_num < self.min_level:
            return
        MIN_TS_WIDTH = 18
        MIN_LEVEL_WIDTH = 8
        ts_part = f"{str(time())[:MIN_TS_WIDTH]:<18}"
        level_part = f"{level[:MIN_LEVEL_WIDTH]:<8}"
        line = "[" + ts_part + "] [" + level_part + "] " + msg + "\n"
        try:
            _make_parent_dirs(self.path)
            with open(self.path, "a") as f:
                f.write(line)
        except OSError:
            print(line, end="")

    def debug(self, msg):
        self._log("DEBUG", msg)

    def info(self, msg):
        self._log("INFO", msg)

    def warning(self, msg):
        self._log("WARNING", msg)

    def error(self, msg):
        self._log("ERROR", msg)

    def critical(self, msg):
        self._log("CRITICAL", msg)
