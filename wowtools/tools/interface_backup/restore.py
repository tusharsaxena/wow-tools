"""Restore a flavor's Interface and/or WTF folders from a backup: exact replace through a staging folder and a
folder swap, after a pre-restore safety backup, with a run journal for Undo. UI-free."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.backup import MANIFEST_NAME
from wowtools.core.install import Flavor
from wowtools.tools.interface_backup.scanner import PARTS, FlavorScan

NEWER_SLACK = 2.0  # zip timestamps have 2-second steps
KINDS = ("backup", "pre-restore")
_DRIVE = re.compile(r"^[A-Za-z]:")
_FLAVOR_FOLDER = re.compile(r"_[A-Za-z0-9_]+_")  # fullmatch: no trailing newline
_BAD_CHARS = frozenset('<>:"|?*\x00')  # refused everywhere: Windows cannot write them, NUL nowhere can
# Windows only: control characters, and device names ("CON", "nul.lua") that open the device, not a file. On POSIX
# these are ordinary names (a character called Aux gets an "Aux" folder), so a backup made there must restore there.
_WINDOWS_BAD_CHARS = frozenset(chr(c) for c in range(1, 32))
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL"} | {f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)})
# Reading a zip: a damaged file, an unsupported compression method or an encrypted entry.
_ZIP_ERRORS = (OSError, zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, ValueError)


def _case_key(name: str) -> str:
    """A name as Windows compares it: per-character lower case, not casefold()'s full folding ("ß" is not "ss" on
    NTFS, so "Straße.lua" and "STRASSE.lua" are two files)."""
    return name.lower()


class RestoreError(Exception):
    """A backup cannot be restored (unreadable, not ours, unsafe names), or a restore cannot start. Nothing was
    changed."""


def _unsafe(name: str) -> RestoreError:
    return RestoreError(f"unsafe entry name in the backup: {name!r}")


def _bad_component(part: str, windows: bool) -> bool:
    if part in ("", ".", "..") or part != part.rstrip(". ") or _BAD_CHARS & set(part):
        return True
    return windows and (bool(_WINDOWS_BAD_CHARS & set(part)) or part.split(".")[0].upper() in _RESERVED)


def split_entry(name: str, *, windows: bool | None = None) -> tuple[str, str]:
    """('Interface', 'AddOns/A/a.lua') for a safe zip entry name; RestoreError for anything that could land
    outside the part folder, or be written as something else, on Windows or POSIX: absolute, a drive, a backslash,
    `.`/`..`, an empty component (a folder entry), `:` (alternate data stream), a trailing dot or space, `<>"|?*`
    or NUL, or a first part other than Interface or WTF (case counts). On Windows (`windows`, default: running
    there) control characters and device names (`CON`, `nul.lua`, `COM1`) are refused too."""
    if windows is None:
        windows = os.name == "nt"
    if not name or "\\" in name or name.startswith("/") or _DRIVE.match(name):
        raise _unsafe(name)
    pieces = name.split("/")
    if len(pieces) < 2 or pieces[0] not in PARTS or any(_bad_component(p, windows) for p in pieces[1:]):
        raise _unsafe(name)
    return pieces[0], "/".join(pieces[1:])


@dataclass
class BackupContents:
    path: Path
    kind: str  # backup | pre-restore
    flavor_short: str
    flavor_folder: str
    created: str
    parts: tuple[str, ...]  # the parts the backup holds (an empty one included): only these can be restored
    files: dict[str, dict[str, tuple[int, float]]]  # part -> rel -> (size, mtime); every part of PARTS is a key
    links: list[str] = field(default_factory=list)  # "<Part>/<rel>" links skipped when the backup was made

    def sizes(self, parts: tuple[str, ...] | None = None) -> dict[str, int]:
        """Entry name -> size, for verify_backup (all parts when `parts` is None; none for an empty tuple)."""
        chosen = PARTS if parts is None else parts
        return {f"{part}/{rel}": size for part in chosen for rel, (size, _) in self.files[part].items()}


def _check_names(names: list[str]) -> None:
    """Every entry safe, no two the same (ignoring case), and no file where another entry needs a folder."""
    seen: set[str] = set()
    for name in names:
        split_entry(name)
        key = _case_key(name)
        if key in seen:
            raise RestoreError(f"the backup has two entries for the same file (case ignored): {name}")
        seen.add(key)
    for key in seen:
        pieces = key.split("/")
        for depth in range(2, len(pieces)):
            if "/".join(pieces[:depth]) in seen:
                raise RestoreError(f"the backup has a file where it also needs a folder: {'/'.join(pieces[:depth])}")


def open_backup(path: Path) -> BackupContents:
    """Read a backup's manifest and check every entry name. Reads no file data but the manifest (verification is
    the restore's first stage). Raises RestoreError."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            try:
                raw = zf.read(MANIFEST_NAME)
            except KeyError:
                raise RestoreError("not an Interface Backup zip (it has no manifest.json)") from None
    except _ZIP_ERRORS as exc:
        raise RestoreError(f"the backup cannot be read: {exc}") from exc
    try:
        manifest = json.loads(raw)
    except ValueError as exc:  # UnicodeDecodeError included
        raise RestoreError(f"the backup's manifest is damaged: {exc}") from exc
    try:
        if manifest["version"] != 1 or manifest["kind"] not in KINDS:
            raise RestoreError("not an Interface Backup zip (unknown manifest)")
        folder = str(manifest["flavor_folder"])
        if not _FLAVOR_FOLDER.fullmatch(folder):
            raise RestoreError(f"the backup names an invalid flavor folder: {folder!r}")
        names = [info.filename for info in infos if info.filename != MANIFEST_NAME]
        _check_names(names)
        sizes = {info.filename: info.file_size for info in infos}
        listed = {str(f["path"]): float(f["mtime"]) for f in manifest["files"]}
        if len(listed) != len(manifest["files"]) or set(listed) != set(names):
            raise RestoreError("the backup's manifest does not match its contents")
        # Only non-finite times are refused: a pre-1970 file (negative st_mtime) is ordinary input to write_zip.
        # Task 6 leaves the extraction time on a file whose time os.utime cannot set.
        if not all(math.isfinite(mtime) for mtime in listed.values()):
            raise RestoreError("the backup's manifest is damaged: a file time is not a valid date")
        if not isinstance(manifest["parts"], list):
            raise RestoreError("the backup's manifest is damaged: parts is not a list")
        parts = tuple(p for p in PARTS if p in manifest["parts"])
        files: dict[str, dict[str, tuple[int, float]]] = {part: {} for part in PARTS}
        for name, mtime in listed.items():
            part, rel = split_entry(name)
            if part not in parts:
                raise RestoreError(f"the backup's manifest does not claim the {part} folder it holds files for")
            files[part][rel] = (sizes[name], mtime)
        return BackupContents(Path(path), str(manifest["kind"]), str(manifest["flavor"]), folder,
                              str(manifest.get("created", "")), parts, files,
                              [str(link) for link in manifest.get("links", [])])
    except (KeyError, TypeError, ValueError) as exc:
        raise RestoreError(f"the backup's manifest is damaged: {exc!r}") from exc


@dataclass
class RestorePlan:
    contents: BackupContents
    flavor: Flavor
    parts: tuple[str, ...]
    removed: list[tuple[str, str]]  # (part, rel) on disk now, not in the backup: lost by the restore
    newer: list[tuple[str, str]]  # on disk now and more than NEWER_SLACK seconds newer than the backup's copy
    links_kept: list[tuple[str, str]]
    links_removed: list[tuple[str, str]]  # the backup has files there: the link (never its target) goes
    bytes_needed: int  # bytes the chosen parts take once extracted
    free_bytes: int | None  # on the flavor's drive; None when unknown
    leftovers: list[Path]  # from an interrupted restore: a new restore of this flavor is blocked
    unreadable: list[str] = field(default_factory=list)  # chosen parts' scan errors: what is there is lost unlisted

    @property
    def low_space(self) -> bool:
        return self.free_bytes is not None and self.bytes_needed > self.free_bytes


def _free_space(path: Path, disk_usage: Callable) -> int | None:
    try:
        return int(disk_usage(path).free)
    except OSError:
        return None


def plan_restore(contents: BackupContents, scan: FlavorScan, parts: tuple[str, ...], *,
                 disk_usage: Callable = shutil.disk_usage) -> RestorePlan:
    """Compare the backup's chosen parts with what is on disk now (a scan with stats, for `newer`). Paths compare
    ignoring case, as Windows does. Raises RestoreError for no parts or an unknown part name, a backup of another
    flavor, a part the backup does not hold or a part folder that is itself a link."""
    unknown = [p for p in parts if p not in PARTS]
    if unknown or not parts:
        raise RestoreError(f"no such part to restore: {unknown!r}" if unknown else "no part chosen to restore")
    if _case_key(contents.flavor_folder) != _case_key(scan.flavor.folder):
        raise RestoreError(f"the backup is of {contents.flavor_folder}, not {scan.flavor.folder}: a backup restores "
                           "only into its own flavor")
    removed: list[tuple[str, str]] = []
    newer: list[tuple[str, str]] = []
    kept: list[tuple[str, str]] = []
    dropped: list[tuple[str, str]] = []
    unreadable: list[str] = []
    needed = 0
    chosen = tuple(p for p in PARTS if p in parts)
    for part in chosen:
        if part not in contents.parts:
            raise RestoreError(f"the backup has no {part} folder")
        live = scan.parts[part]
        if live.linked:
            raise RestoreError(f"{part} is a link to another folder; restore it by hand")
        unreadable.extend(live.errors)
        backup_files = {_case_key(rel): (size, mtime) for rel, (size, mtime) in contents.files[part].items()}
        folders = {"/".join(rel.split("/")[:i]) for rel in backup_files for i in range(1, rel.count("/") + 1)}
        needed += sum(size for size, _ in backup_files.values())
        for info in live.files:
            match = backup_files.get(_case_key(info.rel))
            if match is None:
                removed.append((part, info.rel))
            elif info.mtime is not None and info.mtime > match[1] + NEWER_SLACK:
                newer.append((part, info.rel))
        for link in live.links:
            key = _case_key(link)
            (dropped if key in backup_files or key in folders else kept).append((part, link))
    return RestorePlan(contents, scan.flavor, chosen, removed, newer, kept, dropped, needed,
                       _free_space(scan.flavor.path, disk_usage), list(scan.leftovers), unreadable)
