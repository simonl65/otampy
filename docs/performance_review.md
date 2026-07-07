# MicroPython Performance Review

This document contains a speed and memory allocation audit of the `otampy` device-side firmware, structured according to the official performance-tuning procedure.

---

## 1. Design & Allocation Review (Stage 1)

### Resolved: Frequent Logging in the Hot Path
In MicroPython, the garbage collector (GC) costs several milliseconds when it triggers. To avoid this, we must minimize heap allocations in code that runs inside tight loops.

*   **Previous problem**: `OTA.poll()` used to log on every iteration:
    ```python
    def poll(self, callback=None):
        self._core.logger.debug("OTA manager poll")
        _manager.poll(self._core, callback)
    ```
*   **Current state**: The call has been removed. The standard deployment also
    defaults to `NullLogger`, while `--with-logger` installs optional
    development logging. The example loop performs no unconditional
    per-iteration logging.

---

## 2. Profiling (Stage 2)

To measure the actual execution times of the main loop and `ota.poll()` without guessing, we can use a MicroPython-compatible `@timed_function` wrapper.

### Implementation:
Add this utility to measure the loop overhead:
```python
import time

def timed_function(f):
    myname = str(f).split(' ')[1]
    def wrapper(*args, **kwargs):
        t = time.ticks_us()
        res = f(*args, **kwargs)
        dt = time.ticks_diff(time.ticks_us(), t)
        print(f"Function {myname} took {dt / 1000.0:.3f} ms")
        return res
    return wrapper
```
Decorate `ota.poll` or your main loop functions during testing to capture precise timing figures.

---

## 3. Python Syntax Improvements (Stage 3)

### Caching Attributes & Level Checks
Dictionary lookups (like resolving `self._core.logger.debug`) are expensive in MicroPython. We can cache reference calls or guard them behind a quick integer comparison.

*   **Guard Logging Calls**:
    For an injected logger in an application hot loop, cache its method and
    guard message construction behind its level:
    ```python
    debug = logger.debug
    debug_enabled = getattr(logger, "min_level", 0) <= 0

    # Inside the main loop
    if debug_enabled:
        debug("sensor value: %s", sensor_value)
    ```
    OTAmpy's `NullLogger` sets `min_level` above DEBUG, so this guard also
    avoids formatting work in the silent profile.
*   **Use `const()` for Numeric Constants**:
    If your telemetry or manager parser defines state machines or flags, ensure they are declared as `const()` to substitute values at compile-time:
    ```python
    from micropython import const

    STATE_IDLE = const(0)
    STATE_RECEIVING = const(1)
    ```

---

## 4. Native Emitter (Stage 4)

If your telemetry or data parsing functions (`do_application_stuff`) contain math or bitwise parsing, compile them to machine code by decorating them with `@micropython.native`.

*   **Example**:
    ```python
    @micropython.native
    def parse_adc_telemetry(raw_bytes):
        # Compiles to native CPU opcodes, doubling execution speed.
        pass
    ```
    > [!IMPORTANT]
    > Long-running native functions do not yield the GIL or run the MicroPython background scheduler. Call `time.sleep(0)` periodically inside them if they execute for more than a few milliseconds.

---

## 5. Viper Emitter (Stage 5)

For ultra-high-speed operations (such as custom UART parsing or high-frequency telemetry formatting), utilize the `@micropython.viper` emitter with explicit type annotations.

*   **Example**:
    ```python
    @micropython.viper
    def parse_fast_buffer(buf_ptr: ptr8, length: int) -> int:
        checksum = 0
        for i in range(length):
            checksum ^= buf_ptr[i]
        return checksum
    ```
    > [!CAUTION]
    > Viper pointers (`ptr8`, `ptr16`, `ptr32`) do not perform bounds checking. Writing past the buffer allocation leads to memory corruption.

---

## 6. Direct Hardware Access (Stage 6)

For operations that demand microsecond-level timing (e.g., high-speed GPIO toggling in your application callback), bypass the `machine.Pin` abstraction class entirely and read/write the registers directly.

### Raspberry Pi Pico (RP2) Direct Pin Toggling:
```python
from micropython import const
import machine

# GPIO registers for RP2
GPIO_OUT_XOR = const(0xd000001c)  # SIO GPIO output XOR register
LED_PIN_MASK = const(1 << 25)     # Pico onboard LED pin (GPIO25)

@micropython.viper
def fast_toggle_led():
    ptr32(GPIO_OUT_XOR)[0] = LED_PIN_MASK
```
This reduces a pin-toggle operation from 15–20 microseconds down to less than a microsecond.
