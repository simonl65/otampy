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
    core = _core(tmp_path)
    paths = [str(tmp_path / "main.py"), str(tmp_path / "lib" / "sensor.py")]

    assert restore.write_journal(core, 0, paths) is True

    assert restore.read_journal(core) == (0, False, paths)


def test_journal_round_trip_in_progress(tmp_path):
    core = _core(tmp_path)
    paths = [str(tmp_path / "main.py")]

    assert restore.write_journal(core, restore._COMMIT_IN_PROGRESS, paths)

    assert restore.read_journal(core) == (0, True, paths)


def test_journal_missing_file_reads_empty(tmp_path):
    core = _core(tmp_path)

    assert restore.read_journal(core) == (0, False, [])


def test_journal_empty_file_reads_empty(tmp_path):
    core = _core(tmp_path)
    (tmp_path / "otampy-update.journal").write_text("")

    assert restore.read_journal(core) == (0, False, [])


def test_journal_malformed_first_line_is_in_progress(tmp_path):
    """Fail safe: an unreadable counter means "restore everything"."""
    core = _core(tmp_path)
    (tmp_path / "otampy-update.journal").write_text("garbage\n/main.py\n")

    assert restore.read_journal(core) == (0, True, ["/main.py"])


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
