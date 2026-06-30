import builtins

import device_otampy.logger as logger_module
from device_otampy.logger import (  # pyright: ignore[reportMissingImports]
    OTALogger,
)


def test_logger_accepts_path(tmp_path):
    log_file = tmp_path / "OTA-NO-PATH.log"
    logger = OTALogger(str(log_file))

    logger.critical("critical message")

    content = log_file.read_text()
    assert "[CRITICAL] critical message" in content


def test_logger_creates_missing_parent_dirs(tmp_path):
    log_file = tmp_path / "logs" / "nested" / "ota.log"
    logger = OTALogger(str(log_file), level="DEBUG")

    logger.error("nested message")

    content = log_file.read_text()
    assert "[ERROR   ] nested message" in content


def test_logger_writes_all_levels_to_file(tmp_path):
    log_file = tmp_path / "ota.log"
    logger = OTALogger(path=str(log_file), level="DEBUG")

    logger.debug("debug message")
    logger.info("info message")
    logger.warning("warning message")
    logger.error("error message")
    logger.critical("critical message")

    content = log_file.read_text()
    assert "[DEBUG   ] debug message" in content
    assert "[INFO    ] info message" in content
    assert "[WARNING ] warning message" in content
    assert "[ERROR   ] error message" in content
    assert "[CRITICAL] critical message" in content


def test_logger_filters_lower_level_messages(tmp_path):
    log_file = tmp_path / "ota.log"
    logger = OTALogger(path=str(log_file), level="WARNING")

    logger.debug("debug message")
    logger.info("info message")
    logger.warning("warning message")
    logger.error("error message")
    logger.critical("critical message")

    content = log_file.read_text()
    assert "[DEBUG   ] debug message" not in content
    assert "[INFO    ] info message" not in content
    assert "[WARNING ] warning message" in content
    assert "[ERROR   ] error message" in content
    assert "[CRITICAL] critical message" in content


def test_logger_falls_back_to_stdout_when_file_write_fails(capsys):
    logger = OTALogger(path="/invalid/path/ota.log", level="DEBUG")

    def raise_os_error(*args, **kwargs):
        raise OSError("disk full")

    original_open = builtins.open
    builtins.open = raise_os_error
    try:
        logger.error("failed write")
    finally:
        builtins.open = original_open

    captured = capsys.readouterr()
    assert "[ERROR   ] failed write" in captured.out


def test_ensure_dir_creates_parent_directories(tmp_path):
    log_file = tmp_path / "logs" / "nested" / "ota.log"
    logger_module.OTALogger._ensure_dir(str(log_file))

    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / "logs" / "nested").is_dir()


def test_ensure_logfile_at_root_is_handled_correctly(tmp_path, monkeypatch):
    log_file = tmp_path / "ota.log"
    original_open = builtins.open

    def redirect_root_log(path, *args, **kwargs):
        if path == "/ota.log":
            path = log_file
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", redirect_root_log)

    logger = OTALogger(path="/ota.log", level="DEBUG")
    logger.error("root message")

    assert log_file.exists()
    assert "root message" in log_file.read_text()
