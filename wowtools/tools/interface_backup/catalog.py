"""Backup file names in the backup root (backup-<flavor>-<stamp>.zip and pre-restore-<flavor>-<stamp>.zip), listing
and pruning. UI-free."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wowtools.core.fsutil import free_name

BACKUP = "backup"
SAFETY = "pre-restore"
KINDS = (BACKUP, SAFETY)
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


def new_backup_path(root: Path, flavor_short: str, now: datetime, kind: str = BACKUP) -> Path:
    """root/<kind>-<flavor>-<YYYYMMDD-HHMMSS>.zip, or -2, -3 ... when that name is taken."""
    if kind not in KINDS:
        raise ValueError(f"unknown backup kind {kind!r}")
    return free_name(root, f"{kind}-{flavor_short}-{now:%Y%m%d-%H%M%S}", ".zip")


def list_backups(root: Path | None, flavor_shorts: set[str] | None = None, *,
                 kinds: tuple[str, ...] = KINDS) -> list[BackupInfo]:
    """Backups in root (top level only, regular files only), newest first. Never raises: an unreadable or missing
    folder lists nothing."""
    if root is None:
        return []
    try:
        with os.scandir(root) as it:
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
    return sorted(found, key=lambda b: (b.stamp, b.n), reverse=True)


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
    """Delete all but the newest `keep` backup-<flavor>-*.zip of this flavor; keep 0 means never delete. Safety
    backups, other flavors' backups and other files are never touched. `protect` (the backup just made) is never
    deleted and takes one of the `keep` slots, whatever its stamp: an older backup stamped later (a clock
    change, a DST fall-back) cannot push it out."""
    if keep <= 0:
        return []
    found = [b.path for b in list_backups(root, {flavor_short}, kinds=(BACKUP,))]
    kept = [p for p in found if protect is not None and p.name == protect.name]
    if kept:
        found.remove(kept[0])
        keep -= 1
    return _delete(found[keep:])


def prune_safety(root: Path, referenced: set[str]) -> list[Path]:
    """Delete pre-restore zips whose file name no remaining restore journal names."""
    return _delete([b.path for b in list_backups(root, kinds=(SAFETY,)) if b.path.name not in referenced])
