"""Best-effort detection of a running WoW client (WoW rewrites SavedVariables on logout)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from wowtools.core.paths import is_wsl

WOW_EXECUTABLES = ("Wow.exe", "WowClassic.exe", "WowB.exe", "WowT.exe")
# Companion apps known to hold SavedVariables files open, which makes deleting them fail on Windows.
WTF_LOCKERS = ("RaiderIO.exe", "WeakAurasCompanion.exe")
# STD-1.9: listings are decoded as UTF-8, never with the locale; a byte that is not UTF-8 (tasklist writes in the OEM
# code page) becomes U+FFFD instead of raising. ValueError (UnicodeDecodeError) is still caught as a last resort.
_DECODE = {"encoding": "utf-8", "errors": "replace"}
_LIST_ERRORS = (OSError, subprocess.SubprocessError, ValueError)


def names_in_tasklist(output: str, names: tuple[str, ...] = WOW_EXECUTABLES) -> list[str]:
    """Parse `tasklist /FO CSV /NH` output."""
    lower = output.lower()
    return [exe for exe in names
            if re.search(rf'^"?{re.escape(exe.lower())}"?[\s,]', lower, re.MULTILINE)]


def running_wtf_lockers(**kwargs) -> list[str] | None:
    """Names of running companion apps that may lock WTF files, [] if none, None if we cannot tell."""
    return running_wow_executables(names=WTF_LOCKERS, **kwargs)


def running_wow_executables(*, use_tasklist: bool | None = None, runner=subprocess.run,
                            proc_root: Path = Path("/proc"),
                            names: tuple[str, ...] = WOW_EXECUTABLES) -> list[str] | None:
    """Names of running executables from `names` (WoW by default), [] if none, None if we cannot tell."""
    if use_tasklist is None:
        use_tasklist = os.name == "nt" or is_wsl()
    if use_tasklist:
        command = "tasklist" if os.name == "nt" else "tasklist.exe"
        try:
            proc = runner([command, "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=5, check=False,
                          **_DECODE)
        except _LIST_ERRORS:
            return None
        if proc.returncode != 0:
            return None
        return names_in_tasklist(proc.stdout or "", names)
    try:
        comm_files = list(proc_root.glob("[0-9]*/comm"))
    except OSError:
        return None
    running = set()
    for comm in comm_files:
        try:
            running.add(comm.read_text(encoding="utf-8", errors="replace").strip().lower())
        except OSError:
            continue
    # /proc/<pid>/comm is cut to 15 characters
    return [exe for exe in names if exe.lower()[:15] in running]


# --- flavor-aware check (spec §A.9) --------------------------------------------------------------
@dataclass(frozen=True)
class WowProcess:
    name: str
    path: str | None


_SEPARATORS = re.compile(r"[\\/]")
_CANONICAL = {exe.lower(): exe for exe in WOW_EXECUTABLES}
# The macOS client is an app bundle: <flavor>/World of Warcraft[ <variant>].app/Contents/MacOS/<same name>, where the
# variant is Classic, Beta, PTR and so on. Any "World of Warcraft ..." name counts (an unknown variant is safer seen
# than missed), except the known non-game processes: the Launcher (an old updater), helpers and crash reporters.
_MAC_CLIENT = re.compile(r"world of warcraft(?: .*)?")
_MAC_NOT_GAME = re.compile(r"\b(?:launcher|helper|crash|error|reporter|updater|agent)\b")
# No double quotes: they do not survive Windows command-line quoting reliably. '' is a literal ' in PowerShell.
# PowerShell writes in the OEM code page unless told otherwise: UTF-8 without a byte-order mark keeps a path with
# letters like é or ü intact (F-010).
_PS_QUERY = ("[Console]::OutputEncoding=New-Object Text.UTF8Encoding $false; "
             "Get-CimInstance Win32_Process -Filter '" +
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


def wow_name(basename: str) -> str | None:
    """The one name rule for every platform: the WoW client's display name for an executable's base name, or None.
    Matches the Windows executables (also under Wine) and the macOS bundle executables, ignoring case."""
    name = basename.strip()
    exe = _CANONICAL.get(name.lower())
    if exe is not None:
        return exe
    lower = name.lower()
    return name if _MAC_CLIENT.fullmatch(lower) and not _MAC_NOT_GAME.search(lower) else None


def _parse_powershell(output: str) -> list[WowProcess]:
    result = []
    for line in output.splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line:
            continue
        name, _, path = line.partition("|")
        exe = wow_name(name)
        if exe is not None:
            result.append(WowProcess(exe, path.strip() or None))
    return result


def _windows_processes(platform: str, runner) -> list[WowProcess] | None:
    command = "powershell" if platform == "windows" else "powershell.exe"
    try:
        proc = runner([command, "-NoProfile", "-NonInteractive", "-Command", _PS_QUERY],
                      capture_output=True, text=True, timeout=10, check=False, **_DECODE)
        if proc.returncode == 0:
            return _parse_powershell(proc.stdout or "")
    except _LIST_ERRORS:
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
        exe = wow_name(_SEPARATORS.split(first)[-1]) if first else None
        if exe is not None:
            result.append(WowProcess(exe, first))
    return result


def _bundle_path(path: str) -> str:
    """For a bundle's own executable (<X>.app/Contents/MacOS/<name>), the bundle's path, so its parent is the flavor
    folder. Any other path is kept whole: a Wine Wow.exe inside a wrapper .app sits in its own flavor folder."""
    parts = path.split("/")
    if (len(parts) >= 4 and parts[-4].lower().endswith(".app")
            and [part.lower() for part in parts[-3:-1]] == ["contents", "macos"]):
        return "/".join(parts[:-3])
    return path


def _parse_ps(output: str) -> list[WowProcess]:
    """Parse `ps -axww -o comm=`: one executable per line, a full path for apps on macOS, sometimes a bare name."""
    result = []
    for line in output.splitlines():
        command = line.strip()
        if not command:
            continue
        exe = wow_name(_SEPARATORS.split(command)[-1])
        if exe is not None:
            result.append(WowProcess(exe, _bundle_path(command) if _SEPARATORS.search(command) else None))
    return result


def _mac_processes(runner) -> list[WowProcess] | None:
    try:
        # -ww: without it macOS ps cuts the last column to the terminal width (79 with no tty), so a long bundle
        # path loses its executable name and a running WoW reads as "not running".
        proc = runner(["ps", "-axww", "-o", "comm="], capture_output=True, text=True, timeout=5, check=False,
                      stdin=subprocess.DEVNULL, **_DECODE)
    except _LIST_ERRORS:
        return None
    if proc.returncode != 0:
        return None
    return _parse_ps(proc.stdout or "")


def running_wow_processes(*, platform: str | None = None, runner=subprocess.run,
                          proc_root: Path = Path("/proc")) -> list[WowProcess] | None:
    """Running WoW processes with their executable paths where known; None if we cannot tell."""
    platform = platform or _detect_platform()
    if platform in ("windows", "wsl"):
        return _windows_processes(platform, runner)
    if platform == "linux":
        return _linux_processes(proc_root)
    if platform == "mac":
        return _mac_processes(runner)
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
    """The check the review screen runs: display strings for WoW processes of this flavor, or of any of several
    flavors (a list). The processes are listed once per check, whatever the number of flavors."""
    flavors = flavor if isinstance(flavor, (list, tuple)) else [flavor]
    folders = [getattr(f, "folder", f) for f in flavors]

    def check() -> list[str] | None:
        processes = lister()
        if processes is None:
            return None
        unknown = [proc for proc in processes if proc.path is None]
        matching: list[WowProcess] = []
        for folder in folders:
            matching += processes_for_flavor(processes, folder)[0]
        labels = [proc.name for proc in matching] + [f"{proc.name} (flavor unknown)" for proc in unknown]
        return list(dict.fromkeys(labels))
    return check
