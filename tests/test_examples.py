"""Guards the shipped device scaffolds — see
docs/development/channel-mux-scaffold-spec.md.

The default ``examples/`` set is direct mode (OTA owns the raw UART); the
``examples/shared-uart/`` set is the opt-in ``SerialMux`` pattern. Both must
stay syntactically valid MicroPython-parseable Python.
"""

import ast
from pathlib import Path

import pytest

EXAMPLES = (
    Path(__file__).parent.parent / "src" / "otampy" / "device" / "examples"
)
SHARED_UART = EXAMPLES / "shared-uart"

DEFAULT_SCRIPTS = [EXAMPLES / "boot.py", EXAMPLES / "main.py"]
SHARED_SCRIPTS = [SHARED_UART / "boot.py", SHARED_UART / "main.py"]
ALL_FILES = list(EXAMPLES.glob("*.py")) + list(SHARED_UART.glob("*.py"))


@pytest.mark.parametrize(
    "path", ALL_FILES, ids=lambda p: str(p.relative_to(EXAMPLES))
)
def test_example_file_parses(path):
    ast.parse(path.read_text(), filename=str(path))


@pytest.mark.parametrize("path", DEFAULT_SCRIPTS, ids=lambda p: p.name)
def test_default_scaffold_is_direct_mode(path):
    text = path.read_text()
    assert "SerialMux" not in text
    assert "mux." not in text


@pytest.mark.parametrize(
    "path",
    [EXAMPLES / "main.py", SHARED_UART / "main.py"],
    ids=lambda p: str(p.relative_to(EXAMPLES)),
)
def test_main_scaffold_calls_recover(path):
    """F-06: every main.py must run recover() so a lost boot.py self-heals."""
    assert ".recover()" in path.read_text()


@pytest.mark.parametrize("path", SHARED_SCRIPTS, ids=lambda p: p.name)
def test_shared_uart_scaffold_uses_serialmux(path):
    text = path.read_text()
    assert "SerialMux" in text
    assert "mux.ota_port" in text


def test_shared_uart_set_is_complete():
    for name in ("boot.py", "main.py", "configota.example.py"):
        assert (SHARED_UART / name).is_file()
