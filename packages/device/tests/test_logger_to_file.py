import importlib
import os
import sys

import pytest

# Add packages/device/lib to sys.path so we can import logger
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib"))
)

Logger = importlib.import_module("Log_to_file").Logger


@pytest.fixture(autouse=True)
def reset_logger():
    """Reset the Logger singleton before each test to ensure test isolation."""
    Logger._instance = None
    Logger._current_log_level = Logger._default_log_level
    Logger._log_file = None
    Logger._log_file_path = None
    yield
    # Teardown: close any open log file handle after each test
    if Logger._instance and Logger._log_file and not Logger._log_file.closed:
        Logger._log_file.close()
    Logger._instance = None


def test_file_logger_explicit_source(tmp_path):
    """Test that all public logging methods write to a file and respect an explicitly provided source."""
    log_file = tmp_path / "test.log"
    logger = Logger(level="DEBUG", log_file=str(log_file))

    logger.debug("Debug message", source="custom_debug")
    with open(log_file) as f:
        content = f.read()
    assert "[DEBUG   ] [custom_debug        ] Debug message\n" in content

    logger.info("Info message", source="custom_info")
    with open(log_file) as f:
        content = f.read()
    assert "[INFO    ] [custom_info         ] Info message\n" in content

    logger.warn("Warning message", source="custom_warn")
    with open(log_file) as f:
        content = f.read()
    assert "[WARN    ] [custom_warn         ] Warning message\n" in content

    logger.error("Error message", source="custom_error")
    with open(log_file) as f:
        content = f.read()
    assert "[ERROR   ] [custom_error        ] Error message\n" in content

    logger.critical("Critical message", source="custom_critical")
    with open(log_file) as f:
        content = f.read()
    assert "[CRITICAL] [custom_critical     ] Critical message\n" in content

    logger.close()


def test_file_logger_omitted_source_same_module(tmp_path):
    """Test that public logging methods use the calling module's name when source is omitted and logging to file."""
    log_file = tmp_path / "test.log"
    logger = Logger(level="DEBUG", log_file=str(log_file))

    # In this test, the calling module's name is the current module's __name__
    expected_module = __name__.ljust(20)

    logger.debug("Debug message")
    with open(log_file) as f:
        content = f.read()
    assert f"[DEBUG   ] [{expected_module}] Debug message\n" in content

    logger.info("Info message")
    with open(log_file) as f:
        content = f.read()
    assert f"[INFO    ] [{expected_module}] Info message\n" in content

    logger.warn("Warning message")
    with open(log_file) as f:
        content = f.read()
    assert f"[WARN    ] [{expected_module}] Warning message\n" in content

    logger.error("Error message")
    with open(log_file) as f:
        content = f.read()
    assert f"[ERROR   ] [{expected_module}] Error message\n" in content

    logger.critical("Critical message")
    with open(log_file) as f:
        content = f.read()
    assert f"[CRITICAL] [{expected_module}] Critical message\n" in content

    logger.close()


def test_file_logger_omitted_source_different_module(tmp_path):
    """Test that public logging methods resolve module name correctly when called from another module and logging to file."""
    log_file = tmp_path / "test.log"
    logger = Logger(level="DEBUG", log_file=str(log_file))

    # We dynamically compile a function and run it inside a namespace simulating a different module
    namespace = {"logger": logger}
    exec(
        "def log_debug():\n"
        "    logger.debug('Debug message from different module')\n"
        "def log_info():\n"
        "    logger.info('Info message from different module')\n"
        "def log_warn():\n"
        "    logger.warn('Warning message from different module')\n"
        "def log_error():\n"
        "    logger.error('Error message from different module')\n"
        "def log_critical():\n"
        "    logger.critical('Critical message from different module')\n",
        namespace,
    )
    namespace["__name__"] = "mock_external_module"

    namespace["log_debug"]()
    with open(log_file) as f:
        content = f.read()
    assert (
        "[DEBUG   ] [mock_external_module] Debug message from different module\n"
        in content
    )

    namespace["log_info"]()
    with open(log_file) as f:
        content = f.read()
    assert (
        "[INFO    ] [mock_external_module] Info message from different module\n"
        in content
    )

    namespace["log_warn"]()
    with open(log_file) as f:
        content = f.read()
    assert (
        "[WARN    ] [mock_external_module] Warning message from different module\n"
        in content
    )

    namespace["log_error"]()
    with open(log_file) as f:
        content = f.read()
    assert (
        "[ERROR   ] [mock_external_module] Error message from different module\n"
        in content
    )

    namespace["log_critical"]()
    with open(log_file) as f:
        content = f.read()
    assert (
        "[CRITICAL] [mock_external_module] Critical message from different module\n"
        in content
    )

    logger.close()


def test_file_logger_omitted_source_main_module(tmp_path):
    """Test that if the calling module name is '__main__', we fall back to the calling module's filename basename in file logging."""
    log_file = tmp_path / "test.log"
    logger = Logger(level="DEBUG", log_file=str(log_file))

    namespace = {"logger": logger}
    code = compile(
        "def log_info():\n    logger.info('Message from main')\n",
        "/home/simon/Documents/_ELECTRONICS/otampy/packages/device/mock_temp_script.py",
        "exec",
    )
    exec(code, namespace)
    namespace["__name__"] = "__main__"

    namespace["log_info"]()
    with open(log_file) as f:
        content = f.read()
    assert "[INFO    ] [mock_temp_script.py ] Message from main\n" in content

    logger.close()


def test_delete_log_file(tmp_path):
    """Test that Logger can delete a named log file, including active and inactive log files."""
    inactive_log = tmp_path / "inactive.log"
    active_log = tmp_path / "active.log"

    # Create an inactive log file with some content
    with open(inactive_log, "w") as f:
        f.write("Some old logs\n")

    logger = Logger(level="DEBUG", log_file=str(active_log))
    logger.info("Active log message")

    assert os.path.exists(inactive_log)
    assert os.path.exists(active_log)

    # 1. Delete the inactive log file
    logger.delete_log_file(str(inactive_log))
    assert not os.path.exists(inactive_log)
    assert os.path.exists(active_log)

    # 2. Delete the active log file
    logger.delete_log_file(str(active_log))
    assert not os.path.exists(active_log)

    logger.close()


def test_logger_without_filepath(capsys):
    logger = Logger(level="DEBUG")

    logger.debug("Debug message", source="test_logger_without_filepath")
    # Assert that the message is printed to stdout
    captured = capsys.readouterr().out
    assert (
        "[DEBUG   ] [test_logger_without_filepath] Debug message\n" in captured
    )

    logger.close()


def test_logger_with_incorrect_log_level(capsys):
    # Test that passing an invalid level string does not raise an exception,
    # and that an error message is emitted to stdout instead.
    logger = Logger("/test.log")

    try:
        logger.debug("Debug message", source="my_module")
    except Exception as e:
        raise AssertionError(
            f"Logger raised an exception with invalid parameters: {e}"
        ) from None

    captured = capsys.readouterr().out
    assert (
        "[ERROR   ] [test_logger_to_file ] Invalid log level string provided to Logger.\n"
        in captured
    )

    logger.close()


def test_logger_with_missing_filepath(capsys):
    logger = Logger("INFO", log_file="/missing_path/test.log")

    try:
        logger.info("Info message", source="my_module")
    except Exception as e:
        raise AssertionError(
            f"Logger raised an exception with invalid parameters: {e}"
        ) from None

    captured = capsys.readouterr().out
    assert "Failed to open log file:" in captured

    logger.close()


def test_logger_does_not_emit_logs_below_threshold(tmp_path):
    """Test that messages below the current log level threshold are not written to the file."""
    log_file = tmp_path / "test.log"
    logger = Logger(level="ERROR", log_file=str(log_file))

    logger.debug("This debug message should not be logged")
    logger.info("This info message should not be logged")
    logger.warn("This warning message should not be logged")
    logger.error("This error message should be logged")
    logger.critical("This critical message should be logged")

    with open(log_file) as f:
        content = f.read()

    assert "This debug message should not be logged" not in content
    assert "This info message should not be logged" not in content
    assert "This warning message should not be logged" not in content
    assert "This error message should be logged" in content
    assert "This critical message should be logged" in content

    logger.close()


def test_logger_always_emits_logs(tmp_path):
    """Test that messages with level ALWAYS are emitted regardless of the current log level threshold."""
    log_file = tmp_path / "test.log"
    logger = Logger(level="ERROR", log_file=str(log_file))

    logger.always("This message should always be logged")

    with open(log_file) as f:
        content = f.read()

    assert "This message should always be logged" in content

    logger.close()


def test_logger_none_level(tmp_path):
    """Test that setting log level to NONE disables all logging."""
    log_file = tmp_path / "test.log"
    logger = Logger(level="NONE", log_file=str(log_file))

    logger.debug("This debug message should not be logged")
    logger.info("This info message should not be logged")
    logger.warn("This warning message should not be logged")
    logger.error("This error message should not be logged")
    logger.critical("This critical message should not be logged")
    logger.always("This message SHOULD be logged")

    with open(log_file) as f:
        content = f.read()

    assert (
        "[ALWAYS  ] [test_logger_to_file ] This message SHOULD be logged"
        in content
    )
    assert "This debug message should not be logged" not in content
    assert "This info message should not be logged" not in content
    assert "This warning message should not be logged" not in content
    assert "This error message should not be logged" not in content
    assert "This critical message should not be logged" not in content

    logger.close()
