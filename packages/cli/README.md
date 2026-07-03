# OTAmpy - CLI

This provides a command-line interface to enable over the air (OTA) file management for MicroPython devices when using wireless, such as XBee modules. It makes use of the Universal Reliable Serial Transport (URST) protocol.

## Usage

```bash
otampy [global-options] command [command-options]
```

### Global options

| Option | Effect |
| --- | --- |
| `-p`, `--port` | Select the OTA UART adapter. |
| `-b`, `--baud` | Set the OTA UART baud rate. |
| `--log-level` | Set host CLI logging to `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |

The default host log level is `ERROR`. Supplying an explicit level prompts for
its scope:

```bash
otampy --log-level DEBUG --port /dev/ttyUSB0 ping
```

- `p` stores it permanently;
- `s` keeps it for commands launched from the current shell session;
- `c` applies it only to the current command.

The `OTAMPY_LOG_LEVEL` environment variable overrides saved settings.
Host CLI logging is independent of the optional device file logger installed
by `otampy deploy --with-logger`.

### Saved settings

Permanent port and log-level settings are stored together in
`~/.config/otampy/config.json`:

```json
{
  "default_port": "/dev/ttyUSB0",
  "log_level": "DEBUG"
}
```

Session-only selections use shell-specific files in the operating system's
temporary directory (normally `/tmp` on Linux) and do not alter the permanent
configuration. `OTAMPY_PORT` and `OTAMPY_LOG_LEVEL` override saved settings.

### Commands

| Command    | Args                                            | Description                                                                                      |
| ---------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| **ping**   | None                                            | Connection health check with the MicroPython device                                              |
| **rb**     | None                                            | Hard reboots the device (requires confirmation)                                                  |
| **sr**     | None                                            | Soft resets the device (requires confirmation)                                                   |
| **ls**     | [path]                                          | Lists content of current (or specified) folder on device (folder paths show with a trailing `/`) |
| **cat**    | file                                            | Shows content of specified file on device                                                        |
| **cp**     | source[:destination] [...]                      | Copies files or folders without rebooting the device                                             |
| **rm**     | path [...]                                      | Remove non-recovery files or directories (requires confirmation)                                 |
| **mem**    | None                                            | Queries and displays RAM and Flash storage utilization of the device                             |
| **upd**    | [source[:destination] ...]                       | Updates application firmware on device<sup>2</sup>                                               |
| **ports**  | None                                            | Lists ports with devices and allows selection for subsequent commands                            |
| **deploy** | See deployment options below                    | Erase and deploy OTAmpy, examples, and device dependencies                                        |

With no sources, `upd` selects `main.py` and all Python files under `lib/` in
the current directory.

**<sup>2</sup>** Updates take place after the device has rebooted and the update process is handled by `boot.py`.

## Examples

If you've not already selected a port, all connection commands require specifying the target serial port (via `-p` or `--port`):

Select a port for subsequent commands:

```bash
otampy ports
```

The effective selected port is highlighted in green and marked with `*`.
This reflects a `--port` override, `OTAMPY_PORT`, a session selection, or the
permanently saved default. Each USB device also shows its serial number,
VID:PID, manufacturer, and product when reported by the operating system.

List root content of the device:

```bash
otampy --port /dev/ttyUSB0 ls
```

Show device memory and storage utilization:

```bash
otampy --port /dev/ttyUSB0 mem
```

Check device connection health:

```bash
otampy --port /dev/ttyUSB0 ping
```

Deploy the default silent source profile over the board's USB serial port:

```bash
otampy deploy --port /dev/ttyACM0
```

Deploy with development file logging:

```bash
otampy deploy --port /dev/ttyACM0 --with-logger
```

Deploy target-matched bytecode libraries:

```bash
uv tool install mpy-cross
otampy deploy --port /dev/ttyACM0 --bytecode
```

> [!WARNING]
> `deploy` erases the device filesystem before copying files.

Deployment options:

| Option | Effect |
| --- | --- |
| `-p`, `--port` | Select the USB/serial device used by `mpremote`. |
| `--with-logger` | Install the optional `log-to-file` package. |
| `--bytecode`, `--mpy` | Compile OTAmpy and URST into target-matched `.mpy` files. |
| `--mpy-cross` | Select the `mpy-cross` executable or command. |
| `--no-mip` | Install neither URST nor the optional logger. |
| `--no-reset` | Leave the board without a final reset. |
| `--dry-run` | Print the complete `mpremote` command without running it. |
| `--mpremote` | Use a specific `mpremote` executable. |

The standard profile installs URST only. See the
[deployment guide](../../docs/deployment.md) for prerequisites and the exact
files copied. Use `--no-mip` only when URST is frozen into the firmware or
will be installed separately. The bytecode profile packages the installed URST
dependency itself, skips MIP, and cannot be combined with `--with-logger`.

List content of `/lib`:

```bash
otampy --port /dev/ttyUSB0 ls /lib
```

Copy files without rebooting:

```bash
otampy --port /dev/ttyUSB0 cp settings.json:config/settings.json
otampy --port /dev/ttyUSB0 cp assets:assets/
otampy --port /dev/ttyUSB0 cp 'packages/device/lib/otampy/*:lib/otampy/'
```

`cp` accepts multiple sources, folders, and local `*`, `?`, `[]`, and `**`
patterns using the same `source:destination` mapping syntax as `upd`. Folder
contents include every file type recursively; empty folders are not created.
Files are streamed to checksum-verified staging files and committed
individually. The device keeps running throughout.

A reboot reminder is shown only when a copy targets root `/boot.py` or
`/main.py`, because the running interpreter will not use those replacements
until its next restart. Ordinary copies do not display the reminder.

Remove multiple files or directories:

```bash
otampy --port /dev/ttyUSB0 rm old.py config.old cache
```

Remote wildcards are expanded from device directory listings. Quote them to
prevent the host shell from expanding them locally:

```bash
otampy --port /dev/ttyUSB0 rm 'lib/otampy/*.py'
otampy --port /dev/ttyUSB0 rm 'logs/**'
```

Removing a non-empty directory requires an additional recursive-removal
confirmation.

To preserve remote recovery, `rm` cannot remove root `/boot.py`, `/main.py`,
`/config.py`, anything under `/lib/otampy` or `/lib/urst`, or an ancestor such
as `/lib` or `/`. This also applies to wildcard and recursive selections. The
CLI expands and validates the complete selection before deleting anything,
then sends no `RM` if any protected path is present. There is no force option;
replace protected files using staged `cp` or transactional `upd`.

Update all application firmware:

```bash
otampy --port /dev/ttyUSB0 upd
```

Update specific application firmware files:

```bash
otampy --port /dev/ttyUSB0 upd main.py config.py
otampy --port /dev/ttyUSB0 upd app:/
otampy --port /dev/ttyUSB0 upd packages/device/lib/otampy/boot.py:lib/otampy/boot.py packages/device/lib/otampy/core.py:lib/otampy/core.py
otampy --port /dev/ttyUSB0 upd 'packages/device/lib/otampy/*.py:lib/otampy/'
```

Directories include all Python files recursively. Local `*`, `?`, `[]`, and
`**` patterns are supported. A pattern matching multiple files must map to a
destination ending in `/`. If any explicit source or pattern has no matches,
the update stops before contacting the device instead of applying a partial
selection.

## License

This code is released under the [Sustainable Use License](/LICENSE.md)

### TL;DR ( _NOT forming part of the license_ )

In essence the license is prohibits you from making profit from this code if I haven't given you a specific license to do so. If I give you such a separate license then I'm happy for us both to profit off this code.
