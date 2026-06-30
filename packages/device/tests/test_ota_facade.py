from unittest.mock import patch

import shared
from device_otampy.ota import OTA


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
