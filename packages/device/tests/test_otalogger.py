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
    assert "[CRITICAL] [root                ] critical message" in content


def test_logger_creates_missing_parent_dirs(tmp_path):
    log_file = tmp_path / "logs" / "nested" / "ota.log"
    logger = OTALogger(str(log_file), level="DEBUG")

    logger.error("nested message")

    content = log_file.read_text()
    assert "[ERROR   ] [root                ] nested message" in content


def test_logger_writes_all_levels_to_file(tmp_path):
    log_file = tmp_path / "ota.log"
    logger = OTALogger(path=str(log_file), level="DEBUG")

    logger.debug("debug message")
    logger.info("info message")
    logger.warning("warning message")
    logger.error("error message")
    logger.critical("critical message")
    logger.always("always message")

    content = log_file.read_text()
    assert "[DEBUG   ] [root                ] debug message" in content
    assert "[INFO    ] [root                ] info message" in content
    assert "[WARNING ] [root                ] warning message" in content
    assert "[ERROR   ] [root                ] error message" in content
    assert "[CRITICAL] [root                ] critical message" in content
    assert "[ALWAYS  ] [root                ] always message" in content


def test_logger_filters_lower_level_messages(tmp_path):
    log_file = tmp_path / "ota.log"
    logger = OTALogger(path=str(log_file), level="WARNING")

    logger.debug("debug message")
    logger.info("info message")
    logger.warning("warning message")
    logger.error("error message")
    logger.critical("critical message")

    content = log_file.read_text()
    assert "[DEBUG   ] [root                ] debug message" not in content
    assert "[INFO    ] [root                ] info message" not in content
    assert "[WARNING ] [root                ] warning message" in content
    assert "[ERROR   ] [root                ] error message" in content
    assert "[CRITICAL] [root                ] critical message" in content


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
    assert "[ERROR   ] [root                ] failed write" in captured.out


def test_logger_formats_source_and_arguments(tmp_path):
    log_file = tmp_path / "ota.log"
    logger = OTALogger(
        path=str(log_file),
        level="DEBUG",
        source="main.py",
    )

    logger.error("failure %s: %d", "code", 42)

    line = log_file.read_text().rstrip()
    timestamp, message = line.split(" ", 1)
    assert timestamp.isdigit()
    assert message == (
        "[ERROR   ] [main.py             ] failure code: 42"
    )


def test_logger_none_disables_all_levels(tmp_path):
    log_file = tmp_path / "ota.log"
    logger = OTALogger(path=str(log_file), level="NONE")

    logger.critical("critical message")
    logger.always("always message")

    assert not log_file.exists()


def test_logger_always_level_only_writes_always(tmp_path):
    log_file = tmp_path / "ota.log"
    logger = OTALogger(path=str(log_file), level="ALWAYS")

    logger.critical("critical message")
    logger.always("always message")

    content = log_file.read_text()
    assert "critical message" not in content
    assert "always message" in content


def test_logger_rotates_with_backups(tmp_path):
    log_file = tmp_path / "ota.log"
    logger = OTALogger(
        path=str(log_file),
        level="DEBUG",
        max_bytes=1,
        backup_count=2,
    )

    logger.info("first")
    logger.info("second")
    logger.info("third")

    assert log_file.exists()
    assert (tmp_path / "ota.log.1").exists()
    assert (tmp_path / "ota.log.2").exists()


def test_logger_rotates_without_backup(tmp_path):
    log_file = tmp_path / "ota.log"
    logger = OTALogger(
        path=str(log_file),
        level="DEBUG",
        max_bytes=1,
        backup_count=0,
    )

    logger.info("first")
    logger.info("second")

    content = log_file.read_text()
    assert "first" not in content
    assert "second" in content
    assert not (tmp_path / "ota.log.1").exists()


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
