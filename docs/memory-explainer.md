# MEM Command Output Explainer

## Command and Output

Running `otampy mem` will give something similar to:

```
Memory Information:

Memory (heap, post-GC):
  Free:      63.3% (127.1 KB / 200.6 KB)

Flash (Storage):
  Free:      75.9% (644.0 KB / 848.0 KB)
```

## Explainer

### Memory (heap, post-GC) — Python runtime memory

| Metric          | Meaning                                                            |
| --------------- | ------------------------------------------------------------------ |
| Free: 127.1 KB  | Heap memory currently available for Python objects                 |
| / 200.6 KB      | Total MicroPython heap reserved by this firmware, not physical RAM |
| (63.3%)         | Percentage of that heap which is free after garbage collection     |

**The key number: 127.1 KB is available now.** The command runs garbage collection immediately before sampling, so this is a comparable post-GC heap baseline. It does not include all physical RAM: MicroPython and the device reserve RAM for stacks, runtime state, drivers, and buffers.

### Flash (Storage) — Non-volatile storage

| Metric         | Meaning                                                          |
| -------------- | ---------------------------------------------------------------- |
| Free: 644.0 KB | Storage space available for uploading new files/code             |
| / 848.0 KB     | Total filesystem capacity available after firmware reservations  |
| (75.9%)        | Percentage of that filesystem capacity which is free             |

**The key number: 644.0 KB is available for new files.** Flash is persistent—files survive a reboot. Once it's full, you can't upload more code until you delete something.

### Bottom line:

- **Heap:** You have 127.1 KB available for Python objects after garbage collection.
- **Flash:** You have 644.0 KB of storage space. Also good headroom.

Both look healthy for a Pico! The device has plenty of room to grow.
