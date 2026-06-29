import builtins

from device_otampy.logger import (  # pyright: ignore[reportMissingImports]
    OTALogger,
)


def test_logger_accepts_path(tmp_path):
    log_file = tmp_path / "OTA-NO-PATH.log"
    logger = OTALogger(str(log_file))

    logger.critical("critical message")

    content = log_file.read_text()
    assert "[CRITICAL] critical message" in content


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
