import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

from device_otampy.ota import OTA

import shared


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
    try:
        spec.loader.exec_module(package)

        mode_modules = {
            f"{package_name}.boot",
            f"{package_name}.manager",
        }
        loaded_mode_modules = mode_modules.intersection(sys.modules)
        assert loaded_mode_modules == set()
    finally:
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

    with patch("device_otampy.boot.run") as mock_boot_run, patch(
        "device_otampy.manager.poll"
    ) as mock_manager_poll:
        ota.boot()
        mock_boot_run.assert_called_once_with(ota._core, None)

        ota.poll()
        mock_manager_poll.assert_called_once_with(ota._core, None)
