# Used when optional --with-logger support is installed.
LOG_LEVEL = "ERROR"  # NONE, DEBUG, INFO, WARNING, ERROR, CRITICAL, ALWAYS
LOG_FILE = "/ota.log"  # Path and filename of log file
LOG_MAX_BYTES = 10240  # Max bytes in a log file
LOG_BACKUP_COUNT = 1  # Max log backup files
LOG_USE_TICKS = False  # False = use time epoch, True = use ticks since boot

OTA_PORT = 1
OTA_TX_PIN = 4
OTA_RX_PIN = 5
OTA_BAUDRATE = 57600  # 115200 is unreliable with old XBee-Pro's
# Abort an interrupted boot-time update after this period without a packet.
OTA_TIMEOUT_MS = 5000
# Boots into an unconfirmed update candidate before the device auto-restores
# the previous version. `otampy upd` confirms automatically; see docs 2.4.
OTA_TRIAL_BOOTS = 3
# Milliseconds `boot.py` listens for a recovery command (`otampy upd --recover`
# / `otampy rollback --recover`) on a boot that followed a healthy application
# run. Added to each such boot, ~1 s at the default. `0` disables it.
OTA_BOOT_LISTEN_MS = 1000
# The window on a boot that followed one which never reached `ota.poll()`, or
# that still carries an unconfirmed candidate. A power-cycled XBee takes
# t+3.6-8.7 s to deliver its first frame, which the ~1 s window above opens and
# shuts long before -- so this is the tier that makes radio recovery actually
# work. Only a device that has already failed pays it. `0` disables the wide
# window and the boot marker below entirely. Keep this under your watchdog
# period if a custom `boot.py` arms one before `OTA(...).boot()`: 8000 is just
# under the RP2040's ~8388 ms cap. See docs/protocol.md 2.4.
OTA_BOOT_RECOVERY_LISTEN_MS = 8000
# Marker written once per boot and removed by the first `ota.poll()`. Its
# presence at boot is what says the previous boot never reached the
# application. Must be a dedicated scratch path.
OTA_BOOT_MARK_FILE = "otampy-boot.mark"

# --- Command authentication (optional; see docs/protocol.md 1.2) -------------
# Unset, the device accepts commands from anything that can reach the UART.
# On a radio link that means any station in range. Enable BOTH of these, and
# set OTAMPY_COMMAND_AUTH_KEY on the host FIRST -- a device that requires
# authentication will reject an unconfigured CLI, and recovery is over USB.
# OTA_REQUIRE_AUTH = True
# COMMAND_AUTH_KEY = ""  # 64 hex chars; same value as the host's key
# OTA_REPLAY_FLOOR_FILE = "otampy-replay-floor"

# Restrict which paths CP_START / CAT / RM may target. Unset allows any path
# except traversal ('..' is always refused). A device that only ever receives
# data files should say so here.
# OTA_ALLOWED_PATH_PREFIXES = ("data",)

# =============================================================================
#       DO NOT EDIT BELOW THIS LINE UNLESS YOU KNOW WHAT YOU ARE DOING
# =============================================================================
UPDATE_REQUEST_FLAG_FILE = "update_requested.flag"
# Retain-previous commit journal. Must be a dedicated scratch path -- a commit
# clobbers whatever this points at.
OTA_JOURNAL_FILE = "otampy-update.journal"
