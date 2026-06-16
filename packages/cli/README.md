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
| **bl** | None | Reboots device into its bootloader mode |
| **rb** | None | Hard reboots the device |
| **sr** | None | Soft resets the device |
| **ls** | [path] | Lists content of current (or specified) folder on device |
| **cat** | file | Shows content of specified file on device |
| **rm** | file | Remove specified file from device (may be wildarded) |
| **upd** | [src]<sup>1</sup> dest [,&nbsp;[src]&nbsp;dest] | Updates application firmware on device<sup>2</sup> |

**TODO:** Add other commands

**Additionally**: `-h` and `--help` will show helpful information about OTAmpy and its commands, etc

**<sup>1</sup>** Update source is optional and will be the current folder if not supplied.

**<sup>2</sup>** Updates take place after the device has rebooted and the update process is handled by `boot.py`.


## Examples

List root content
```bash
otampy ls
```

List content of /lib
```bash
otampy ls /lib
```

Update all application firmware
```bash
otampy update
```

Update specific application firmware<sup>**</sup>
```bash
otampy update . main.py # Only main.py (from current folder)
otampy update . main.py lib/lib2.py # Only main.py and lib/*.py
otampy update . /lib/myfolder # Everything from `/lib/myfolder`
otampy update . *.py # All python files from current folder
```

**TODO:** Add example code


## License
This code is released under the [Sustainable Use License](/LICENSE.md)

### TL;DR ( _NOT forming part of the license_ )

In essence the license is prohibits you from making profit from this code if I haven't given you a specific license to do so. If I give you such a separate license then I'm happy for us both to profit off this code.
