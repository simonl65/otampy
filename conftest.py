"""Add project source paths to sys.path for pytest discovery.

This root-level conftest is used for all test locations, including
packages/cli/tests and packages/device/tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "packages" / "cli" / "src"))
sys.path.insert(0, str(root / "packages" / "device" / "lib"))
sys.path.insert(0, str(root))
