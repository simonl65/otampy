# F-10 — boot-time recovery window: raw on-device evidence

Captured 2026-09-10 by temporary `_diag()` instrumentation in
`boot._run_boot_listen` (HIL only; never committed to the device library).
`ts` is `ticks_ms()` — time since the last *hardware* reset, so entries with a
large `ts` are `mpremote`-induced soft reboots, not power cycles.

Run configuration: device stranded with a one-line `raise RuntimeError`
`main.py`; `OTA_BOOT_LISTEN_MS = 15000` (diagnostic widening from the 1000
default); host running `otampy rollback --recover` over the XBee gateway.

See `failsafe-update-boot-listen-log.md` and F-10 in `findings.md` for the
analysis. Key rows: first packet at `ts=5704` and `ts=10885` after *power*
cycles (cold XBee) versus `ts=2275` after a *software* reset (warm XBee).

```
BLW call has_flag=False
BLW start window_ms=15000 ts=2045
BLW raw#1 len=2 hex=4c53 ts=5704
BLW decoded packet=b'LS'
BLW refused unrecognised packet=b'LS'
BLW raw#2 len=14 hex=5550444154455f52455155455354 ts=5883
BLW decoded packet=b'UPDATE_REQUEST'
BLW matched UPDATE_REQUEST
BLW call has_flag=True
BLW call has_flag=False
BLW start window_ms=15000 ts=2139
BLW call has_flag=False
BLW start window_ms=15000 ts=2171
BLW raw#1 len=8 hex=524f4c4c4241434b ts=10885
BLW decoded packet=b'ROLLBACK'
BLW matched ROLLBACK
BLW call has_flag=False
BLW start window_ms=15000 ts=2195
BLW raw#1 len=4 hex=50494e47 ts=2275
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#2 len=4 hex=50494e47 ts=2873
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#3 len=4 hex=50494e47 ts=3412
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#4 len=4 hex=50494e47 ts=3953
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#5 len=4 hex=50494e47 ts=4496
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#6 len=4 hex=50494e47 ts=5063
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#7 len=4 hex=50494e47 ts=5670
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#8 len=4 hex=50494e47 ts=6211
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#9 len=4 hex=50494e47 ts=6770
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#10 len=4 hex=50494e47 ts=7313
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#11 len=4 hex=50494e47 ts=7852
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#12 len=4 hex=50494e47 ts=8400
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#13 len=4 hex=50494e47 ts=9010
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#14 len=4 hex=50494e47 ts=9562
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW raw#15 len=4 hex=50494e47 ts=10126
BLW decoded packet=b'PING'
BLW refused unrecognised packet=b'PING'
BLW call has_flag=False
BLW start window_ms=15000 ts=2126
BLW timeout iters=15 nonempty=0 elapsed=15234
BLW call has_flag=False
BLW start window_ms=15000 ts=25801
BLW timeout iters=15 nonempty=0 elapsed=15294
BLW call has_flag=False
BLW start window_ms=15000 ts=62651
BLW timeout iters=15 nonempty=0 elapsed=15235
```
