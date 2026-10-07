"""Run-in-progress markers: the small JSON file a tool writes before it changes files and removes when the run
ends, so the next start can tell a run was cut short (the WTF Cleaner's clean-in-progress.json, the Ace3 Profile
Manager's edit-in-progress.json). UI-free.

Only the file handling is shared: each tool keeps its own Marker fields and checks them when reading. Path values
are written with to_stored() (Windows form for a path on a Windows drive, STD-4.4); the tool reads them back with
to_native(), which leaves an older marker's str() path as it is."""
from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.paths import to_stored


def write_marker(folder: Path, name: str, data: dict[str, Any]) -> None:
    """Write folder/name atomically (a reader sees the old marker or the new one), making folder if needed."""
    stored = {key: to_stored(value) if isinstance(value, Path) else value for key, value in data.items()}
    folder.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(folder / name, json.dumps(stored, indent=2, ensure_ascii=False).encode("utf-8"))


def read_marker(folder: Path | None, name: str) -> dict[str, Any] | None:
    """folder/name as a dict, or None when there is none or it cannot be read (not JSON, not an object, bad
    bytes). Never raises: an unreadable marker is no usable marker. The tool checks the fields."""
    if folder is None:
        return None
    try:
        data = json.loads((folder / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - any unreadable marker means "no usable marker"
        return None
    return data if isinstance(data, dict) else None


CLEAR_WAITS = (0.05, 0.1, 0.2)  # seconds between tries: a virus scanner or OneDrive may hold a new file briefly


def clear_marker(folder: Path, name: str, waits: Sequence[float] = CLEAR_WAITS) -> bool:
    """Remove folder/name. True when it is gone (or never was); False when it is still there after a retry per
    wait. Never raises: the caller reports a marker left behind (the next scan would offer the run as unfinished)."""
    path = folder / name
    for wait in (*waits, None):
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if wait is None:
                return False
            time.sleep(wait)
    return False  # pragma: no cover - the loop always returns
