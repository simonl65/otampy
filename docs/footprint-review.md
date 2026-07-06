# Device footprint review

**Status:** Baseline measurement in progress

**Last updated:** 2026-07-02

**Scope:** `packages/device`, its deployed examples, and the device-side
dependencies installed by `otampy deploy`

## Executive summary

The reported device still has comfortable headline capacity: 122.9 KB
(61.2%) of heap and 652.0 KB (76.9%) of filesystem space are free. The more
important risks are avoidable steady-state RAM use and short-lived allocation
peaks during imports, directory/file commands, and updates.

The best opportunities, in order, are:

1. Measure live RAM, import cost, peak RAM, and actual deployed files
   reproducibly. The current `MEM` command does not collect garbage first, and
   the snapshot does not say which lifecycle point it represents.
2. Make the no-update boot path avoid importing and constructing URST, and
   avoid keeping both boot-only and runtime-only modules resident.
3. Stop copying a configuration module into a second dictionary.
4. Bound the transient memory used by `CAT`, `LS`, command parsing, URST
   fragmentation/reassembly, and update chunks without changing the wire
   protocol.
5. Produce a MicroPython-specific URST deployment and compare `.mpy` and
   frozen-module builds.

Native/Viper emitters are not proposed. They optimise execution speed, can
increase code size, and introduce portability or safety costs without
addressing the dominant footprint issues here.

## What the current numbers do and do not show

The supplied snapshot is:

| Resource          |   Allocated/used |     Free | Assessment                                                        |
| ----------------- | ---------------: | -------: | ----------------------------------------------------------------- |
| Python heap       |  77.8 KB (38.8%) | 122.9 KB | Healthy at the sampled instant, but no peak or fragmentation data |
| Device filesystem | 196.0 KB (23.1%) | 652.0 KB | Healthy, but not attributable to OTAmpy from this snapshot        |

`manager.py` samples `gc.mem_alloc()` directly. It does not run
`gc.collect()` first, so the 77.8 KB includes both live objects and any
uncollected garbage. A before/after-GC pair is needed before treating it as a
steady-state baseline.

### Initial device diagnostic

On 2026-06-30, the pre-refactor deployment was inspected on a Raspberry Pi
Pico W running MicroPython v1.28.0. After connecting to the already-running
application:

| Checkpoint           |     Allocated |          Free |
| -------------------- | ------------: | ------------: |
| Before explicit GC   | 150,864 bytes |  54,576 bytes |
| After `gc.collect()` |  31,200 bytes | 174,240 bytes |

Both `otampy.boot` and `otampy.manager` were present in `sys.modules`. The
119,664-byte post-GC reduction confirms that an uncollected `MEM` result is not
a reliable live-heap baseline. This was not a controlled cold boot, so it is
diagnostic evidence only and does not complete FP-01.

### Post-F1 device diagnostic

The lazy-import facade was deployed to the same board and verified by SHA-256.
The boot-only checkpoint and two normal-lifecycle runs produced:

| Lifecycle                          | Allocated after GC | Free after GC | `boot` loaded | `manager` loaded |
| ---------------------------------- | -----------------: | ------------: | ------------- | ---------------- |
| Boot only                          |       25,440 bytes | 180,000 bytes | Yes           | No               |
| Normal boot-to-main, run 1         |       29,952 bytes | 175,488 bytes | Yes           | Yes              |
| Normal boot-to-main, run 2         |       29,952 bytes | 175,488 bytes | Yes           | Yes              |
| Boot only, after release           |       22,064 bytes | 183,376 bytes | No            | No               |
| Normal boot-to-main, after release |       26,400 bytes | 179,040 bytes | No            | Yes              |

The isolated mode behaviour and explicit boot-module release work on the
target. Releasing `boot` recovered 3,376 bytes in the boot-only checkpoint and
3,552 bytes in the normal lifecycle compared with the lazy-import-only
deployment. The normal application retains only the runtime `manager` module.

### FP-01 RAM checkpoint baseline

On 2026-07-01, `packages/device/tools/footprint_boot.py` was temporarily
installed as `/boot.py` on the same Pico W running MicroPython v1.28.0. The
production boot file was backed up, restored byte-for-byte, and verified with
SHA-256 `befeba4209e37170699a9dbdc3470fa32bfbaee8413d7a83f7e4dceb83ffd4f3`.
OTA operation was verified with `PONG` after restoration.

The probe is excluded from normal deployment. Its fixed result buffer and
bytecode are therefore included in every probe checkpoint; compare future
results using the same probe and firmware rather than treating `clean_boot` as
the production application's absolute floor.

| Checkpoint                      | Before GC allocated | Before GC free | After GC allocated | After GC free | Post-GC delta |
| ------------------------------- | ------------------: | -------------: | -----------------: | ------------: | ------------: |
| `clean_boot`                    |               8,704 |        196,736 |              6,448 |       198,992 |      baseline |
| `import_otampy`                 |              40,432 |        165,008 |             19,216 |       186,224 |       +12,768 |
| `ota_inputs_ready`              |              26,608 |        178,832 |             22,416 |       183,024 |        +3,200 |
| `ota_constructed`               |              23,008 |        182,432 |             22,816 |       182,624 |          +400 |
| `no_flag_boot`                  |              23,376 |        182,064 |             23,376 |       182,064 |          +560 |
| `first_poll`                    |              27,600 |        177,840 |             25,440 |       180,000 |        +2,064 |
| `idle_poll`                     |              25,488 |        179,952 |             25,440 |       180,000 |             0 |
| `LS /`                          |              63,760 |        141,680 |             25,792 |       179,648 |     operation |
| `CAT ota-config.py` (491 bytes) |              64,992 |        140,448 |             25,808 |       179,632 |     operation |

The deltas are between adjacent post-GC boot-probe checkpoints. `LS` and `CAT`
were measured independently after a normal reset, successful command, and
immediate USB-REPL capture. They expose substantial collectible allocation but
do not measure the in-operation peak; FP-03 owns peak stress testing.

After result printing, `micropython.mem_info(1)` reported:

- stack use: 820 of 7,936 bytes;
- GC heap: 205,440 total, 27,312 used, 178,128 free;
- 314 one-block allocations and 66 two-block allocations;
- largest allocated run: 68 blocks;
- largest free run: 9,917 blocks.

`packages/device/tools/footprint_update.py` then ran a controlled five-byte
update. It intercepted the updater reset, measured from inside transport
acknowledgements, and removed its flag, target, and staging files:

| Update checkpoint | Before GC allocated | Before GC free | After GC allocated | After GC free | Post-GC delta |
| ----------------- | ------------------: | -------------: | -----------------: | ------------: | ------------: |
| `flagged_boot`    |              62,784 |        142,656 |             31,120 |       174,320 |      baseline |
| `update_chunk`    |              33,616 |        171,824 |             33,072 |       172,368 |        +1,952 |
| `update_commit`   |              33,552 |        171,888 |             33,264 |       172,176 |          +192 |

The three probe paths were verified absent afterward, the board was reset, and
normal OTA operation was verified with `PONG`.

### FP-02 filesystem inventory

On 2026-07-01, `packages/device/tools/footprint_fs.py` inventoried the running
device without modifying it. The filesystem geometry was:

| Property              |                   Value |
| --------------------- | ----------------------: |
| Block/fragment size   |             4,096 bytes |
| Total blocks          |                     212 |
| Free/available blocks |                     161 |
| Used blocks           |                      51 |
| Total                 | 868,352 bytes (848 KiB) |
| Current used          | 208,896 bytes (204 KiB) |
| Current free          | 659,456 bytes (644 KiB) |

Every deployed file was captured:

| File                               | Logical bytes | Minimum rounded bytes |
| ---------------------------------- | ------------: | --------------------: |
| `/boot.py`                         |           688 |                 4,096 |
| `/ota-config.py`                   |           491 |                 4,096 |
| `/main.py`                         |         2,568 |                 4,096 |
| `/lib/Blink.py`                    |           346 |                 4,096 |
| `/lib/log_to_file/__init__.py`     |         5,018 |                 8,192 |
| `/lib/otampy/__init__.py`          |           190 |                 4,096 |
| `/lib/otampy/boot.py`              |         8,244 |                12,288 |
| `/lib/otampy/core.py`              |         1,308 |                 4,096 |
| `/lib/otampy/logger.py`            |         2,319 |                 4,096 |
| `/lib/otampy/manager.py`           |         4,204 |                 8,192 |
| `/lib/otampy/ota.py`               |         1,584 |                 4,096 |
| `/lib/shared/performance_timer.py` |           966 |                 4,096 |
| `/lib/shared/protocol.py`          |           513 |                 4,096 |
| `/lib/urst/__init__.py`            |           671 |                 4,096 |
| `/lib/urst/codec_layer.py`         |         4,705 |                 8,192 |
| `/lib/urst/constants.py`           |         1,106 |                 4,096 |
| `/lib/urst/core_handler.py`        |         4,393 |                 8,192 |
| `/lib/urst/protocol_layer.py`      |         9,104 |                12,288 |
| `/lib/urst/transport_layer.py`     |           223 |                 4,096 |
| `/logs/ota.log`                    |         4,957 |                 8,192 |

The six directories were `/lib`, `/lib/log_to_file`, `/lib/otampy`,
`/lib/shared`, `/lib/urst`, and `/logs`. No update flag or `.ota` staging file
was present.

| Content group                                  | Logical bytes | Rounded file bytes |
| ---------------------------------------------- | ------------: | -----------------: |
| Root application/config                        |         3,747 |             12,288 |
| `Blink.py`                                     |           346 |              4,096 |
| MIP `log_to_file`                              |         5,018 |              8,192 |
| OTAmpy                                         |        17,849 |             36,864 |
| MIP shared helpers                             |         1,479 |              8,192 |
| MIP URST                                       |        20,202 |             40,960 |
| Generated OTA log                              |         4,957 |              8,192 |
| **Current total**                              |    **53,598** |        **118,784** |
| **Clean-deploy files (without generated log)** |    **48,641** |        **110,592** |

The current filesystem is exactly 8,192 bytes above the originally reported
196 KiB use, matching the two blocks occupied by the generated log. Removing
that generated allocation mathematically reconciles the original clean
baseline:

- 49 used blocks = 200,704 bytes (196 KiB);
- clean deployed files require at least 27 blocks = 110,592 bytes;
- the remaining 22 blocks = 90,112 bytes are directory, filesystem metadata,
  and LittleFS allocation overhead.

Consequently the clean deployment occupies about 4.13 times its 48,641 bytes
of logical content. Module/file consolidation may therefore save whole 4 KiB
blocks even when it removes relatively little source text.

The flash figure comes from `statvfs("/")`. It includes every deployed
application/dependency/log/staging file plus filesystem metadata and block
rounding. It is not the size of `packages/device` alone.

### FP-03 peak-memory stress matrix

On 2026-07-01, `packages/device/tools/footprint_stress.py` ran on the same
Pico W and MicroPython v1.28.0 firmware as the other baseline probes. It
samples `gc.mem_free()` from inside transport `read()` and `send()`, including
the point where the complete response and production temporaries are still
live on the caller's stack. This is a repeatable protocol-boundary minimum,
not a VM allocator trace; future comparisons must use the same harness.

| Scenario                           | Free before | Minimum free | Peak consumed | Free after cleanup | Result |
| ---------------------------------- | ----------: | -----------: | ------------: | -----------------: | ------ |
| `CAT`, valid 16 KiB file           |     162,704 |      111,440 |        51,264 |            162,704 | PASS   |
| `LS`, directory with 64 files      |     162,704 |      139,040 |        23,664 |            162,704 | PASS   |
| Update, maximum 256-byte chunk     |     161,808 |      157,856 |         3,952 |            161,808 | PASS   |
| Update, 32-file manifest           |     161,616 |       68,672 |        92,944 |            161,616 | PASS   |
| Update, failed checksum            |     161,312 |      158,080 |         3,232 |            161,312 | PASS   |
| Interrupted update after one chunk |     161,008 |      158,032 |         2,976 |            161,008 | PASS   |

The functional assertions verify the `CAT` response size, prefix, and content;
all 64 unique `LS` entries; update acknowledgements and committed content;
checksum rejection and staging-file removal; and that interruption leaves an
uncommitted staging file without creating its target. The many-file transport
generates packets on demand so the probe does not retain an artificial packet
queue in the measured heap.

All three approved fixture roots (`/fp-stress-cat.txt`,
`/fp-stress-dir`, and `/fp-stress-update`) were verified absent after the run.
Each scenario returned exactly to its own pre-run free-heap value after
cleanup and collection. The board was reset and responded over its USB REPL;
the separate OTA UART adapter was not present for a `PONG` check.

### FP-04 lazy transport measurement

On 2026-07-01, commit `755b90e` changed `OTACore.transport` to import and
construct URST on first access. Configuration, logger, UART validation, and
the public `core.transport` interface are unchanged. Runtime polling and a
flagged boot still create one cached transport; a no-flag boot never creates
one.

The FP-01 cold-boot probe was rerun on the same Pico W and MicroPython v1.28.0
firmware. Values below are allocated bytes immediately after `gc.collect()`:

| Checkpoint         | Before FP-04 | After FP-04 |     Change |
| ------------------ | -----------: | ----------: | ---------: |
| `clean_boot`       |        6,448 |       6,448 |          0 |
| `import_otampy`    |       19,216 |      10,160 |     -9,056 |
| `ota_inputs_ready` |       22,416 |      13,392 |     -9,024 |
| `ota_constructed`  |       22,816 |      13,552 |     -9,264 |
| `no_flag_boot`     |       23,376 |      15,072 | **-8,304** |
| `first_poll`       |       25,440 |      25,616 |       +176 |
| `idle_poll`        |       25,440 |      25,616 |       +176 |

The identical clean checkpoint confirms a comparable run. The no-update path
recovers 8,304 bytes, while first polling pays the deferred import and returns
to effectively the previous application heap. The 176-byte runtime increase
is the cached property state and accessor bytecode cost; it is deliberately
paid only by code that actually uses the transport.

The probe exercised no-flag boot followed by first and idle polling. Its
production `/boot.py` was then restored and verified against SHA-256
`befeba4209e37170699a9dbdc3470fa32bfbaee8413d7a83f7e4dceb83ffd4f3`.
The deployed `core.py` matched the committed source SHA-256
`a4b5674401780389ba3041c70de6df86f6858fe823455339fe6ff8c78a760964`,
and the board was reset and verified responsive over USB.

### FP-06 configuration measurement

On 2026-07-01, commits `43810bd` and `df5ebef` removed module configuration
copying. `OTACore.config` now retains the caller's mapping or module directly;
one small accessor reads mappings with `.get()` and modules with `getattr()`.
Empty mappings still receive the same defaults, and custom mappings/settings
remain intact.

An initial mapping-adapter class was rejected after target measurement: its
class, methods, and instance cost 320–384 bytes more than the copied
dictionary. The final function-based design was then measured with the same
FP-01 probe:

| Checkpoint         | After FP-04 | After FP-06 |   Change |
| ------------------ | ----------: | ----------: | -------: |
| `clean_boot`       |       6,448 |       6,448 |        0 |
| `import_otampy`    |      10,160 |      10,128 |      -32 |
| `ota_inputs_ready` |      13,392 |      13,456 |      +64 |
| `ota_constructed`  |      13,552 |      13,536 |      -16 |
| `no_flag_boot`     |      15,072 |      14,912 | **-160** |
| `first_poll`       |      25,616 |      25,408 | **-208** |
| `idle_poll`        |      25,616 |      25,408 | **-208** |

The `ota_inputs_ready` checkpoint precedes `OTACore` construction, so its
64-byte movement is allocator/layout variation rather than retained
configuration state. The lifecycle checkpoints where configuration is live
show a small but real reduction. This confirms that a dedicated adapter would
be over-engineering on this MicroPython build.

The probe exercised the deployed module-style `ota-config.py` through no-flag boot
and runtime polling. Production `/boot.py` was restored to its established
SHA-256, all three changed modules matched their committed checksums, and the
board was reset and verified responsive over USB.

### FP-07 bounded CAT and LS responses

On 2026-07-01, commits `d262479`, `64e2393`, and `633d42f` changed large
`CAT` and `LS` responses to feed URST's reliable protocol in bounded 194-byte
logical fragments. The wire-level message remains one `CAT_OK:` or `LS_OK:`
payload: existing URST receivers reassemble the same bytes as before.

`CAT` now reads a binary file one fragment at a time. `LS` uses `ilistdir`
where available, walks the directory once to determine the fragment count,
and walks it again to emit names and separators without building a second
entry list or joined string. Responses above URST's one-byte fragment-count
limit return `ERROR:Response too large` instead of failing while constructing
an invalid header.

MicroPython does not reclaim unreachable temporary frame objects immediately.
The first target run therefore showed that structural streaming alone still
accumulated garbage. Collection now occurs after each acknowledged fragment
and periodically during directory walks, safe points where no frame is in
flight. A fresh-interpreter rerun of the FP-03 matrix measured:

| Scenario                      | FP-03 peak | FP-07 peak |          Reduction | FP-07 minimum free | Result |
| ----------------------------- | ---------: | ---------: | -----------------: | -----------------: | ------ |
| `CAT`, valid 16 KiB file      |     51,264 |      4,416 | **46,848 (91.4%)** |            157,248 | PASS   |
| `LS`, directory with 64 files |     23,664 |      2,800 | **20,864 (88.2%)** |            158,864 | PASS   |

The other four stress cases retained their expected results, including the
92,944-byte many-file update peak. Host regressions reassemble every emitted
fragment and prove exact logical payloads for both large cases; existing
ordinary-response tests remain byte-for-byte unchanged.

The physical OTA UART round trip was completed later on 2026-07-01. CLI
`PING` returned `PONG`; fragmented `CAT ota-config.py` reassembled 491 bytes with
SHA-256 `5acd4e06427a59b9afcd97655915fda057558525096de4e98ce24f3dca4930cf`,
exactly matching the file on the Pico; and fragmented `LS /fp-stress-dir`
reassembled a 255-byte payload containing exactly 64 expected filenames. The
temporary directory was removed and verified absent, the board was reset, and
a final physical CLI `PING` returned `PONG`.

The deployed `manager.py` matched SHA-256
`e2b63d6c5cff64ff4758982ea21e0b79a025df4b0aab20e03fc1c548f7283b4c`.
Its source grew from 4,244 to 7,501 bytes but remained inside the same 8 KiB
filesystem allocation, with device free space unchanged at 651,264 bytes.
All stress fixtures were absent afterward; the board was reset and verified
responsive over USB.

### FP-08 compact update parsing and state

On 2026-07-01, commit `792a349` changed the update loop to retain protocol
packets as bytes. Command splits are bounded, base64 is decoded directly from
bytes, chunk acknowledgements concatenate the byte sequence number, and only
filesystem paths are decoded. The free-space check now uses integer
arithmetic.

The string-keyed session dictionary was replaced with fixed locals. Atomic
commit still retains every target and staging path, but in one flat list
without a tuple per file. Parser and chunk temporaries are released and
collected immediately before acknowledgements, after the file write and hash
state are durable and while the host is already waiting.

The fresh-interpreter FP-03 matrix measured:

| Scenario               | Before FP-08 | After FP-08 |          Reduction | Minimum free | Result |
| ---------------------- | -----------: | ----------: | -----------------: | -----------: | ------ |
| Maximum 256-byte chunk |        3,952 |       2,432 |      1,520 (38.5%) |      158,224 | PASS   |
| 32-file manifest       |       92,944 |      11,488 | **81,456 (87.6%)** |      148,976 | PASS   |
| Failed checksum        |        3,232 |       2,256 |        976 (30.2%) |      157,904 | PASS   |
| Interrupted update     |        2,976 |       2,256 |        720 (24.2%) |      157,600 | PASS   |

The bounded `CAT` and `LS` peaks remained 4,416 and 2,800 bytes. All six
stress cases passed their content, acknowledgement, checksum, commit,
interruption, and cleanup assertions.

A physical CLI update then transferred the 491-byte example configuration in
two chunks to `/fp-stress-update/physical.py`. Runtime request, reboot,
`READY`, space check, chunk acknowledgements, SHA-256 verification, atomic
commit, and final reboot all succeeded. The committed file's SHA-256
`5acd4e06427a59b9afcd97655915fda057558525096de4e98ce24f3dca4930cf`
matched its source exactly. The temporary target was removed and verified
absent, and a final physical CLI `PING` returned `PONG`.

The deployed `boot.py` matched SHA-256
`11685f4f6de3a08c16e4bf6ff2b8ba7e12db15934b5b8fd9b5c726b0859cfe20`.
Its source grew from 8,340 to 9,628 bytes but stayed within the same 12 KiB
filesystem allocation.

### FP-10 optional device logging

Commit `e82df83` first consolidated logging into a feature-complete bundled
`OTALogger`. Commit `add1d72` then removed that implementation from the
production import graph: `OTACore` now uses a tiny `NullLogger` unless the
application injects another compatible logger.

The examples try to construct `log_to_file.Logger` and fall back to
`NullLogger` when the package is absent. The standard deployment therefore
installs only URST and runs silently. `otampy deploy --with-logger` additionally
installs `log-to-file` for development, and applications remain free to inject
another logger. Removing the former public `OTALogger` is an intentional
breaking API change.

The same cold-boot probe measured allocated bytes after GC:

| Checkpoint         | Before FP-10 | After FP-10 | Clean-adjusted change |
| ------------------ | -----------: | ----------: | --------------------: |
| `clean_boot`       |        6,448 |       6,560 |              baseline |
| `import_otampy`    |       10,128 |       8,624 |            **-1,616** |
| `ota_inputs_ready` |       13,456 |       9,456 |            **-4,112** |
| `ota_constructed`  |       13,536 |       9,552 |            **-4,096** |
| `no_flag_boot`     |       14,944 |      10,576 |            **-4,480** |
| `first_poll`       |       28,640 |      23,296 |            **-5,456** |
| `idle_poll`        |       28,640 |      23,296 |            **-5,456** |

Changes are adjusted for the 112-byte difference between clean-boot
baselines. Relative to the intermediate bundled-logger result, the final
silent profile saves 3,200 bytes at first and idle poll.

Before FP-10, `/lib/otampy/logger.py` and
`/lib/log_to_file/__init__.py` occupied 4,096 and 8,192 bytes respectively.
The production profile contains neither, guaranteeing a 12 KiB
file-allocation saving. The development profile restores the 8 KiB external
logger but still avoids the bundled 4 KiB implementation. Relative to the
intermediate consolidated deployment, the clean production deployment
reported 20,480 additional free bytes; LittleFS metadata and copy-on-write
cleanup mean only the 4 KiB removed file is guaranteed by that comparison.

On MicroPython, the production profile used `NullLogger`, both logger modules
were absent, deployed source hashes matched, and physical CLI `PING` returned
`PONG`. After installing the optional package, the examples loaded
`log_to_file`, a source-labelled WARNING entry was written successfully, and
another physical `PING` returned `PONG`.

### FP-11 target-matched bytecode deployment

Commits `9531a05`, `0b59daa`, and `0ad410a` add a separate
`otampy deploy --bytecode` profile while retaining source deployment as the
default. Before erasing the device, deployment now:

- reads `sys.implementation._mpy` and derives the positive small-int width
  from `sys.maxsize`;
- compiles OTAmpy, `Blink`, and the installed URST 1.0.0 package with
  device-relative source names;
- validates every `.mpy` header's magic, major version, small-int requirement,
  and absence of architecture-specific output;
- waits for the board to reconnect after preflight.

The Raspberry Pi Pico W ran MicroPython v1.28.0 and reported `_mpy=4870`:
`.mpy` major version 6 and a 31-bit positive small-int width. `mpy-cross`
v1.27.0 emitted v6.3 bytecode with deployed headers `4d 06 00 1f`. OTAmpy's
profile deliberately emits bytecode rather than native code, so the `.mpy`
minor/native-architecture compatibility rules do not apply.

Only library and dependency modules are compiled. Root `boot.py`, `main.py`,
and `ota-config.py` remain source files. The bytecode profile packages URST itself,
does not run MIP, and rejects `--with-logger`; source plus optional
`log-to-file` remains the development profile.

The clean library tree measured:

| Content           | Source bytes | Source allocation | `.mpy` bytes | `.mpy` allocation |   Allocated saving |
| ----------------- | -----------: | ----------------: | -----------: | ----------------: | -----------------: |
| `Blink`           |          346 |             4,096 |          263 |             4,096 |                  0 |
| OTAmpy            |       21,002 |            32,768 |        7,506 |            20,480 |             12,288 |
| URST              |       20,232 |            40,960 |        6,779 |            24,576 |             16,384 |
| **Library total** |   **41,580** |        **77,824** |   **14,548** |        **49,152** | **28,672 (36.8%)** |

The raw payload fell by 27,032 bytes (65.0%). Clean in-place free space rose
from 712,704 to 778,240 bytes, an observed 65,536-byte increase. LittleFS
cleanup and metadata account for the difference beyond the guaranteed
28,672-byte file-allocation saving.

The same cold-boot probe measured allocated bytes after GC:

| Checkpoint         | Source | `.mpy` |   Change |
| ------------------ | -----: | -----: | -------: |
| `clean_boot`       |  6,560 |  6,560 | baseline |
| `import_otampy`    |  8,624 |  8,640 |      +16 |
| `ota_inputs_ready` |  9,456 |  9,440 |      -16 |
| `ota_constructed`  |  9,552 |  9,536 |      -16 |
| `no_flag_boot`     | 10,576 | 10,272 | **-304** |
| `first_poll`       | 23,296 | 22,624 | **-672** |
| `idle_poll`        | 23,296 | 22,624 | **-672** |

As expected, `.mpy` primarily saves flash: its steady heap improvement is only
672 bytes because imported bytecode still occupies RAM. All 12 modules
imported on target; no `.py` library files were present; no-flag boot,
physical `PING`, `LS`, and `CAT` passed; and all 95 host regressions passed.

### Known source payload

These are host-side raw `.py` byte counts, not on-device allocation:

| Deployed content                                           |  Files |  Raw bytes |
| ---------------------------------------------------------- | -----: | ---------: |
| `lib/otampy`                                               |      5 |     21,002 |
| `lib/Blink.py`                                             |      1 |        346 |
| deployed `boot.py`, `main.py`, and current `ota-config.py` |      3 |      3,874 |
| locally installed URST package                             |      6 |     20,232 |
| **Known subtotal**                                         | **15** | **45,454** |

This subtotal excludes `log-to-file`, logs, orphaned `.ota` files, other
application files, and filesystem overhead. Consequently, source minification
cannot explain or recover most of the reported 196 KB by itself.

Within `lib/otampy`, `boot.py` is 10,121 bytes (48% of the package) and
`manager.py` is 7,501 bytes (36%). Import lifetime matters more than shaving a
few expressions from the smaller modules.

## Findings

Impact labels are directional until the baseline tasks are complete:

- **High:** likely to remove an object/module graph or an unbounded copy.
- **Medium:** removes several persistent objects, module/file overhead, or
  repeated moderate allocations.
- **Low:** small constants/references or cosmetic source savings.

### F1. Operating-mode imports and lifetime

**Impact:** High steady-state RAM; medium flash opportunity  
**Initial evidence:** `otampy.__init__` imported `OTA`; `ota.py` imported both
`boot` and `manager` at module load; `core.py` imported `Urst`; URST then
imported its codec, protocol, constants, logging compatibility, `math`, and
`sys`.

**Progress (2026-06-30):** `OTA.boot()` and `OTA.poll()` now import their
respective handlers on demand, with an isolated regression test proving that
package import loads neither operating-mode module. This prevents
runtime-only and boot-only consumers from loading the unused mode. A Pico W
measurement confirmed that `OTA.boot()` removes the boot module from both
`sys.modules` and the package after use, then collects at the boot/main
boundary. A later `boot()` call safely re-imports it. Normal runtime retains
only `manager`.

Compatibility gate: keep `from otampy import OTA`, `OTA.boot()`, and
`OTA.poll()` working exactly as today.

### F2. A normal boot constructs a transport stack that it usually does not use

**Impact:** High boot RAM and allocation churn; likely medium runtime benefit  
**Evidence:** example `boot.py` constructs a logger, UART, `OTA`, `OTACore`,
`Urst`, `CodecLayer`, and `ProtocolLayer` before checking the update flag. If
there is no flag, boot only needs configuration, filesystem access, and
logging. Example `main.py` then constructs another logger, UART, `OTA`, and
URST object graph.

Make the flag check precede transport import/construction, or lazily create
`OTACore.transport` on first use. Then determine on the target whether
`boot.py` and `main.py` share globals. If they do, reuse one UART/logger/OTA;
if they do not, explicitly discard boot objects and collect before starting
the application. Do not assume either behaviour across ports without a test.

**Progress (2026-07-01):** `OTACore` now lazily imports and constructs URST on
first transport access. Target measurements recover 8,304 bytes after a
no-flag boot, while first polling constructs and caches the same reliable
transport used previously. UART/logger reuse remains a separate possible
lifecycle refinement.

Compatibility gate: an update-flag boot must still announce `READY`, perform
the update, verify hashes, commit, and reset.

### F3. Module configuration is duplicated into a dictionary

**Impact:** Medium steady-state RAM; medium construction peak  
**Evidence:** `_normalize_config()` calls `dir(config)`, allocates a new
dictionary, and copies every uppercase attribute. The original `config` module
and its globals remain resident.

Use a small accessor which supports `.get()` against either a mapping or module
attributes, or normalise individual values once into compact fields. This
removes the temporary `dir()` list and the duplicate dictionary, keys, and
references while retaining support for both module-style and dict-style
configuration.

**Completed (2026-07-01):** a shared accessor now reads the original mapping
or module without copying it. Tests cover default, empty, non-empty, custom
mapping, module, missing, and extra settings. Target measurements recover 160
bytes on no-flag boot and 208 bytes after first/idle polling. A class adapter
was measured and rejected because it increased target heap use.

Compatibility gate: preserve dict configs, module configs, defaults, and
unknown extra settings.

### F4. `CAT` and `LS` have unbounded transient allocation

**Impact:** High peak RAM  
**Evidence:**

- `CAT` reads the whole file, creates a formatted string containing it,
  encodes that string, and passes it to URST. URST then fragments and slices
  the payload.
- `LS` builds a list for the whole directory, creates a joined string, formats
  it, encodes it, and then hands it to the same fragmentation path.

The worst case is several simultaneous copies of the logical response. Keep
the existing single logical `CAT_OK:`/`LS_OK:` response on the wire, but teach
the transport to produce its fragments from a file/iterator or reusable
buffer. Update the host URST implementation in lockstep so it reassembles the
same bytes it does now. Add explicit size/error behaviour if the transport
cannot stream safely.

Compatibility gate: the CLI output and protocol payload must remain
byte-for-byte compatible for ordinary inputs.

**Completed (2026-07-01):** target-side production is bounded to one
194-byte logical fragment plus URST's frame temporaries, with collection at
safe fragment boundaries. Target stress peaks fell 91.4% for 16 KiB `CAT` and
88.2% for 64-entry `LS`; fragment reassembly and ordinary-response regressions
prove wire compatibility.

### F5. Update parsing and update-session state create avoidable copies

**Impact:** Medium-to-high update peak RAM  
**Evidence:** each received packet is decoded to `str`, stripped, split into a
list of strings, and then a base64 string is decoded to a new bytes object.
URST has already reassembled the fragmented `CHUNK` message. The fixed update
state is held in a string-keyed dictionary, and every staged path is retained
as a tuple until commit.

Parse command prefixes as bytes, use bounded `split`/`partition`, and avoid
decoding base64 text through Unicode. Replace the fixed-state dictionary with
compact locals or a fixed object. Retain the staged-file list because atomic
commit needs it, but measure a compact representation or on-flash journal for
large manifests. Replace `total_bytes * 1.5` with integer arithmetic to avoid
a float allocation on ports where floats use the heap.

A transport-level `readinto()`/reusable receive buffer would produce a larger
gain, but requires coordinated URST work.

**Completed (2026-07-01):** normal update packets stay as bytes, splits are
bounded, fixed state uses locals, atomic paths use a flat list, and collection
occurs at safe acknowledgement boundaries. The 32-file peak fell 87.6%, all
stress semantics passed, and a physical two-chunk CLI update committed and
verified byte-for-byte.

Compatibility gate: preserve transaction atomicity, per-file SHA-256
verification, acknowledgements, cleanup, and reset behaviour.

### F6. URST is similar in size to OTAmpy and carries desktop compatibility

**Impact:** High combined RAM/flash potential  
**Evidence:** the local URST source is 20,232 bytes versus 21,002 bytes for
`lib/otampy`. Its device import path includes logging fallbacks, typing
fallbacks, desktop serial branches, time shims, `math.ceil`, multiple module
loggers, growing buffers, and general fragmentation/reassembly structures.

Create and measure a device-specific URST build/profile rather than weakening
reliability:

- retain COBS, CRC, sequence checking, ACK/NAK, retries, fragmentation, and
  reassembly;
- exclude desktop-only imports/branches from the device artifact;
- use one injected/no-op logger rather than per-module compatibility loggers;
- use integer fragment-count arithmetic instead of importing `math`;
- preallocate or cap receive/reassembly buffers;
- omit genuinely unused device modules from the deployment.

**Logging completed (2026-07-02):** production uses an injected/no-op logger;
development can request `log-to-file` with `--with-logger`. The production
profile saves 12 KiB of guaranteed file allocation and 5,456 clean-adjusted
bytes at the measured runtime checkpoint.

Compatibility gate: run OTAmpy's protocol/update tests against both host and
device URST variants and add corrupted, duplicate, fragmented, retry, and
timeout cases.

### F7. Filesystem `.py`, `.mpy`, and frozen builds target different costs

**Impact:** Medium flash for `.mpy`; potentially high RAM for freezing

Add reproducible deployment profiles:

1. **Source profile:** current `.py` deployment, retained for development.
2. **Bytecode profile:** compile library/dependency modules with the
   target-compatible `mpy-cross`, deploy only `.mpy`, and compare file and heap
   measurements.
3. **Frozen production profile:** freeze stable OTAmpy/URST modules into a
   board-specific MicroPython firmware.

`.mpy` avoids parsing source on-device and may reduce filesystem bytes and
import peaks, but its bytecode still loads into RAM. Frozen bytecode can
execute from ROM and is the option expected to reclaim substantial persistent
heap. `.mpy` compatibility must be checked against
`sys.implementation._mpy`; a mismatched file fails to import.

Do not quote a saving until the exact target firmware and compiler are used.

**Completed (2026-07-02):** `--bytecode` performs target preflight, compiles
OTAmpy plus URST into portable bytecode, and rejects incompatible headers
before erase. On the RP2040 target it guarantees 28,672 bytes of file
allocation, saves 672 steady heap bytes, and preserves physical OTA behaviour.

References:

- [MicroPython `.mpy` files](https://docs.micropython.org/en/latest/reference/mpyfiles.html)
- [MicroPython package freezing](https://docs.micropython.org/en/latest/reference/packages.html#freezing-packages)

### F8. Module dictionaries and filesystem blocks can be reduced after F1

**Impact:** Medium flash; low-to-medium RAM  
**Evidence:** OTAmpy uses five package modules, including several small ones;
URST uses six more. Every imported module has globals/module-table overhead,
and every filesystem file may consume at least one allocation unit plus
metadata.

After the mode-specific import design is proven, consider consolidating the
small always-loaded runtime pieces (`ota`, `core`, and `manager`) while keeping
the large boot updater separable. This trades fewer module dictionaries/files
against coarser import granularity, so it must follow rather than precede F1.
Record `statvfs` block size and actual per-file allocation first.

Compatibility gate: preserve the documented top-level API. Internal module
paths should only be removed after checking downstream users.

### F9. Smaller persistent structures are worthwhile but secondary

**Impact:** Low-to-medium steady RAM

Candidates to measure after the architectural work:

- test `__slots__` for `OTA`, `OTACore`, and URST classes on every
  supported MicroPython version;
- remove duplicate object references only where ownership remains clear;
- use deliberate `gc.collect()` checkpoints after boot and update completion,
  and evaluate `gc.threshold()` with a fragmentation stress test;
- profile an injected logger separately if application logging is shown to
  cause a relevant peak.

These should not distract from import lifetime, duplicate construction, and
unbounded payload copies.

### F10. Source stripping/minification is a poor first trade

**Impact:** Low-to-medium flash only; no meaningful live-RAM gain once
precompiled/frozen

Comments and docstrings account for some raw source bytes, but minification
damages maintainability and does not address object graphs or response peaks.
An optimised `.mpy` production artifact can omit non-runtime metadata while
keeping readable source in the repository. If runtime `help()`/`__doc__`
behaviour is considered functionality, docstrings must be retained.

## Prioritised todo list

Keep IDs stable. When completing an item, change `[ ]` to `[x]`, add the date,
record before/after measurements, and link the implementing commit or PR.
Only compare measurements taken with the same board, firmware, filesystem
contents, configuration, and lifecycle checkpoint.

### P0 — establish trustworthy baselines

- [x] **FP-01 — Build a repeatable RAM checkpoint harness.** Record
      `gc.mem_alloc/free()` before and after `gc.collect()` at: clean boot,
      `import otampy`, `OTA` construction, first/idle poll, no-flag boot, flagged
      boot, one update chunk, update commit, representative `LS`, and
      representative `CAT`. Capture `micropython.mem_info(1)` for fragmentation.
      **Done when:** results and exact board/firmware revision are committed.
      **Completed (2026-07-01):** reusable boot and update probes, all named
      checkpoint results, the exact target/firmware, a fragmentation map, and
      restoration checks are committed.
- [x] **FP-02 — Inventory the deployed filesystem.** Capture every file's
      logical size, `statvfs` block size/count, logs, `.ota` files, MIP-installed
      dependency files, and clean-deploy total. Reconcile the 196.0 KB figure.
      **Done when:** known files plus measured filesystem overhead explain the
      clean baseline.
      **Completed (2026-07-01):** all 20 files and six directories, dependency and
      log allocations, filesystem geometry, clean-deploy total, and 90,112 bytes
      of filesystem/directory overhead are recorded. The generated two-block log
      exactly explains the change from 196 KiB to 204 KiB used.
- [x] **FP-03 — Add a peak-memory stress matrix.** Include a large valid file
      for `CAT`, a large directory for `LS`, maximum update chunk, many-file
      manifest, failed checksum, and interrupted update. **Done when:** each case
      reports minimum free heap and passes existing functional assertions.
      **Completed (2026-07-01):** all six cases pass on the target, report
      protocol-boundary minimum free heap, verify their functional invariants,
      clean their fixtures, and recover their per-scenario baseline after GC.

### P1 — remove the dominant costs

- [x] **FP-04 — Defer URST import and construction on the no-flag boot path**
      (F2). Measure cold boot and post-GC application heap.
      **Completed (2026-07-01):** package import and `OTA` construction no longer
      load URST; no-flag boot recovers 8,304 bytes after GC, and first/idle polling
      preserves runtime transport behaviour. Covered by target checkpoints and
      regression tests in commit `755b90e`.
- [x] **FP-05 — Make boot/runtime imports mode-specific and release boot-only
      state** (F1). Preserve the public facade and test both lifecycle paths.
      **Completed (2026-06-30):** regression tests cover lazy imports, release,
      repeated calls, and MicroPython's missing `__package__` global. Pico W
      measurements confirm boot-only retains neither mode and normal runtime
      retains only `manager`, recovering 3,552 bytes in the measured lifecycle.
- [x] **FP-06 — Eliminate module-to-dictionary config copying** (F3). Test
      mapping, module, empty, and custom config inputs.
      **Completed (2026-07-01):** all input forms retain their settings without a
      copied dictionary; target lifecycle measurements and 79 host regressions
      pass in commits `43810bd` and `df5ebef`.
- [x] **FP-07 — Implement bounded, wire-compatible `CAT` and `LS` response
      production with URST** (F4). Prove the peak no longer scales as multiple
      full-response copies.
      **Completed (2026-07-01):** bounded URST fragments preserve exact logical
      payloads and reduce target peaks by 46,848 bytes for `CAT` and 20,864 bytes
      for `LS`, without consuming another filesystem block.
- [x] **FP-08 — Parse update commands as bytes and compact update state**
      (F5). Record peak heap for the stress matrix before and after.
      **Completed (2026-07-01):** the many-file peak fell from 92,944 to 11,488
      bytes, maximum-chunk and failure peaks also fell, all stress assertions
      passed, and a physical CLI update completed and verified successfully.
- [ ] **FP-09 — Define and test a MicroPython-specific URST artifact** (F6).
      Keep all reliability semantics and publish its source, `.mpy`, import-RAM,
      and peak-buffer deltas.
      **Deferred (2026-07-02):** intentionally skipped for now; retain this item
      for later work in the canonical URST repository.
- [x] **FP-10 — Consolidate device logging to one implementation** (F6).
      Preserve levels, file fallback, module labels, and formatting used by the
      examples before removing either dependency.
      **Completed (2026-07-02):** production defaults to `NullLogger`, development
      can install `log-to-file` with `--with-logger`, runtime heap falls 5,456
      clean-adjusted bytes, guaranteed production file allocation falls 12 KiB,
      both target profiles and physical OTA pass, and 78 regressions pass.
- [x] **FP-11 — Add a target-matched `.mpy` deployment profile** (F7). Fail
      deployment clearly on incompatible bytecode and retain source deployment
      for development.
      **Completed (2026-07-02):** the profile validates target version/small-int
      compatibility before erase, saves 28,672 allocated file bytes and 672
      steady heap bytes, passes 95 regressions, and completes physical
      import/boot/`PING`/`LS`/`CAT` checks.

### P2 — compound the gains

- [ ] **FP-12 — Evaluate module consolidation using measured filesystem
      allocation and module RAM** (F8). Merge only always-loaded pieces.
- [ ] **FP-13 — Evaluate `__slots__`, injected-logger overhead, and ownership
      cleanup** (F9) on all supported ports.
- [ ] **FP-14 — Add explicit GC checkpoints/threshold only if stress data
      improves** (F9). Record pause-time and fragmentation effects as well as free
      bytes.

### P3 — production option

- [ ] **FP-15 — Prototype a frozen-module firmware profile** (F7). Freeze
      stable OTAmpy and URST dependencies, then compare heap, import time,
      firmware size, filesystem free space, and update workflow against FP-01/02.

## Acceptance rules for every footprint change

A reduction is accepted only when:

1. all existing device and CLI tests pass;
2. public imports and CLI-visible behaviour remain compatible;
3. update atomicity, checksum verification, recovery, and reliable transport
   semantics are unchanged;
4. both steady-state and worst-case peak measurements improve or the trade-off
   is documented;
5. source, `.mpy`, and frozen figures are not mixed in the same comparison;
6. readability is retained in repository source—generated production
   artifacts may be compact, source code should not be hand-minified.

The official MicroPython measurement guidance recommends collecting garbage
around checkpoints and using `micropython.mem_info()`/`gc.mem_free()` rather
than inferring heap use from source size:
[MicroPython on constrained devices](https://docs.micropython.org/en/latest/reference/constrained.html#the-heap).
