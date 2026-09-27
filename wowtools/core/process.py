"""Best-effort detection of a running WoW client (WoW rewrites SavedVariables on logout)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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


# --- flavor-aware check (spec §A.9) --------------------------------------------------------------
@dataclass(frozen=True)
class WowProcess:
    name: str
    path: str | None


_SEPARATORS = re.compile(r"[\\/]")
_CANONICAL = {exe.lower(): exe for exe in WOW_EXECUTABLES}
# No double quotes: they do not survive Windows command-line quoting reliably. '' is a literal ' in PowerShell.
_PS_QUERY = ("Get-CimInstance Win32_Process -Filter '" +
             " OR ".join(f"Name=''{exe}''" for exe in WOW_EXECUTABLES) +
             "' | ForEach-Object { $_.Name + '|' + $_.ExecutablePath }")


def _detect_platform() -> str:
    if os.name == "nt":
        return "windows"
    if is_wsl():
        return "wsl"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def _parse_powershell(output: str) -> list[WowProcess]:
    result = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        name, _, path = line.partition("|")
        exe = _CANONICAL.get(name.strip().lower())
        if exe is not None:
            result.append(WowProcess(exe, path.strip() or None))
    return result


def _windows_processes(platform: str, runner) -> list[WowProcess] | None:
    command = "powershell" if platform == "windows" else "powershell.exe"
    try:
        proc = runner([command, "-NoProfile", "-NonInteractive", "-Command", _PS_QUERY],
                      capture_output=True, text=True, timeout=10, check=False)
        if proc.returncode == 0:
            return _parse_powershell(proc.stdout or "")
    except (OSError, subprocess.SubprocessError):
        pass
    names = running_wow_executables(use_tasklist=True, runner=runner)
    return None if names is None else [WowProcess(name, None) for name in names]


def _linux_processes(proc_root: Path) -> list[WowProcess] | None:
    try:
        cmdlines = list(proc_root.glob("[0-9]*/cmdline"))
    except OSError:
        return None
    result = []
    for cmdline in cmdlines:
        try:
            raw = cmdline.read_bytes()
        except OSError:
            continue
        first = raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")
        exe = _CANONICAL.get(_SEPARATORS.split(first)[-1].lower()) if first else None
        if exe is not None:
            result.append(WowProcess(exe, first))
    return result


def running_wow_processes(*, platform: str | None = None, runner=subprocess.run,
                          proc_root: Path = Path("/proc")) -> list[WowProcess] | None:
    """Running WoW processes with their executable paths where known; None if we cannot tell."""
    platform = platform or _detect_platform()
    if platform in ("windows", "wsl"):
        return _windows_processes(platform, runner)
    if platform == "linux":
        return _linux_processes(proc_root)
    return None


def processes_for_flavor(processes: list[WowProcess],
                         flavor_folder: str) -> tuple[list[WowProcess], list[WowProcess]]:
    """(processes whose executable sits in the flavor folder, processes whose path is unknown)."""
    target = flavor_folder.lower()
    matching, unknown = [], []
    for proc in processes:
        if proc.path is None:
            unknown.append(proc)
            continue
        parts = [part for part in _SEPARATORS.split(proc.path) if part]
        if len(parts) >= 2 and parts[-2].lower() == target:
            matching.append(proc)
    return matching, unknown


def wow_check_for(flavor, *, lister: Callable[[], list[WowProcess] | None] = running_wow_processes
                  ) -> Callable[[], list[str] | None]:
    """The check the review screen and CLI run: display strings for WoW processes of this flavor."""
    folder = getattr(flavor, "folder", flavor)

    def check() -> list[str] | None:
        processes = lister()
        if processes is None:
            return None
        matching, unknown = processes_for_flavor(processes, folder)
        labels = [proc.name for proc in matching] + [f"{proc.name} (flavor unknown)" for proc in unknown]
        return list(dict.fromkeys(labels))
    return check
