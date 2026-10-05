"""Run-in-progress markers: the small JSON file a tool writes before it changes files and removes when the run
ends, so the next start can tell a run was cut short (the WTF Cleaner's clean-in-progress.json, the Ace3 Profile
Manager's edit-in-progress.json). UI-free.

Only the file handling is shared: each tool keeps its own Marker fields and checks them when reading. Path values
are written with str() (the format the markers on disk already use)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wowtools.core.fsutil import atomic_write_bytes, remove_quietly


def write_marker(folder: Path, name: str, data: dict[str, Any]) -> None:
    """Write folder/name atomically (a reader sees the old marker or the new one), making folder if needed."""
    stored = {key: str(value) if isinstance(value, Path) else value for key, value in data.items()}
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


def clear_marker(folder: Path, name: str) -> None:
    remove_quietly(folder / name)
