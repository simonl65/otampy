from time import time

try:
    import uos as _os
except ImportError:
    import os as _os


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
        self._ensure_dir(path)

    @staticmethod
    def _ensure_dir(filename: str) -> None:
        # MicroPython's `os` module has no `os.path` and (on most ports) no
        # `os.makedirs`, so directories are split out and created manually,
        # one path segment at a time.
        idx = filename.rfind("/")
        if idx <= 0:
            return  # no directory component (or root-level file)

        directory = filename[:idx]
        parts = directory.split("/")
        path = ""
        for part in parts:
            if not part:
                # leading slash on an absolute path
                path = "/"
                continue
            if path == "" or path == "/":
                path = part if path == "" else "/" + part
            else:
                path = path + "/" + part
            if path == "/":
                continue
            try:
                _os.mkdir(path)
            except OSError:
                pass  # already exists (or can't be created; caught later on write)

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
