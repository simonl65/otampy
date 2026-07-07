"""
Timing function for performance monitoring.
Usage example:
@timed_function
def add(a, b):
    time.sleep_ms(25)  # works in both now
    return a + b


result = add(2, 3)
print("result:", result)
"""

try:
    import utime as time
except Exception:
    import time as _time

    class _TimeShim:
        @staticmethod
        def ticks_us():
            return int(_time.perf_counter() * 1_000_000)  # type: ignore

        @staticmethod
        def ticks_diff(t1, t0):
            return t1 - t0

        # keep your existing call working if you use it elsewhere
        sleep_ms = staticmethod(lambda ms: _time.sleep(ms / 1000.0))

    time = _TimeShim()


def timed_function(f):
    myname = str(f).split(" ")[1]

    def wrapper(*args, **kwargs):
        t = time.ticks_us()
        res = f(*args, **kwargs)
        dt = time.ticks_diff(time.ticks_us(), t)
        print(f"Function {myname} took {dt / 1000.0:.3f} ms")
        return res

    return wrapper
