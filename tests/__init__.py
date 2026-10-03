"""Test package: make vendored libraries importable, exactly like the launcher does."""
from __future__ import annotations

from wowtools.core.bootstrap import add_vendor_path

add_vendor_path()
