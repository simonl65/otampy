# Used when optional --with-logger support is installed.
LOG_LEVEL = "ERROR"  # NONE, DEBUG, INFO, WARNING, ERROR, CRITICAL, ALWAYS
LOG_FILE = "/ota.log"

OTA_PORT = 1
OTA_TX_PIN = 4
OTA_RX_PIN = 5
OTA_BAUDRATE = 57600  # 115200 is unreliable with old XBee-Pro's
# Abort an interrupted boot-time update after this period without a packet.
OTA_TIMEOUT_MS = 5000

# =============================================================================
#       DO NOT EDIT BELOW THIS LINE UNLESS YOU KNOW WHAT YOU ARE DOING
# =============================================================================
UPDATE_REQUEST_FLAG_FILE = "update_requested.flag"
