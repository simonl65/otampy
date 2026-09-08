"""Replay guard for authenticated channel-0 commands.

The counter is issued by the host as ``max(persisted + 1, unix_seconds)``
and must be strictly increasing. This module holds the device's view of
"highest counter already accepted", in RAM, with an optional flash floor
so a reboot commanded over the link cannot be replayed afterwards.

Nothing here may raise: it is reached from ``manager.poll()``, inside the
application's main loop.
"""

import builtins

import device_otampy.replay as replay
import pytest


@pytest.fixture
def floor_path(tmp_path):
    return str(tmp_path / "otampy-replay-floor")


# --- accept() -----------------------------------------------------------


def test_a_higher_counter_is_accepted_and_advances_the_guard():
    guard = replay.ReplayGuard()
    assert guard.accept(100) is True
    assert guard.last_seen == 100


def test_the_same_counter_twice_is_rejected():
    guard = replay.ReplayGuard()
    assert guard.accept(100) is True
    assert guard.accept(100) is False
    assert guard.last_seen == 100


def test_a_lower_counter_is_rejected():
    guard = replay.ReplayGuard()
    guard.accept(100)
    assert guard.accept(99) is False
    assert guard.last_seen == 100


def test_a_gap_in_counters_is_accepted():
    # Strictly `>`, never `== last + 1`. The host issues a fresh counter
    # per retry attempt and seeds from wall-clock, so gaps are normal and
    # must not wedge the guard.
    guard = replay.ReplayGuard()
    guard.accept(100)
    assert guard.accept(5000) is True
    assert guard.last_seen == 5000


def test_a_rejected_counter_does_not_advance_the_guard():
    # The ordering trap from F-15a: if a rejected counter advanced
    # last_seen, one forged high counter would lock out the real host.
    guard = replay.ReplayGuard()
    guard.accept(100)
    guard.accept(10**9)  # accepted, legitimately high
    assert guard.accept(50) is False
    assert guard.last_seen == 10**9


# --- load_floor() -------------------------------------------------------


def test_a_missing_floor_file_loads_as_zero(floor_path):
    assert replay.load_floor(floor_path) == 0


def test_a_garbage_floor_file_loads_as_zero(floor_path):
    with open(floor_path, "w") as f:
        f.write("not a number")
    assert replay.load_floor(floor_path) == 0


def test_an_empty_floor_file_loads_as_zero(floor_path):
    with open(floor_path, "w") as f:
        f.write("")
    assert replay.load_floor(floor_path) == 0


def test_a_negative_floor_loads_as_zero(floor_path):
    with open(floor_path, "w") as f:
        f.write("-5")
    assert replay.load_floor(floor_path) == 0


def test_an_out_of_u32_floor_loads_as_zero(floor_path):
    # F-16's lesson: an implausible stored value is corruption, not a
    # counter. Accepting it would reject every real command forever.
    with open(floor_path, "w") as f:
        f.write(str(2**40))
    assert replay.load_floor(floor_path) == 0


def test_a_floor_file_that_raises_oserror_loads_as_zero(
    monkeypatch, floor_path
):
    def boom(*_args, **_kwargs):
        raise OSError("flash is unhappy")

    monkeypatch.setattr(builtins, "open", boom)
    assert replay.load_floor(floor_path) == 0


def test_surrounding_whitespace_in_the_floor_file_is_tolerated(floor_path):
    with open(floor_path, "w") as f:
        f.write("  4242\n")
    assert replay.load_floor(floor_path) == 4242


def test_load_floor_with_no_path_configured_is_zero():
    assert replay.load_floor(None) == 0
    assert replay.load_floor("") == 0


# --- persist_floor() and the restart round trip -------------------------


def test_persist_then_load_round_trips(floor_path):
    guard = replay.ReplayGuard()
    guard.accept(123456)
    assert guard.persist_floor(floor_path) is True
    assert replay.load_floor(floor_path) == 123456


def test_a_guard_constructed_from_a_floor_rejects_a_replay_below_it(floor_path):
    # The case a RAM-only counter cannot cover: an authenticated reboot,
    # then the captured frame replayed after the device comes back.
    with open(floor_path, "w") as f:
        f.write("900")
    guard = replay.ReplayGuard(replay.load_floor(floor_path))
    assert guard.accept(900) is False
    assert guard.accept(899) is False
    assert guard.accept(901) is True


def test_persist_floor_swallows_an_oserror_and_reports_failure(
    monkeypatch, floor_path
):
    # The caller is about to machine.reset(); a failed flash write must
    # never propagate and must never block the reset.
    def boom(*_args, **_kwargs):
        raise OSError("flash is full")

    monkeypatch.setattr(builtins, "open", boom)
    guard = replay.ReplayGuard()
    guard.accept(7)
    assert guard.persist_floor(floor_path) is False


def test_persist_floor_with_no_path_configured_is_a_no_op(floor_path):
    guard = replay.ReplayGuard()
    guard.accept(7)
    assert guard.persist_floor(None) is False
    assert guard.persist_floor("") is False


def test_persist_floor_writes_a_plain_integer(floor_path):
    guard = replay.ReplayGuard()
    guard.accept(4242)
    guard.persist_floor(floor_path)
    with open(floor_path) as f:
        assert f.read().strip() == "4242"
