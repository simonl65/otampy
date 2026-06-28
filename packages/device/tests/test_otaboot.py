"""
Test the OTA boot process (boot.py)
"""

import pytest
from shared import FakeLogger, FakeUART, LoadOTAModule


@pytest.mark.skip("TODO: Implement test_for_update_request_flag_file_found")
def test_for_update_request_flag_file_found(monkeypatch, tmp_path):
    """Expect to initiate upload process and see URST 'READY_TO_RECEIVE' message sent."""
    pass


@pytest.mark.skip("TODO: Implement test_for_update_request_flag_file_missing")
def test_for_update_request_flag_file_missing(monkeypatch, tmp_path):
    pass
