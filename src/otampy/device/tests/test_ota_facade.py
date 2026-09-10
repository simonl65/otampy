import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import shared
from device_otampy.ota import OTA


def test_package_import_does_not_eagerly_load_operating_modes():
    package_name = "lazy_device_otampy"
    package_path = Path(__file__).resolve().parents[1] / "lib" / "otampy"
    spec = importlib.util.spec_from_file_location(
        package_name,
        package_path / "__init__.py",
        submodule_search_locations=[str(package_path)],
    )
    assert spec is not None
    assert spec.loader is not None

    package = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = package
    urst_module = sys.modules.pop("urst")
    try:
        spec.loader.exec_module(package)

        mode_modules = {
            f"{package_name}.boot",
            f"{package_name}.manager",
        }
        loaded_mode_modules = mode_modules.intersection(sys.modules)
        assert loaded_mode_modules == set()
        assert "urst" not in sys.modules
    finally:
        sys.modules["urst"] = urst_module
        for module_name in tuple(sys.modules):
            if module_name == package_name or module_name.startswith(
                package_name + "."
            ):
                del sys.modules[module_name]


def test_boot_releases_boot_module_and_can_run_again():
    uart = shared.FakeUART()
    ota = OTA(uart)
    package = sys.modules["device_otampy"]

    for _ in range(2):
        with patch("device_otampy.boot.run") as mock_boot_run:
            ota.boot()
            mock_boot_run.assert_called_once_with(ota._core, None)

        assert "device_otampy.boot" not in sys.modules
        assert not hasattr(package, "boot")


def test_boot_teardown_survives_micropython_delattr_keyerror():
    """MicroPython's ``delattr`` raises ``KeyError`` (not ``AttributeError``)
    when the attribute is absent -- as ``authgate`` is on every boot that did
    not configure auth. The teardown must swallow that, or ``boot()`` raises
    and ``boot.py`` crashes on every boot, stranding the device (F-09).
    """
    import builtins

    real_delattr = builtins.delattr

    def micropython_delattr(obj, name):
        if not hasattr(obj, name):
            raise KeyError(name)
        return real_delattr(obj, name)

    uart = shared.FakeUART()
    ota = OTA(uart)
    package = sys.modules["device_otampy"]

    # The teardown legitimately drops these from sys.modules; restore them so
    # test ordering does not leave later tests importing a stale `boot`.
    released = ("boot", "restore", "authgate")
    saved = {
        name: sys.modules.get("device_otampy." + name) for name in released
    }
    try:
        with (
            patch("device_otampy.boot.run"),
            patch("builtins.delattr", side_effect=micropython_delattr),
        ):
            ota.boot()

        assert "device_otampy.authgate" not in sys.modules
    finally:
        for name, module in saved.items():
            if module is not None:
                sys.modules["device_otampy." + name] = module
                setattr(package, name, module)


def test_boot_release_does_not_require_package_global():
    uart = shared.FakeUART()
    ota = OTA(uart)
    ota_module = sys.modules["device_otampy.ota"]
    package_name = ota_module.__package__
    del ota_module.__package__

    try:
        with patch("device_otampy.boot.run"):
            ota.boot()
    finally:
        ota_module.__package__ = package_name

    assert "device_otampy.boot" not in sys.modules


def test_facade_delegates_to_boot_and_manager():
    uart = shared.FakeUART()
    ota = OTA(uart)

    with (
        patch("device_otampy.boot.run") as mock_boot_run,
        patch("device_otampy.manager.poll") as mock_manager_poll,
    ):
        ota.boot()
        mock_boot_run.assert_called_once_with(ota._core, None)

        ota.poll()
        mock_manager_poll.assert_called_once_with(
            ota._core, None, heartbeat=None
        )


def test_recover_delegates_to_restore_repair():
    """F-06: main.py calls recover() so an interrupted commit that left boot.py
    absent (and so never ran boot.run()'s repair()) still self-heals."""
    uart = shared.FakeUART()
    ota = OTA(uart)

    with patch("device_otampy.restore.repair") as mock_repair:
        ota.recover()

    mock_repair.assert_called_once_with(ota._core)


def test_confirm_delegates_to_restore_confirm():
    """The app calls ota.confirm() after its own health check to take the
    running candidate off trial."""
    uart = shared.FakeUART()
    ota = OTA(uart)

    with patch("device_otampy.restore.confirm", return_value=True) as mock:
        assert ota.confirm() is True

    mock.assert_called_once_with(ota._core)


def test_recover_clears_the_stale_update_flag(tmp_path):
    """The interrupted boot.run() never removed the flag; recover() must, so
    the next boot skips the dead update loop."""
    flag = tmp_path / "update_requested.flag"
    flag.touch()
    uart = shared.FakeUART()
    ota = OTA(uart, config={"UPDATE_REQUEST_FLAG_FILE": str(flag)})

    with patch("device_otampy.restore.repair"):
        ota.recover()

    assert not flag.exists()


def test_recover_survives_a_missing_flag_file(tmp_path):
    uart = shared.FakeUART()
    ota = OTA(
        uart,
        config={"UPDATE_REQUEST_FLAG_FILE": str(tmp_path / "absent.flag")},
    )

    with patch("device_otampy.restore.repair"):
        ota.recover()  # must not raise


def test_poll_passes_heartbeat_through_to_manager():
    uart = shared.FakeUART()
    ota = OTA(uart)
    heartbeat = object()

    with patch("device_otampy.manager.poll") as mock_manager_poll:
        ota.poll(heartbeat=heartbeat)
        mock_manager_poll.assert_called_once_with(
            ota._core, None, heartbeat=heartbeat
        )


# =============================================================================
# Clearing the boot marker
#
# Reaching poll() is the only proof the runtime OTA surface is alive, so this
# -- not recover(), which runs before the application has proved anything --
# is where the marker written by boot.run() is cleared. Once per process.
# See docs/development/failsafe-update-window-reachability-spec.md.
# =============================================================================


def _mark_config(tmp_path, **extra):
    config = {"OTA_BOOT_MARK_FILE": str(tmp_path / "otampy-boot.mark")}
    config.update(extra)
    return config


def test_first_poll_clears_the_boot_marker(tmp_path):
    mark = tmp_path / "otampy-boot.mark"
    mark.write_text("1")
    ota = OTA(shared.FakeUART(), config=_mark_config(tmp_path))

    with patch("device_otampy.manager.poll"):
        ota.poll()

    assert not mark.exists()


def test_later_polls_do_no_filesystem_work(tmp_path):
    """The hot path pays one boolean check per call, not a syscall."""
    mark = tmp_path / "otampy-boot.mark"
    mark.write_text("1")
    ota = OTA(shared.FakeUART(), config=_mark_config(tmp_path))

    with patch("device_otampy.manager.poll"):
        ota.poll()
        with patch("os.remove") as mock_remove:
            ota.poll()
            ota.poll()

    mock_remove.assert_not_called()


def test_poll_survives_a_marker_remove_failure_and_still_delegates(tmp_path):
    """A read-only filesystem must never stop the application polling.

    The flag is set regardless of outcome, so one failing remove is not
    repaid on every poll() for the life of the process.
    """
    ota = OTA(shared.FakeUART(), config=_mark_config(tmp_path))

    with (
        patch("os.remove", side_effect=OSError(30, "Read-only file system")),
        patch("device_otampy.manager.poll") as mock_manager_poll,
    ):
        ota.poll()
        mock_manager_poll.assert_called_once_with(
            ota._core, None, heartbeat=None
        )

        with patch("os.remove") as mock_remove:
            ota.poll()

    mock_remove.assert_not_called()


def test_poll_does_no_filesystem_work_when_recovery_window_disabled(tmp_path):
    """OTA_BOOT_RECOVERY_LISTEN_MS = 0 switches the marker off at both ends."""
    mark = tmp_path / "otampy-boot.mark"
    mark.write_text("1")
    config = _mark_config(tmp_path, OTA_BOOT_RECOVERY_LISTEN_MS=0)
    ota = OTA(shared.FakeUART(), config=config)

    with (
        patch("os.remove") as mock_remove,
        patch("device_otampy.manager.poll"),
    ):
        ota.poll()

    mock_remove.assert_not_called()
    assert mark.exists()
