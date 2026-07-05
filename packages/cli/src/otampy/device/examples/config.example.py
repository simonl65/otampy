"""
RENAME THIS FILE TO config.py AND EDIT THE VALUES BELOW TO MATCH YOUR ENVIRONMENT
"""

# Used by the examples when optional log-to-file support is installed.
LOG_LEVEL = "DEBUG"  # NONE, DEBUG, INFO, WARNING, ERROR, CRITICAL, ALWAYS
LOG_FILE = "/ota.log"

OTA_PORT = 1
OTA_TX_PIN = 4
OTA_RX_PIN = 5
OTA_BAUDRATE = 57600  # 115200 is unreliable wirth old XBee-Pro's
OTA_TIMEOUT_MS = 5000

# =============================================================================
# BEST PRACTICE: DO NOT EDIT BELOW THIS LINE UNLESS YOU KNOW WHAT YOU ARE DOING
# =============================================================================
UPDATE_REQUEST_FLAG_FILE = "update_requested.flag"
