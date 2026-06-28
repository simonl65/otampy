import builtins

from shared import LoadOTAModule


def test_logger_writes_all_levels_to_file(monkeypatch, tmp_path):
    ota = LoadOTAModule.load(monkeypatch)
    Logger = ota.OTALogger
    log_file = tmp_path / "ota.log"
    logger = Logger(path=str(log_file), min_level="DEBUG")

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


def test_logger_filters_lower_level_messages(monkeypatch, tmp_path):
    ota = LoadOTAModule.load(monkeypatch)
    Logger = ota.OTALogger
    log_file = tmp_path / "ota.log"
    logger = Logger(path=str(log_file), min_level="WARNING")

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


def test_logger_falls_back_to_stdout_when_file_write_fails(monkeypatch, capsys):
    ota = LoadOTAModule.load(monkeypatch)
    Logger = ota.OTALogger
    logger = Logger(path="/invalid/path/ota.log", min_level="DEBUG")

    def raise_os_error(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(builtins, "open", raise_os_error)

    logger.error("failed write")

    captured = capsys.readouterr()
    assert "[ERROR   ] failed write" in captured.out
