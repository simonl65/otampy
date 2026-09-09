# Boot-time recovery listen window — dev log

Spec: `docs/development/failsafe-update-boot-listen-spec.md`
Branch: `feature/failsafe-update-boot-listen`

## 2026-09-09 — D2 re-confirmed before any code

The spec's red-team overturned signed-off decision D2 (a `RECOVERY` beacon
broadcast at window open). `Urst.send()` is stop-and-wait reliable, so with no
host listening it costs up to ~8 s per boot: `protocol.connect()` at 4 attempts
× `ACK_TIMEOUT_MS` 1000, then `send_reliable()` for 4 more. Sending it
unreliably would mean reaching into URST's frame codec, which the parent
sign-off excluded.

Simon re-confirmed the replacement: **silent window + host blind-retry**, no
beacon, no wire-format change. Recorded in the spec's Protocol decision.

## Step 1 — extract the auth gate into `authgate.py`

Pure move, no behaviour change. `_AUTH_PREFIX`, `_AUTH_FIELDS`,
`_REPLAY_FLOOR_FILE`, `_UNAUTHENTICATED`, `_REPLAYED`, `_replay_floor_path`,
`_auth_blocks`, `_replay_guard`, `_authenticate` (→ `authenticate`) and
`_persist_replay_floor` (→ `persist_replay_floor`) moved out of `manager.py`.

`manager.py` keeps a thin `_persist_replay_floor` wrapper that holds the
`core._replay_guard is None` early-out **at the call site**, so the reset paths
(`RB`/`SR`/`UPDATE_REQUEST`/`ROLLBACK`) can keep calling it unconditionally
while a no-auth device never imports `authgate`.

Evidence the no-auth path stays clean (the spec's stated risk for this step) —
ad-hoc probe with `OTA_REQUIRE_AUTH` absent:

| Command | Reply | `authgate` in `sys.modules` |
| --- | --- | --- |
| `PING` | `b'PONG'` | `False` |
| `RB` | `b'RB_OK'` | `False` |
| `SR` | `b'SR_OK'` | `False` |

Guard suites: `test_manager_auth.py`, `test_command_auth_contract.py`,
`test_ota_facade.py` — 109 passed. Full device suite 315 passed, identical to
the pre-change baseline. `ruff check .` clean.

## Step 2 — `restore.rollback_result()`, `manager.poll` refactored onto it

Four tests written first, all failing on `AttributeError: module
'device_otampy.restore' has no attribute 'rollback_result'` before the
implementation existed.

`rollback_result(core) -> (reply_bytes, restored_count)` wraps the unchanged
`rollback()`. `_ROLLBACK_BUSY` now stays private to `restore.py` — it is folded
into a reply rather than crossing a module boundary, which is the point: the
boot window would otherwise have to import and interpret it too.

`manager.poll`'s `ROLLBACK` branch drops from 12 lines to 8 and no longer
carries the reply strings. The `ROLLBACK_ERR` strings now appear exactly once
each in code (`restore.py:56-57`); the remaining tree hits are `docs/protocol.md`
and `CHANGELOG.md`, which are documentation.

`test_ota_manager.py`'s existing `ROLLBACK` tests passed untouched — the guard
that the refactor changed no behaviour. Device suite 319 passed (315 + 4 new).

Note: `uv run pyright` reports one pre-existing error in `restore.py` (`trial()`,
`attempt > limit`, because `_get_config` is typed `Any | None`). Confirmed
present on `develop` before this branch — line number moved 294 → 317 only.
Pyright does not gate CI.

## Step 3 — `boot._run_boot_listen()`, the window itself

12 tests written first, all red on `AttributeError: module
'device_otampy.boot' has no attribute '_run_boot_listen'`.

Tests use a fake monotonic clock (`itertools.count` patched over
`boot._ticks_ms`, with `_sleep_ms` a no-op) so no test ever really sleeps a
window. The whole device suite still runs in ~4 s.

Two design points worth remembering:

- **The deadline is absolute, not inactivity-based.**
  `_run_default_update_loop` resets `last_activity` on every packet; the
  window must not, or a chatty peer could pin a device inside it. Covered by
  `test_boot_listen_deadline_is_absolute_not_inactivity`, which queues 500
  refused `PING`s and asserts fewer than 200 are served before the window
  closes on schedule.
- **A refusal keeps the window open.** `ROLLBACK` with nothing retained
  replies and *keeps listening*, so an operator who guesses wrong can still
  land `UPDATE_REQUEST` in the same window without another power cycle.
  Covered by `test_boot_listen_refusal_does_not_consume_the_window`.

Non-UTF-8 packets are dropped in silence (per the spec's dispatch table),
not answered with `ERROR:Invalid UTF-8` as the update loop does. The
high-bit scan from the update loop is reused so pure-ASCII packets never pay
for a decode.

`boot.py` still contains no import of `manager` (grep, no hits) — the reason
`authgate` was extracted in step 1. `boot._persist_replay_floor` duplicates
`manager`'s four-line guard on purpose; sharing it would mean importing
`manager` into the boot phase, which is the exact cost being avoided. Noted
in both docstrings.

Device suite 331 passed (319 + 12). `ruff check .` clean; ruff format
reformatted the new test file.
