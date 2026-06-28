"""
Shared protocol definitions for OTAmpy (commands and default config).

This module centralises protocol-level constants so both the device
and the CLI use the same definitions when communicating over serial.
"""

OTA_COMMANDS = [
    "PING",
    "CAT",
    "LS",
    "RM",
    "BL",
    "RB",
    "SR",
    "UPDATE_REQUEST",
]

# Shared default configuration for OTA components
DEFAULT_OTA_CONFIG = {
    "LOG_LEVEL": "DEBUG",
    "LOG_FILE": "/logs/ota.log",
    "UPDATE_REQUEST_FLAG_FILE": "update_requested.flag",
}
