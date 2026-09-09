from pathlib import Path

import shared
from device_otampy import restore
from device_otampy.core import OTACore


def _core(tmp_path, **extra):
    config = {"OTA_JOURNAL_FILE": str(tmp_path / "otampy-update.journal")}
    config.update(extra)
    return OTACore(shared.FakeUART(), config=config, logger=shared.FakeLogger())


# =============================================================================
# Journal read/write round-trip
# =============================================================================


def test_journal_round_trip(tmp_path):
    """An integer line 1 is a committed candidate on trial."""
    core = _core(tmp_path)
    paths = [str(tmp_path / "main.py"), str(tmp_path / "lib" / "sensor.py")]

    assert restore.write_journal(core, 0, paths) is True

    assert restore.read_journal(core) == (0, restore._STATE_TRIAL, paths)


def test_journal_round_trip_counter_carries_attempt(tmp_path):
    core = _core(tmp_path)
    paths = [str(tmp_path / "main.py")]

    assert restore.write_journal(core, 2, paths) is True

    assert restore.read_journal(core) == (2, restore._STATE_TRIAL, paths)


def test_journal_round_trip_in_progress(tmp_path):
    core = _core(tmp_path)
    paths = [str(tmp_path / "main.py")]

    assert restore.write_journal(core, restore._STATE_COMMITTING, paths)

    assert restore.read_journal(core) == (0, restore._STATE_COMMITTING, paths)


def test_journal_round_trip_confirmed(tmp_path):
    """A confirmed candidate keeps its path list but stops trial counting."""
    core = _core(tmp_path)
    paths = [str(tmp_path / "main.py")]

    assert restore.write_journal(core, restore._STATE_CONFIRMED, paths)

    assert restore.read_journal(core) == (0, restore._STATE_CONFIRMED, paths)


def test_journal_missing_file_reads_empty(tmp_path):
    """No journal means nothing on trial, so the state is "confirmed"."""
    core = _core(tmp_path)

    assert restore.read_journal(core) == (0, restore._STATE_CONFIRMED, [])


def test_journal_empty_file_reads_empty(tmp_path):
    core = _core(tmp_path)
    (tmp_path / "otampy-update.journal").write_text("")

    assert restore.read_journal(core) == (0, restore._STATE_CONFIRMED, [])


def test_journal_malformed_first_line_is_in_progress(tmp_path):
    """Fail safe: an unreadable counter means "restore everything"."""
    core = _core(tmp_path)
    (tmp_path / "otampy-update.journal").write_text("garbage\n/main.py\n")

    assert restore.read_journal(core) == (
        0,
        restore._STATE_COMMITTING,
        ["/main.py"],
    )


def test_journal_uses_default_path_when_unconfigured(tmp_path, monkeypatch):
    core = OTACore(shared.FakeUART(), config={}, logger=shared.FakeLogger())
    monkeypatch.setattr(
        restore, "_resolve_path", lambda p: str(tmp_path / p.lstrip("/"))
    )

    assert restore._journal_path(core) == str(
        tmp_path / restore._DEFAULT_JOURNAL
    )


# =============================================================================
# clear_journal
# =============================================================================


def test_clear_journal_removes_backups_and_journal(tmp_path):
    core = _core(tmp_path)
    target = tmp_path / "main.py"
    backup = tmp_path / ("main.py" + restore._BACKUP_SUFFIX)
    target.write_bytes(b"new")
    backup.write_bytes(b"old")
    restore.write_journal(core, 0, [str(target)])

    restore.clear_journal(core)

    assert not backup.exists()
    assert not (tmp_path / "otampy-update.journal").exists()
    # The live target is untouched -- only the retained backup goes.
    assert target.read_bytes() == b"new"


def test_clear_journal_is_a_noop_when_nothing_exists(tmp_path):
    core = _core(tmp_path)

    restore.clear_journal(core)

    assert not (tmp_path / "otampy-update.journal").exists()


def test_write_journal_returns_false_on_oserror(tmp_path):
    """An unwritable journal path must not raise out of the boot loop."""
    core = _core(tmp_path, OTA_JOURNAL_FILE=str(tmp_path / "nodir" / "j"))

    assert restore.write_journal(core, 0, []) is False


# =============================================================================
# commit() -- all-or-nothing rename with .bck
# =============================================================================


def _staged_pair(tmp_path, name, old, new):
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(old)
    staging = tmp_path / (name + ".ota")
    staging.write_bytes(new)
    return str(target), str(staging)


def test_commit_success_multi_file(tmp_path):
    core = _core(tmp_path)
    t1, s1 = _staged_pair(tmp_path, "main.py", b"old-main", b"new-main")
    t2, s2 = _staged_pair(
        tmp_path, "lib/sensor.py", b"old-sensor", b"new-sensor"
    )

    assert restore.commit(core, [t1, s1, t2, s2], []) is True

    assert Path(t1).read_bytes() == b"new-main"
    assert Path(t2).read_bytes() == b"new-sensor"
    assert Path(t1 + ".bck").read_bytes() == b"old-main"
    assert Path(t2 + ".bck").read_bytes() == b"old-sensor"
    assert not (tmp_path / "main.py.ota").exists()
    assert restore.read_journal(core) == (0, restore._STATE_TRIAL, [t1, t2])


def test_commit_rolls_back_whole_set_on_rename_failure(tmp_path, monkeypatch):
    core = _core(tmp_path)
    t1, s1 = _staged_pair(tmp_path, "main.py", b"old-main", b"new-main")
    t2, s2 = _staged_pair(
        tmp_path, "lib/sensor.py", b"old-sensor", b"new-sensor"
    )

    real_rename = restore._os.rename

    def flaky_rename(src, dst):
        if src == s2:
            raise OSError("boom")
        return real_rename(src, dst)

    monkeypatch.setattr(restore._os, "rename", flaky_rename)

    assert restore.commit(core, [t1, s1, t2, s2], []) is False

    # Every already-renamed target is back to its original content.
    assert Path(t1).read_bytes() == b"old-main"
    assert Path(t2).read_bytes() == b"old-sensor"
    # Journal stays "committing" so a later repair() finishes the reversal.
    assert restore.read_journal(core)[1] == restore._STATE_COMMITTING


def test_commit_applies_delete_paths_and_their_backups(tmp_path):
    core = _core(tmp_path)
    t1, s1 = _staged_pair(tmp_path, "main.py", b"old", b"new")
    goner = tmp_path / "obsolete.py"
    goner.write_bytes(b"x")
    goner_bck = tmp_path / ("obsolete.py" + restore._BACKUP_SUFFIX)
    goner_bck.write_bytes(b"x")

    assert restore.commit(core, [t1, s1], [str(goner)]) is True

    assert not goner.exists()
    assert not goner_bck.exists()


# =============================================================================
# repair() -- finish or reverse an interrupted commit
# =============================================================================


def test_restore_all_restores_whole_set_and_removes_journal(tmp_path):
    core = _core(tmp_path)
    main = tmp_path / "main.py"
    sensor = tmp_path / "lib" / "sensor.py"
    sensor.parent.mkdir()
    # main got a half-written new version; sensor never made it across.
    main.write_bytes(b"half-new-main")
    (tmp_path / "main.py.bck").write_bytes(b"good-main")
    (tmp_path / "lib" / "sensor.py.bck").write_bytes(b"good-sensor")
    restore.write_journal(
        core, restore._STATE_COMMITTING, [str(main), str(sensor)]
    )

    assert restore.restore_all(core) == 2

    assert main.read_bytes() == b"good-main"
    assert sensor.read_bytes() == b"good-sensor"
    assert not (tmp_path / "main.py.bck").exists()
    assert not (tmp_path / "otampy-update.journal").exists()


def test_repair_committing_delegates_to_restore_all(tmp_path):
    core = _core(tmp_path)
    main = tmp_path / "main.py"
    sensor = tmp_path / "lib" / "sensor.py"
    sensor.parent.mkdir()
    main.write_bytes(b"half-new-main")
    (tmp_path / "main.py.bck").write_bytes(b"good-main")
    (tmp_path / "lib" / "sensor.py.bck").write_bytes(b"good-sensor")
    restore.write_journal(
        core, restore._STATE_COMMITTING, [str(main), str(sensor)]
    )

    restore.repair(core)

    assert main.read_bytes() == b"good-main"
    assert sensor.read_bytes() == b"good-sensor"
    assert restore.read_journal(core) == (0, restore._STATE_CONFIRMED, [])


def test_repair_trial_all_targets_present_does_not_write(tmp_path, monkeypatch):
    """F-07: a boot after a clean update must not rewrite the journal."""
    core = _core(tmp_path)
    main = tmp_path / "main.py"
    main.write_bytes(b"live-main")
    (tmp_path / "main.py.bck").write_bytes(b"old-main")
    restore.write_journal(core, 0, [str(main)])

    writes = []
    real_write = restore.write_journal
    monkeypatch.setattr(
        restore,
        "write_journal",
        lambda *a, **kw: writes.append(a) or real_write(*a, **kw),
    )

    restore.repair(core)

    assert writes == []
    assert restore.read_journal(core) == (0, restore._STATE_TRIAL, [str(main)])


def test_repair_finished_restores_only_missing_target(tmp_path):
    core = _core(tmp_path)
    main = tmp_path / "main.py"
    (tmp_path / "main.py.bck").write_bytes(b"good-main")
    restore.write_journal(core, 3, [str(main)])

    restore.repair(core)

    assert main.read_bytes() == b"good-main"
    # Counter written back unchanged.
    assert restore.read_journal(core) == (3, restore._STATE_TRIAL, [str(main)])


def test_repair_finished_is_noop_when_target_present(tmp_path):
    core = _core(tmp_path)
    main = tmp_path / "main.py"
    main.write_bytes(b"live-main")
    (tmp_path / "main.py.bck").write_bytes(b"old-main")
    restore.write_journal(core, 0, [str(main)])

    restore.repair(core)

    assert main.read_bytes() == b"live-main"


# =============================================================================
# confirm() and state()
# =============================================================================


def test_confirm_flips_trial_to_confirmed_and_keeps_paths(tmp_path):
    core = _core(tmp_path)
    paths = [str(tmp_path / "main.py")]
    restore.write_journal(core, 2, paths)

    assert restore.confirm(core) is True

    assert restore.read_journal(core) == (
        0,
        restore._STATE_CONFIRMED,
        paths,
    )


def test_confirm_is_idempotent(tmp_path):
    core = _core(tmp_path)
    paths = [str(tmp_path / "main.py")]
    restore.write_journal(core, 1, paths)

    assert restore.confirm(core) is True
    assert restore.confirm(core) is True
    assert restore.read_journal(core)[1] == restore._STATE_CONFIRMED


def test_confirm_with_no_journal_returns_true(tmp_path):
    core = _core(tmp_path)

    assert restore.confirm(core) is True


def test_confirm_during_commit_returns_false(tmp_path):
    core = _core(tmp_path)
    restore.write_journal(
        core, restore._STATE_COMMITTING, [str(tmp_path / "main.py")]
    )

    assert restore.confirm(core) is False
    assert restore.read_journal(core)[1] == restore._STATE_COMMITTING


def test_state_reports_trial_count(tmp_path):
    core = _core(tmp_path)
    restore.write_journal(core, 2, [str(tmp_path / "main.py")])

    assert restore.state(core) == ("trial", 2)


def test_state_reports_stable_when_confirmed_or_absent(tmp_path):
    core = _core(tmp_path)
    assert restore.state(core) == ("stable", 0)

    restore.write_journal(
        core, restore._STATE_CONFIRMED, [str(tmp_path / "main.py")]
    )
    assert restore.state(core) == ("stable", 0)


# =============================================================================
# trial() -- per-boot counter with reboot-triggered auto-rollback
# =============================================================================


def test_trial_counts_then_rolls_back_past_the_limit(tmp_path):
    core = _core(tmp_path, OTA_TRIAL_BOOTS=3)
    main = tmp_path / "main.py"
    main.write_bytes(b"candidate")
    (tmp_path / "main.py.bck").write_bytes(b"previous-good")
    restore.write_journal(core, 0, [str(main)])

    for expected in (1, 2, 3):
        assert restore.trial(core) is None
        assert restore.read_journal(core) == (
            expected,
            restore._STATE_TRIAL,
            [str(main)],
        )

    # The 4th boot: 4 > 3 -> restore the previous generation and signal reset.
    assert restore.trial(core) == restore._ROLLED_BACK
    assert main.read_bytes() == b"previous-good"
    assert not (tmp_path / "otampy-update.journal").exists()


def test_trial_is_a_noop_when_confirmed(tmp_path, monkeypatch):
    core = _core(tmp_path)
    paths = [str(tmp_path / "main.py")]
    restore.write_journal(core, restore._STATE_CONFIRMED, paths)

    writes = []
    monkeypatch.setattr(
        restore, "write_journal", lambda *a, **kw: writes.append(a)
    )

    assert restore.trial(core) is None
    assert writes == []


def test_trial_is_a_noop_with_no_journal(tmp_path):
    core = _core(tmp_path)

    assert restore.trial(core) is None
    assert not (tmp_path / "otampy-update.journal").exists()


def test_repair_no_journal_is_noop(tmp_path):
    core = _core(tmp_path)

    restore.repair(core)

    assert not (tmp_path / "otampy-update.journal").exists()


# =============================================================================
# rollback() -- the user-initiated revert primitive
# =============================================================================


def test_rollback_restores_trial_generation(tmp_path):
    core = _core(tmp_path)
    main = tmp_path / "main.py"
    sensor = tmp_path / "lib" / "sensor.py"
    sensor.parent.mkdir()
    main.write_bytes(b"new-main")
    sensor.write_bytes(b"new-sensor")
    (tmp_path / "main.py.bck").write_bytes(b"old-main")
    (tmp_path / "lib" / "sensor.py.bck").write_bytes(b"old-sensor")
    restore.write_journal(core, 1, [str(main), str(sensor)])

    assert restore.rollback(core) == 2

    assert main.read_bytes() == b"old-main"
    assert sensor.read_bytes() == b"old-sensor"
    assert not (tmp_path / "otampy-update.journal").exists()


def test_rollback_restores_confirmed_generation(tmp_path):
    """The point of the sub-task: a confirmed build is still revertible."""
    core = _core(tmp_path)
    main = tmp_path / "main.py"
    main.write_bytes(b"new-main")
    (tmp_path / "main.py.bck").write_bytes(b"old-main")
    restore.write_journal(core, restore._STATE_CONFIRMED, [str(main)])

    assert restore.rollback(core) == 1

    assert main.read_bytes() == b"old-main"
    assert not (tmp_path / "otampy-update.journal").exists()


def test_rollback_without_backups_leaves_the_journal_untouched(tmp_path):
    """Nothing to revert must not silently take a candidate off trial."""
    core = _core(tmp_path)
    main = tmp_path / "main.py"
    main.write_bytes(b"new-main")
    restore.write_journal(core, 2, [str(main)])
    before = (tmp_path / "otampy-update.journal").read_text()

    assert restore.rollback(core) == 0

    assert main.read_bytes() == b"new-main"
    assert (tmp_path / "otampy-update.journal").read_text() == before


def test_rollback_refuses_while_committing(tmp_path):
    core = _core(tmp_path)
    main = tmp_path / "main.py"
    main.write_bytes(b"half-new-main")
    (tmp_path / "main.py.bck").write_bytes(b"old-main")
    restore.write_journal(core, restore._STATE_COMMITTING, [str(main)])
    before = (tmp_path / "otampy-update.journal").read_text()

    assert restore.rollback(core) == restore._ROLLBACK_BUSY

    assert main.read_bytes() == b"half-new-main"
    assert (tmp_path / "main.py.bck").read_bytes() == b"old-main"
    assert (tmp_path / "otampy-update.journal").read_text() == before


def test_rollback_with_no_journal_returns_zero(tmp_path):
    core = _core(tmp_path)

    assert restore.rollback(core) == 0

    assert not (tmp_path / "otampy-update.journal").exists()
