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


def test_repair_committing_restores_whole_set(tmp_path):
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

    restore.repair(core)

    assert main.read_bytes() == b"good-main"
    assert sensor.read_bytes() == b"good-sensor"
    assert restore.read_journal(core) == (
        0,
        restore._STATE_TRIAL,
        [str(main), str(sensor)],
    )


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


def test_repair_no_journal_is_noop(tmp_path):
    core = _core(tmp_path)

    restore.repair(core)

    assert not (tmp_path / "otampy-update.journal").exists()
