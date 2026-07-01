# Device footprint review

**Status:** Initial review  
**Last updated:** 2026-06-30  
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
5. Produce a MicroPython-specific URST/logging deployment and compare `.mpy`
   and frozen-module builds.

Native/Viper emitters are not proposed. They optimise execution speed, can
increase code size, and introduce portability or safety costs without
addressing the dominant footprint issues here.

## What the current numbers do and do not show

The supplied snapshot is:

| Resource | Allocated/used | Free | Assessment |
| --- | ---: | ---: | --- |
| Python heap | 77.8 KB (38.8%) | 122.9 KB | Healthy at the sampled instant, but no peak or fragmentation data |
| Device filesystem | 196.0 KB (23.1%) | 652.0 KB | Healthy, but not attributable to OTAmpy from this snapshot |

`manager.py` samples `gc.mem_alloc()` directly. It does not run
`gc.collect()` first, so the 77.8 KB includes both live objects and any
uncollected garbage. A before/after-GC pair is needed before treating it as a
steady-state baseline.

### Initial device diagnostic

On 2026-06-30, the pre-refactor deployment was inspected on a Raspberry Pi
Pico W running MicroPython v1.28.0. After connecting to the already-running
application:

| Checkpoint | Allocated | Free |
| --- | ---: | ---: |
| Before explicit GC | 150,864 bytes | 54,576 bytes |
| After `gc.collect()` | 31,200 bytes | 174,240 bytes |

Both `otampy.boot` and `otampy.manager` were present in `sys.modules`. The
119,664-byte post-GC reduction confirms that an uncollected `MEM` result is not
a reliable live-heap baseline. This was not a controlled cold boot, so it is
diagnostic evidence only and does not complete FP-01.

### Post-F1 device diagnostic

The lazy-import facade was deployed to the same board and verified by SHA-256.
The boot-only checkpoint and two normal-lifecycle runs produced:

| Lifecycle | Allocated after GC | Free after GC | `boot` loaded | `manager` loaded |
| --- | ---: | ---: | --- | --- |
| Boot only | 25,440 bytes | 180,000 bytes | Yes | No |
| Normal boot-to-main, run 1 | 29,952 bytes | 175,488 bytes | Yes | Yes |
| Normal boot-to-main, run 2 | 29,952 bytes | 175,488 bytes | Yes | Yes |
| Boot only, after release | 22,064 bytes | 183,376 bytes | No | No |
| Normal boot-to-main, after release | 26,400 bytes | 179,040 bytes | No | Yes |

The isolated mode behaviour and explicit boot-module release work on the
target. Releasing `boot` recovered 3,376 bytes in the boot-only checkpoint and
3,552 bytes in the normal lifecycle compared with the lazy-import-only
deployment. The normal application retains only the runtime `manager` module.

The flash figure comes from `statvfs("/")`. It includes every deployed
application/dependency/log/staging file plus filesystem metadata and block
rounding. It is not the size of `packages/device` alone.

### Known source payload

These are host-side raw `.py` byte counts, not on-device allocation:

| Deployed content | Files | Raw bytes |
| --- | ---: | ---: |
| `lib/otampy` | 6 | 17,007 |
| `lib/Blink.py` | 1 | 346 |
| deployed `boot.py`, `main.py`, and current `config.py` | 3 | 3,747 |
| locally installed URST package | 6 | 20,232 |
| **Known subtotal** | **16** | **41,332** |

This subtotal excludes `log-to-file`, logs, orphaned `.ota` files, other
application files, and filesystem overhead. Consequently, source minification
cannot explain or recover most of the reported 196 KB by itself.

Within `lib/otampy`, `boot.py` is 8,244 bytes (48% of the package) and
`manager.py` is 4,204 bytes (25%). Import lifetime matters more than shaving a
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

Compatibility gate: preserve transaction atomicity, per-file SHA-256
verification, acknowledgements, cleanup, and reset behaviour.

### F6. URST is at least as large as OTAmpy and carries desktop compatibility

**Impact:** High combined RAM/flash potential  
**Evidence:** the local URST source is 20,232 bytes versus 17,007 bytes for
`lib/otampy`. Its device import path includes logging fallbacks, typing
fallbacks, desktop serial branches, time shims, `math.ceil`, multiple module
loggers, growing buffers, and general fragmentation/reassembly structures.
The deploy also installs `log-to-file`, while OTAmpy ships `OTALogger`.

Create and measure a device-specific URST build/profile rather than weakening
reliability:

- retain COBS, CRC, sequence checking, ACK/NAK, retries, fragmentation, and
  reassembly;
- exclude desktop-only imports/branches from the device artifact;
- use one injected/no-op logger rather than per-module compatibility loggers;
- use integer fragment-count arithmetic instead of importing `math`;
- preallocate or cap receive/reassembly buffers;
- omit genuinely unused device modules from the deployment.

Separately, select one logging implementation. If `OTALogger` absorbs the
module-name and formatting features used by the examples, `log-to-file` can be
removed without losing logging functionality. Otherwise, remove the fallback
implementation and depend on `log-to-file`. The exact saving must be measured
from the files actually installed by `mip`.

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

References:

- [MicroPython `.mpy` files](https://docs.micropython.org/en/latest/reference/mpyfiles.html)
- [MicroPython package freezing](https://docs.micropython.org/en/latest/reference/packages.html#freezing-packages)

### F8. Module dictionaries and filesystem blocks can be reduced after F1

**Impact:** Medium flash; low-to-medium RAM  
**Evidence:** OTAmpy uses six package modules, including several small ones;
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

- replace `OTALogger.log_levels`' string-keyed dictionary with compact integer
  constants/conversion logic;
- test `__slots__` for `OTA`, `OTACore`, `OTALogger`, and URST classes on every
  supported MicroPython version;
- remove duplicate object references only where ownership remains clear;
- use deliberate `gc.collect()` checkpoints after boot and update completion,
  and evaluate `gc.threshold()` with a fragmentation stress test;
- write log line segments directly or reuse a buffer if logging is shown to
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

- [ ] **FP-01 — Build a repeatable RAM checkpoint harness.** Record
  `gc.mem_alloc/free()` before and after `gc.collect()` at: clean boot,
  `import otampy`, `OTA` construction, first/idle poll, no-flag boot, flagged
  boot, one update chunk, update commit, representative `LS`, and
  representative `CAT`. Capture `micropython.mem_info(1)` for fragmentation.
  **Done when:** results and exact board/firmware revision are committed.
- [ ] **FP-02 — Inventory the deployed filesystem.** Capture every file's
  logical size, `statvfs` block size/count, logs, `.ota` files, MIP-installed
  dependency files, and clean-deploy total. Reconcile the 196.0 KB figure.
  **Done when:** known files plus measured filesystem overhead explain the
  clean baseline.
- [ ] **FP-03 — Add a peak-memory stress matrix.** Include a large valid file
  for `CAT`, a large directory for `LS`, maximum update chunk, many-file
  manifest, failed checksum, and interrupted update. **Done when:** each case
  reports minimum free heap and passes existing functional assertions.

### P1 — remove the dominant costs

- [ ] **FP-04 — Defer URST import and construction on the no-flag boot path**
  (F2). Measure cold boot and post-GC application heap.
- [x] **FP-05 — Make boot/runtime imports mode-specific and release boot-only
  state** (F1). Preserve the public facade and test both lifecycle paths.
  **Completed (2026-06-30):** regression tests cover lazy imports, release,
  repeated calls, and MicroPython's missing `__package__` global. Pico W
  measurements confirm boot-only retains neither mode and normal runtime
  retains only `manager`, recovering 3,552 bytes in the measured lifecycle.
- [ ] **FP-06 — Eliminate module-to-dictionary config copying** (F3). Test
  mapping, module, empty, and custom config inputs.
- [ ] **FP-07 — Implement bounded, wire-compatible `CAT` and `LS` response
  production with URST** (F4). Prove the peak no longer scales as multiple
  full-response copies.
- [ ] **FP-08 — Parse update commands as bytes and compact update state**
  (F5). Record peak heap for the stress matrix before and after.
- [ ] **FP-09 — Define and test a MicroPython-specific URST artifact** (F6).
  Keep all reliability semantics and publish its source, `.mpy`, import-RAM,
  and peak-buffer deltas.
- [ ] **FP-10 — Consolidate device logging to one implementation** (F6).
  Preserve levels, file fallback, module labels, and formatting used by the
  examples before removing either dependency.
- [ ] **FP-11 — Add a target-matched `.mpy` deployment profile** (F7). Fail
  deployment clearly on incompatible bytecode and retain source deployment
  for development.

### P2 — compound the gains

- [ ] **FP-12 — Evaluate module consolidation using measured filesystem
  allocation and module RAM** (F8). Merge only always-loaded pieces.
- [ ] **FP-13 — Evaluate compact logger levels, `__slots__`, and ownership
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
