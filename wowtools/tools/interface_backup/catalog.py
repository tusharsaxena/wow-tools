"""Backup file names (backup-<flavor>-<stamp>.zip and pre-restore-<flavor>-<stamp>.zip) in <root>/backup, listing
and pruning, and the one-time move of the zips an older version wrote to <root> itself (L16). `root` is the
tool's folder (settings.resolve_backup_root); until a zip is moved, listing and pruning see it in <root> too.
UI-free."""
from __future__ import annotations

import json
import os
import re
import threading
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from wowtools.core import activity
from wowtools.core.backup import MANIFEST_NAME
from wowtools.core.events import log_event
from wowtools.core.fsutil import free_name, rename_no_replace
from wowtools.core.paths import to_stored
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
    """<root>/backup/<kind>-<flavor>-<YYYYMMDD-HHMMSS>.zip, or -2, -3 ... when that name is taken there or in
    <root> (a zip not moved yet keeps its name free, so its move never clashes)."""
    if kind not in KINDS:
        raise ValueError(f"unknown backup kind {kind!r}")
    return free_name(zips_dir(root), f"{kind}-{flavor_short}-{now:%Y%m%d-%H%M%S}", ".zip", also=(root,))


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
    """Backups in <root>/backup and, not moved yet, in <root> itself, newest first. Never raises: an unreadable or
    missing folder lists nothing."""
    if root is None:
        return []
    found = _scan(zips_dir(root), flavor_shorts, kinds) + _scan(root, flavor_shorts, kinds)
    return sorted(found, key=lambda b: (b.stamp, b.n), reverse=True)


def zip_now_at(path: Path, root: Path) -> Path:
    """Where a zip a journal named is now: path itself, or the zip of that name in <root>/backup when path is gone
    and that one is there (an older run's zip, moved by move_old_zips)."""
    if os.path.lexists(path):
        return path
    moved = zips_dir(root) / path.name
    return moved if os.path.lexists(moved) else path


@dataclass
class ZipMove:
    """What move_old_zips did: file names moved, left in place because backup/ has that name, or failed."""
    moved: list[str] = field(default_factory=list)
    taken: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)  # "<name>: <error>"


_reported: set[tuple[str, str]] = set()  # (folder, name) of the zips left in place already logged this session
_reported_lock = threading.Lock()


def move_old_zips(root: Path | None) -> ZipMove | None:
    """Move the zips an older version wrote to <root> (backup-*.zip, pre-restore-*.zip) into <root>/backup with
    rename_no_replace: a name backup/ already has is left in place, a move that fails is left in place too (both
    stay listed, restorable and pruned where they are, and are tried again on the next scan). A backup/ that is a
    link to a folder is used, as new_backup_path and the zip writers use it. Runs inside activity.running()
    (STD-5.19). Logged as ibackup.zips_moved, at warning when one was left; a zip left in place is logged the first
    time only, so the next scans log nothing until something moves or another zip is left. None, with nothing
    logged, when there is nothing to move. Never raises. Runs in the review's scan worker, never on the UI thread
    (STD-7.20)."""
    if root is None:
        return None
    old = sorted(b.path.name for b in _scan(root, None, KINDS))
    if not old:
        return None
    folder, result = zips_dir(root), ZipMove()
    with activity.running():
        try:
            folder.mkdir(exist_ok=True)
            if not folder.is_dir():
                raise NotADirectoryError(f"{to_stored(folder)} is not a folder")
        except OSError as exc:
            result.failed = [f"{name}: {exc}" for name in old]
            left = list(old)
        else:
            left = []
            for name in old:
                try:
                    rename_no_replace(root / name, folder / name)
                except FileExistsError:
                    result.taken.append(name)
                    left.append(name)
                except OSError as exc:
                    result.failed.append(f"{name}: {exc}")
                    left.append(name)
                else:
                    result.moved.append(name)
    stored = to_stored(folder)
    with _reported_lock:
        new_left = {(stored, name) for name in left} - _reported
        _reported.update(new_left)
        _reported.difference_update({(stored, name) for name in result.moved})
    if result.moved or new_left:
        log_event("ibackup.zips_moved", level="warning" if left else None,
                  folder=stored, moved=len(result.moved), taken=result.taken, failed=result.failed)
    return result


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
    """Delete all but the newest `keep` backup-<flavor>-*.zip of this flavor, in <root>/backup and <root> alike;
    keep 0 means never delete. Safety
    backups, other flavors' backups and other files are never touched. `protect` (the backup just made) is never
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
    """Delete the pre-restore zips (in <root>/backup or <root>) whose file name is in `names` (the caller passes
    those only pruned journals named). Any other file, and `protect` (a safety zip being restored from), is never
    touched."""
    return _delete([b.path for b in list_backups(root, kinds=(SAFETY,))
                    if b.path.name in names and (protect is None or b.path.name != protect.name)])
