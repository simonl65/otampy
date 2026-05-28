import logging

logger = logging.getLogger(__name__)

logger.debug("This is a debug message from OTAmpy main module.")


def main() -> None:
    print("Hello from OTAmpy CLI (main)!")


if __name__ == "__main__":
    main()
