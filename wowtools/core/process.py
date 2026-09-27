"""Best-effort detection of a running WoW client (WoW rewrites SavedVariables on logout)."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from wowtools.core.paths import is_wsl

WOW_EXECUTABLES = ("Wow.exe", "WowClassic.exe", "WowB.exe", "WowT.exe")


def names_in_tasklist(output: str) -> list[str]:
    """Parse `tasklist /FO CSV /NH` output."""
    lower = output.lower()
    return [exe for exe in WOW_EXECUTABLES
            if re.search(rf'^"?{re.escape(exe.lower())}"?[\s,]', lower, re.MULTILINE)]


def running_wow_executables(*, use_tasklist: bool | None = None, runner=subprocess.run,
                            proc_root: Path = Path("/proc")) -> list[str] | None:
    """Names of running WoW executables, [] if none, None if we cannot tell."""
    if use_tasklist is None:
        use_tasklist = os.name == "nt" or is_wsl()
    if use_tasklist:
        command = "tasklist" if os.name == "nt" else "tasklist.exe"
        try:
            proc = runner([command, "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        return names_in_tasklist(proc.stdout or "")
    try:
        comm_files = list(proc_root.glob("[0-9]*/comm"))
    except OSError:
        return None
    names = set()
    for comm in comm_files:
        try:
            names.add(comm.read_text(encoding="utf-8", errors="replace").strip().lower())
        except OSError:
            continue
    return [exe for exe in WOW_EXECUTABLES if exe.lower() in names]
