import os
import sys

# Add device/lib to sys.path so we can import logger
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../device/lib"))
)

from logger import Logger


def test_logger_explicit_source(capsys):
    """Test that all public logging methods respect an explicitly provided source."""
    logger = Logger("dummy_port")

    logger.debug("Debug message", source="custom_debug")
    captured = capsys.readouterr().out
    assert "[DEBUG] [custom_debug] Debug message\n" in captured

    logger.info("Info message", source="custom_info")
    captured = capsys.readouterr().out
    assert "[INFO] [custom_info] Info message\n" in captured

    logger.warn("Warning message", source="custom_warn")
    captured = capsys.readouterr().out
    assert "[WARN] [custom_warn] Warning message\n" in captured

    logger.error("Error message", source="custom_error")
    captured = capsys.readouterr().out
    assert "[ERROR] [custom_error] Error message\n" in captured

    logger.critical("Critical message", source="custom_critical")
    captured = capsys.readouterr().out
    assert "[CRITICAL] [custom_critical] Critical message\n" in captured


def test_logger_omitted_source_same_module(capsys):
    """Test that public logging methods use the calling module's name when source is omitted."""
    logger = Logger("dummy_port")

    # In this test, the calling module's name is the current module's __name__
    expected_module = __name__

    logger.debug("Debug message")
    captured = capsys.readouterr().out
    assert f"[DEBUG] [{expected_module}] Debug message\n" in captured

    logger.info("Info message")
    captured = capsys.readouterr().out
    assert f"[INFO] [{expected_module}] Info message\n" in captured

    logger.warn("Warning message")
    captured = capsys.readouterr().out
    assert f"[WARN] [{expected_module}] Warning message\n" in captured

    logger.error("Error message")
    captured = capsys.readouterr().out
    assert f"[ERROR] [{expected_module}] Error message\n" in captured

    logger.critical("Critical message")
    captured = capsys.readouterr().out
    assert f"[CRITICAL] [{expected_module}] Critical message\n" in captured


def test_logger_omitted_source_different_module(capsys):
    """Test that public logging methods resolve module name correctly when called from another module."""
    logger = Logger("dummy_port")

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
    captured = capsys.readouterr().out
    assert (
        "[DEBUG] [mock_external_module] Debug message from different module\n"
        in captured
    )

    namespace["log_info"]()
    captured = capsys.readouterr().out
    assert (
        "[INFO] [mock_external_module] Info message from different module\n"
        in captured
    )

    namespace["log_warn"]()
    captured = capsys.readouterr().out
    assert (
        "[WARN] [mock_external_module] Warning message from different module\n"
        in captured
    )

    namespace["log_error"]()
    captured = capsys.readouterr().out
    assert (
        "[ERROR] [mock_external_module] Error message from different module\n"
        in captured
    )

    namespace["log_critical"]()
    captured = capsys.readouterr().out
    assert (
        "[CRITICAL] [mock_external_module] Critical message from different module\n"
        in captured
    )


def test_logger_omitted_source_main_module(capsys):
    """Test that if the calling module name is '__main__', we fall back to the calling module's filename basename."""
    logger = Logger("dummy_port")

    namespace = {"logger": logger}
    code = compile(
        "def log_info():\n    logger.info('Message from main')\n",
        "/home/simon/Documents/_ELECTRONICS/otampy/device/mock_temp_script.py",
        "exec",
    )
    exec(code, namespace)
    namespace["__name__"] = "__main__"

    namespace["log_info"]()
    captured = capsys.readouterr().out
    assert "[INFO] [mock_temp_script.py] Message from main\n" in captured
