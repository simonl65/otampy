"""
Test the OTA runtime process (main.py)
"""

import pytest
from shared import FakeLogger, FakeUART, LoadOTAModule


@pytest.mark.skip(
    "TODO: Implement test_otamanager_recognises_all_valid_commands"
)
def test_otamanager_recognises_all_valid_commands(monkeypatch):
    """Expect all commands to be recognised andf handled."""
