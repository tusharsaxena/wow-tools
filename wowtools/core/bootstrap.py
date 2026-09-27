"""Interpreter check and vendor/ path setup. Stdlib only: runs before any third-party import."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDOR_DIR = REPO_ROOT / "vendor"
MIN_PYTHON = (3, 10)


def check_python(version_info: tuple[int, ...] | None = None) -> str | None:
    """Return a readable error if this Python is too old, else None."""
    major, minor = tuple(version_info or sys.version_info)[:2]
    if (major, minor) < MIN_PYTHON:
        return (f"Ka0s WoW Tools needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer "
                f"(found {major}.{minor}).")
    return None


def add_vendor_path(vendor_dir: Path = VENDOR_DIR) -> None:
    """Put vendor/ first on sys.path so bundled libraries win over anything installed."""
    path = str(vendor_dir)
    if path not in sys.path:
        sys.path.insert(0, path)
