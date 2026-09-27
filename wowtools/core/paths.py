"""Path handling that lets one config work from both Windows and WSL.

Paths are stored in Windows form (G:\\Games\\...) whenever they point at a Windows drive,
and converted to the native form (/mnt/g/Games/...) when running under WSL.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

_WIN_DRIVE = re.compile(r"^([A-Za-z]):(?:[\\/](.*))?$")
_WSL_MOUNT = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$")


@functools.lru_cache(maxsize=1)
def is_wsl() -> bool:
    try:
        text = Path("/proc/version").read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return "microsoft" in text or "wsl" in text


def win_to_wsl(value: str) -> str | None:
    match = _WIN_DRIVE.match(value.strip())
    if not match:
        return None
    drive = match.group(1).lower()
    rest = (match.group(2) or "").replace("\\", "/").strip("/")
    return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"


def wsl_to_win(value: str) -> str | None:
    text = value.strip()
    if text != "/":
        text = text.rstrip("/")
    match = _WSL_MOUNT.match(text)
    if not match:
        return None
    drive = match.group(1).upper()
    rest = (match.group(2) or "").strip("/")
    return f"{drive}:\\" + rest.replace("/", "\\")


def to_native(value: str, *, wsl: bool | None = None) -> Path:
    """Turn a stored path into one this process can open."""
    if is_wsl() if wsl is None else wsl:
        converted = win_to_wsl(value)
        if converted:
            return Path(converted)
    return Path(value.strip())


def to_stored(value: str | Path, *, wsl: bool | None = None) -> str:
    """Turn a native path into the form written to wow-tools.cfg."""
    text = str(value)
    if is_wsl() if wsl is None else wsl:
        converted = wsl_to_win(text)
        if converted:
            return converted
    return text
