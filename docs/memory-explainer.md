# MEM Command Output Explainer

## Command and Output

Running `otampy mem` will give something similar to:

```
Memory Information:

RAM (Random Access Memory):
  Free:      127.1 KB  / 200.6 KB (63.3%)
  Allocated: 73.6 KB   (36.7%)

Flash (Storage):
  Free:      644.0 KB  / 848.0 KB (75.9%)
  Used:      204.0 KB  (24.1%)
```

## Explainer

### RAM (Random Access Memory) — Runtime memory

| Metric             | Meaning                                                     |
| ------------------ | ----------------------------------------------------------- |
| Free: 127.1 KB     | Memory currently available for the program to use right now |
| / 200.6 KB         | Total RAM capacity on the device                            |
| (63.3%)            | Percentage of total RAM that is free                        |
| Allocated: 73.6 KB | Memory currently in use by your running program             |
| (36.7%)            | Percentage of total RAM that is allocated                   |

**The key number: 127.1 KB is available now.** RAM is volatile—it's used for variables, objects, and runtime state. If you run out of RAM, your device will crash or behave unpredictably. On a Pico, you generally want to keep at least 50-100 KB free.

### Flash (Storage) — Non-volatile storage

| Metric         | Meaning                                                                |
| -------------- | ---------------------------------------------------------------------- |
| Free: 644.0 KB | Storage space available for uploading new files/code                   |
| / 848.0 KB     | Total Flash capacity on the device                                     |
| (75.9%)        | Percentage of total flash that is free                                 |
| Used: 204.0 KB | Storage consumed by existing files (boot.py, main.py, libraries, etc.) |
| (24.1%)        | Percentage of total flash that is used                                 |

**The key number: 644.0 KB is available for new files.** Flash is persistent—files survive a reboot. Once it's full, you can't upload more code until you delete something.

### Bottom line:

- **RAM:** You have 127.1 KB of working memory. Good headroom.
- **Flash:** You have 644.0 KB of storage space. Also good headroom.

Both look healthy for a Pico! The device has plenty of room to grow.
