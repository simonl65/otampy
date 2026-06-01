"""
@file Logger.py
@brief Centralized logging utility for the MicroPython Differential-Drive Robot.

This module provides a robust logging mechanism with configurable levels,
timestamping, and consistent message formatting. It adheres to NASA P10
safety guidelines by offering clear error reporting and critical event
notification, essential for debugging and monitoring safety-critical systems.
"""

import os
import sys

# Log Levels
# These constants define the severity levels for log messages.
# Higher values indicate higher severity.
DEBUG = 0  # Detailed information for debugging purposes.
INFO = 1  # General information about the application's progress.
WARN = 2  # Indicates potential issues that are not errors but should be noted.
ERROR = 3  # Signifies an error event that might affect functionality.
CRITICAL = (
    4  # Denotes a severe error that could lead to system failure or halt.
)
ALWAYS = 98  # Messages that are always logged, regardless of the set log level.
NONE = 99  # Disables logging.


class Logger:
    """
    @brief A singleton logging utility for the MicroPython robot project.

    This class provides methods for logging messages at different severity levels.
    It ensures that log messages are formatted consistently with timestamps and
    level indicators, and supports filtering based on a configurable log level.
    """

    _instance = None
    _current_log_level = DEBUG  # Default log level upon initialization
    _log_file = None
    _log_file_path = None

    def __new__(cls, *args, **kwargs):
        """
        @brief Implements the singleton pattern for the Logger class.

        Ensures that only one instance of the Logger exists throughout the application.
        This is crucial for a centralized logging system.

        @return Logger: The single instance of the Logger class.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, level=None, log_file=None):
        """
        @brief Initializes the Logger.

        @param level (int or str): The desired logging level.
        @param log_file (str): Optional path to a file for log output.
        """
        if level is not None:
            self.set_log_level(level)

        if log_file:
            self.set_log_file(log_file)

    def set_log_level(self, level: int) -> None:
        """
        @brief Sets the current logging level.

        @param level (int): The desired logging level.
        """
        if isinstance(level, str):
            level_map = {
                "DEBUG": DEBUG,
                "INFO": INFO,
                "WARN": WARN,
                "ERROR": ERROR,
                "CRITICAL": CRITICAL,
                "ALWAYS": ALWAYS,
                "NONE": NONE,
            }
            level_int = level_map.get(level.upper())
            if level_int is not None:
                self._current_log_level = level_int
            else:
                self._log(ERROR, "Invalid log level string provided to Logger.")
        elif level in [DEBUG, INFO, WARN, ERROR, CRITICAL, ALWAYS, NONE]:
            self._current_log_level = level
        else:
            self._log(ERROR, "Invalid log level set.")

    def set_log_file(self, file_path: str):
        """
        @brief Sets the output file for the logger.

        @param file_path (str): The path to the log file.
        """
        if self._log_file and not self._log_file.closed:
            self._log_file.close()
        try:
            self._log_file = open(file_path, "a")  # noqa: SIM115
            self._log_file_path = file_path
        except IOError as e:  # noqa: UP024
            self._log_file = None
            self._log_file_path = None
            self.error(f"Failed to open log file: {e}")

    def close(self):
        """
        @brief Closes the log file if it is open.
        """
        if self._log_file and not self._log_file.closed:
            self._log_file.close()
            self._log_file = None
        self._log_file_path = None

    def _get_caller_name(self) -> str:
        """
        @brief Resolves the calling module or file name.
        """
        try:
            # Walk up the stack frames starting from the immediate caller's frame (index 1).
            frame = sys._getframe(1)
            while frame:
                globals_dict = frame.f_globals
                module_name = globals_dict.get("__name__", "")
                # We want the first frame that is not the Logger's module.
                if module_name != __name__:
                    if module_name == "__main__":
                        # Fallback to the filename basename of the calling frame
                        filename = frame.f_code.co_filename
                        return os.path.basename(filename)
                    return module_name
                frame = frame.f_back
        except Exception:
            pass
        return "unknown"

    def _format_message(self, level: int, message: str, source: str) -> str:
        """
        @brief Formats a log message with level and source information.

        @param level (int): The severity level of the message.
        @param message (str): The raw log message.
        @param source (str): The source of the message.

        @return str: The formatted log message string.
        """
        level_str = {
            DEBUG: "DEBUG   ",
            INFO: "INFO    ",
            WARN: "WARN    ",
            ERROR: "ERROR   ",
            CRITICAL: "CRITICAL",
            ALWAYS: "ALWAYS  ",
            NONE: "DISABLED",
        }.get(level, "INFO    ")

        # if source string is less than 20 characters, pad it to 20 characters for alignment
        if len(source) < 20:
            source = source.ljust(20)

        return f"[{level_str}] [{source}] {message}"

    def _log(self, level: int, message: str, source: str = None) -> None:
        """
        @brief Internal method to handle logging logic.

        @param level (int): The severity level of the message.
        @param message (str): The raw log message.
        @param source (str): The optional source of the log message.
        """
        if level == ALWAYS or level >= self._current_log_level:
            if source is None:
                source = self._get_caller_name()
            formatted_message = self._format_message(level, message, source)
            if self._log_file:
                self._log_file.write(formatted_message + "\n")
                self._log_file.flush()

            # Also print to stdout
            print(formatted_message, file=sys.stdout)

    def debug(self, message: str, source: str = None) -> None:
        self._log(DEBUG, message, source=source)

    def info(self, message: str, source: str = None) -> None:
        self._log(INFO, message, source=source)

    def warn(self, message: str, source: str = None) -> None:
        self._log(WARN, message, source=source)

    def error(self, message: str, source: str = None) -> None:
        self._log(ERROR, message, source=source)

    def critical(self, message: str, source: str = None) -> None:
        self._log(CRITICAL, message, source=source)

    def always(self, message: str, source: str = None) -> None:
        self._log(ALWAYS, message, source=source)

    def none(self) -> None:
        self.set_log_level(NONE)

    def delete_log_file(self, file_path: str) -> None:
        """
        @brief Closes the log file if it matches the active log file, then deletes it.

        @param file_path (str): The path to the log file to delete.
        """
        # If the file path is the active log file, close it first
        if hasattr(self, "_log_file_path") and self._log_file_path == file_path:
            self.close()

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError as e:
            self.error(f"Failed to delete log file {file_path}: {e}")


# Global logger instance
logger = Logger()
