"""Backup file names (backup-<flavor>-<stamp>.zip and pre-restore-<flavor>-<stamp>.zip) in <root>/backup, listing
and pruning. `root` is the tool's folder (settings.resolve_backup_root). UI-free."""
from __future__ import annotations

import json
import os
import re
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wowtools.core.backup import MANIFEST_NAME
from wowtools.core.fsutil import free_name
from wowtools.tools.interface_backup.scanner import PARTS

BACKUP = "backup"
SAFETY = "pre-restore"
KINDS = (BACKUP, SAFETY)
ZIPS_SUBDIR = "backup"  # <root>/backup, a sibling of <root>/journal (L16)
NAME = re.compile(r"^(?P<kind>backup|pre-restore)-(?P<flavor>.+?)-(?P<stamp>\d{8}-\d{6})(?:-(?P<n>\d+))?\.zip$")


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    kind: str  # BACKUP or SAFETY
    flavor_short: str
    stamp: str  # YYYYMMDD-HHMMSS
    n: int  # 1, or the -2, -3 ... added when the name was taken
    size: int

    @property
    def is_safety(self) -> bool:
        return self.kind == SAFETY

    @property
    def when(self) -> str:
        """The stamp as "YYYY-MM-DD HH:MM:SS"."""
        s = self.stamp
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[9:11]}:{s[11:13]}:{s[13:15]}"


def zips_dir(root: Path) -> Path:
    """Where new backups and pre-restore zips go: <root>/backup."""
    return root / ZIPS_SUBDIR


def new_backup_path(root: Path, flavor_short: str, now: datetime, kind: str = BACKUP) -> Path:
    """<root>/backup/<kind>-<flavor>-<YYYYMMDD-HHMMSS>.zip, or -2, -3 ... when that name is taken there."""
    if kind not in KINDS:
        raise ValueError(f"unknown backup kind {kind!r}")
    return free_name(zips_dir(root), f"{kind}-{flavor_short}-{now:%Y%m%d-%H%M%S}", ".zip")


def _scan(folder: Path, flavor_shorts: set[str] | None, kinds: tuple[str, ...]) -> list[BackupInfo]:
    """The backups in folder (top level only, regular files only). Never raises: an unreadable or missing folder
    lists nothing."""
    try:
        with os.scandir(folder) as it:
            entries = list(it)
    except OSError:
        return []
    found = []
    for entry in entries:
        m = NAME.match(entry.name)
        if not m or m["kind"] not in kinds or (flavor_shorts is not None and m["flavor"] not in flavor_shorts):
            continue
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            size = entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue
        found.append(BackupInfo(Path(entry.path), m["kind"], m["flavor"], m["stamp"], int(m["n"] or 1), size))
    return found


def list_backups(root: Path | None, flavor_shorts: set[str] | None = None, *,
                 kinds: tuple[str, ...] = KINDS) -> list[BackupInfo]:
    """Backups in <root>/backup, newest first. Never raises: an unreadable or missing folder lists nothing."""
    if root is None:
        return []
    found = _scan(zips_dir(root), flavor_shorts, kinds)
    return sorted(found, key=lambda b: (b.stamp, b.n), reverse=True)


def read_parts(path: Path) -> tuple[str, ...] | None:
    """The parts a backup's manifest claims, in PARTS order, or None when the zip or its manifest cannot be read.
    Reads the manifest entry only: no entry is checked and nothing is verified (open_backup and verify_backup
    do that before a restore). Never raises."""
    try:
        with zipfile.ZipFile(path) as zf:
            manifest = json.loads(zf.read(MANIFEST_NAME))
        parts = manifest["parts"]
    except (OSError, zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, ValueError,
            KeyError, TypeError, RecursionError):
        return None
    if not isinstance(parts, list):
        return None
    return tuple(p for p in PARTS if p in parts)


def _delete(paths: list[Path]) -> list[Path]:
    """Unlink each file; return the ones that went. One that cannot be deleted is left and skipped."""
    removed = []
    for path in paths:
        try:
            path.unlink()
        except OSError:
            continue
        removed.append(path)
    return removed


def prune_backups(root: Path, flavor_short: str, keep: int, *, protect: Path | None = None) -> list[Path]:
    """Delete all but the newest `keep` backup-<flavor>-*.zip of this flavor in <root>/backup; keep 0 means
    never delete. Safety backups, other flavors' backups and other files are never touched. `protect` (the backup just made) is never
    deleted and takes one of the `keep` slots, whatever its stamp: an older backup stamped later (a clock
    change, a DST fall-back) cannot push it out."""
    if keep <= 0:
        return []
    found = [b.path for b in list_backups(root, {flavor_short}, kinds=(BACKUP,))]
    kept = [] if protect is None else [p for p in found if p == protect] or [p for p in found if p.name == protect.name]
    if kept:
        found.remove(kept[0])
        keep -= 1
    return _delete(found[keep:])


def prune_safety(root: Path, names: set[str], *, protect: Path | None = None) -> list[Path]:
    """Delete the pre-restore zips in <root>/backup whose file name is in `names` (the caller passes
    those only pruned journals named). Any other file, and `protect` (a safety zip being restored from), is never
    touched."""
    return _delete([b.path for b in list_backups(root, kinds=(SAFETY,))
                    if b.path.name in names and (protect is None or b.path.name != protect.name)])
