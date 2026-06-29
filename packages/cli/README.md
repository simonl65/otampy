# OTAmpy - CLI
This provides a command-line interface to enable over the air (OTA) file management for MicroPython devices when using wireless, such as XBee modules. It makes use of the Universal Reliable Serial Transport (URST) protocol.


## Usage

```bash
otampy command [args]
```


### Commands

|Command|Args|Description|
|--|--|--|
| **h** | None | Shows helpful information about OTAmpy and its commands |
| **ping** | None | Connection health check with the MicroPython device |
| **bl** | None | Reboots device into its bootloader mode (requires confirmation) |
| **rb** | None | Hard reboots the device (requires confirmation) |
| **sr** | None | Soft resets the device (requires confirmation) |
| **ls** | [path] | Lists content of current (or specified) folder on device (folder paths show with a trailing `/`) |
| **cat** | file | Shows content of specified file on device |
| **rm** | file | Remove specified file from device (requires confirmation) |
| **mem** | None | Queries and displays RAM and Flash storage utilization of the device |
| **upd** | [src]<sup>1</sup> dest [,&nbsp;[src]&nbsp;dest] | Updates application firmware on device<sup>2</sup> |
| **deploy** | None | Deploy OTAmpy lib/, boot.py, and main.py to a MicroPython device |

**<sup>1</sup>** Update source is optional and will be the current folder if not supplied.

**<sup>2</sup>** Updates take place after the device has rebooted and the update process is handled by `boot.py`.


## Examples

All connection commands require specifying the target serial port (via `-p` or `--port`):

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

List content of `/lib`:
```bash
otampy --port /dev/ttyUSB0 ls /lib
```

Update all application firmware:
```bash
otampy --port /dev/ttyUSB0 upd
```

Update specific application firmware files:
```bash
otampy --port /dev/ttyUSB0 upd . main.py                  # Only main.py from current folder
otampy --port /dev/ttyUSB0 upd . main.py lib/sensor.py    # Only main.py and lib/sensor.py
otampy --port /dev/ttyUSB0 upd . /lib/myfolder            # Everything from /lib/myfolder
otampy --port /dev/ttyUSB0 upd . *.py                     # All python files in the current folder
```


## License
This code is released under the [Sustainable Use License](/LICENSE.md)

### TL;DR ( _NOT forming part of the license_ )

In essence the license is prohibits you from making profit from this code if I haven't given you a specific license to do so. If I give you such a separate license then I'm happy for us both to profit off this code.
