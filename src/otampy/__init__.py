import logging

from .utils.logging_utils import logging_formatter

# Configure logging using the `name=` parameter.
# name="sendrec" : Shows only sendrec package logs (suppresses unrelated dependencies).
# name=None      : Shows all logs from all imported packages (including dependencies).
logging_formatter(name=None, level_width=5, name_width=20, level=logging.DEBUG)


# def main() -> None:
#     print("Hello from otampy CLI!")
