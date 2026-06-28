"""Add the repo root and device package lib path to sys.path so that tests can import project modules."""

from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "packages" / "cli" / "src"))
sys.path.insert(0, str(root / "packages" / "device" / "lib"))
