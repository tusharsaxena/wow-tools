"""Safety net for a real clean: a verified backup of the whole WTF folder plus a marker file (spec A.4, D).

UI-free. The backup ("snapshot" in the code) is taken before anything is deleted, to
<backup folder>/backup/backup-<flavor>-<YYYYMMDD-HHMMSS>.zip, and kept afterwards; prune_snapshots() keeps the
newest N of each flavor.
The marker says a clean is in progress. After an unexpected error the files this run deleted are put back from
the snapshot. Nothing here ever restores on its own after a crash: a leftover marker only produces a notice.
"""
from __future__ import annotations

import os
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from wowtools.core import marker as core_marker
from wowtools.core import snapshot as core_snapshot
from wowtools.core.backup import BackupError
from wowtools.core.fsutil import remove_quietly
from wowtools.core.install import Flavor
from wowtools.core.paths import to_native
from wowtools.core.snapshot import SnapshotProgress, wtf_files

MARKER_NAME = "clean-in-progress.json"
SNAPSHOT_SUBDIR = "backup"
SNAPSHOT_PREFIX = "backup"


@dataclass(frozen=True)
class Marker:
    snapshot: Path
    flavor: str
    flavor_path: Path
    started: str
    pid: int
    suite_version: str
    files: list[str]


def take_snapshot(flavor: Flavor, backup_dir: Path, now: datetime,
                  progress: SnapshotProgress | None = None, must_hold: list[str] | None = None) -> Path:
    """Zip every regular file under <flavor>/WTF (stored as WTF/...) into <backup folder>/backup, verify it, then
    move it into place. must_hold: the flavor-relative paths ("WTF/...") the clean will delete; a BackupError if
    any of them is not among the files backed up (core.snapshot.take_snapshot)."""
    return core_snapshot.take_snapshot(flavor, backup_dir / SNAPSHOT_SUBDIR, SNAPSHOT_PREFIX, now, progress,
                                       must_hold)


def snapshot_path(backup_dir: Path, flavor_short: str, now: datetime) -> Path:
    """<backup folder>/backup/backup-<flavor>-<YYYYMMDD-HHMMSS>.zip, e.g. backup-retail-20261003-140311.zip, with
    -2, -3, ... before .zip when that name is taken (two cleans in the same second)."""
    return core_snapshot.snapshot_path(backup_dir / SNAPSHOT_SUBDIR, SNAPSHOT_PREFIX, flavor_short, now)


def prune_snapshots(backup_dir: Path, flavor_short: str, keep: int) -> list[Path]:
    """Delete all but the newest `keep` (0 = keep all) WTF backups of this flavor (backup-<flavor>-<stamp>.zip) in
    <backup_dir>/backup. Other flavors' backups and other files are never touched. Returns what was removed."""
    return core_snapshot.prune_snapshots(backup_dir / SNAPSHOT_SUBDIR, SNAPSHOT_PREFIX, flavor_short, keep)


def write_marker(backup_dir: Path, marker: Marker) -> None:
    core_marker.write_marker(backup_dir, MARKER_NAME, asdict(marker))


def read_marker(backup_dir: Path | None) -> Marker | None:
    """The marker left by an unfinished clean, or None (missing or unreadable). Never raises."""
    data = core_marker.read_marker(backup_dir, MARKER_NAME)
    if data is None:
        return None
    try:
        files = data["files"]
        if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
            return None
        pid = data["pid"]
        if not isinstance(pid, int):
            return None
        return Marker(snapshot=to_native(data["snapshot"]), flavor=str(data["flavor"]),
                      flavor_path=to_native(data["flavor_path"]), started=str(data["started"]), pid=pid,
                      suite_version=str(data["suite_version"]), files=list(files))
    except Exception:  # noqa: BLE001 - any unreadable marker means "no usable marker"
        return None


def clear_marker(backup_dir: Path) -> bool:
    """Remove the marker; False when it is still there after the retries. Callers may ignore it: a leftover marker
    here only produces a notice at the next start."""
    return core_marker.clear_marker(backup_dir, MARKER_NAME)


def restore_deleted(snapshot: Path, flavor: Flavor, rel_paths: list[str]) -> list[str]:
    """Extract exactly rel_paths from the snapshot into the flavor folder. Existing files are never overwritten.

    Returns the paths that were restored. Raises BackupError if the snapshot cannot be read or lacks an entry.
    """
    restored: list[str] = []
    try:
        with zipfile.ZipFile(snapshot) as zf:
            names = set(zf.namelist())
            missing = [rel for rel in rel_paths if rel not in names]
            if missing:
                raise BackupError(f"the WTF backup {snapshot} has no entry for {', '.join(missing)}")
            for rel in rel_paths:
                parts = PurePosixPath(rel).parts
                if PurePosixPath(rel).is_absolute() or ".." in parts:
                    raise BackupError(f"refusing to restore {rel!r}: it is not inside the flavor folder")
                dest = flavor.path.joinpath(*parts)
                if dest.exists() or dest.is_symlink():
                    continue
                info = zf.getinfo(rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    out = open(dest, "xb")  # noqa: SIM115 - closed by the `with` below; exclusive create: never overwrite a file that appeared meanwhile
                except FileExistsError:
                    continue
                try:
                    with out, zf.open(info) as src:
                        while chunk := src.read(1 << 20):
                            out.write(chunk)
                except BaseException:
                    remove_quietly(dest)
                    raise
                mtime = time.mktime(info.date_time + (0, 0, -1))
                os.utime(dest, (mtime, mtime))
                restored.append(rel)
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile, ValueError, KeyError) as exc:
        raise BackupError(f"could not restore from {snapshot}: {exc}") from exc
    return restored


def check_clean(snapshot: Path, flavor: Flavor, deleted: list[str], backup_zip: Path | None,
                progress: SnapshotProgress | None = None) -> list[str]:
    """Compare the WTF folder after a clean with its safety snapshot. Returns the problems found (empty = good).

    - every file this clean deleted is gone, and is in the snapshot;
    - every other file in the snapshot is still on disk;
    - with a backup zip, it lists every deleted file at the size the snapshot recorded.
    Never raises: a check that cannot run is reported as a problem.
    """
    problems: list[str] = []
    try:
        with zipfile.ZipFile(snapshot) as zf:
            in_snapshot = {info.filename: info.file_size for info in zf.infolist()}
        on_disk = {path.relative_to(flavor.path).as_posix() for path in wtf_files(flavor, progress, "validate")}
        gone = set(deleted)
        for rel in sorted(gone):
            if rel in on_disk:
                problems.append(f"{rel} was reported deleted but is still on disk")
            if rel not in in_snapshot:
                problems.append(f"{rel} was deleted but is not in the WTF backup")
        for rel in sorted(set(in_snapshot) - gone - on_disk):
            problems.append(f"{rel} is missing but was not selected for deletion")
        if backup_zip is not None:
            with zipfile.ZipFile(backup_zip) as zf:
                in_backup = {info.filename: info.file_size for info in zf.infolist()}
            for rel in sorted(gone):
                if rel not in in_backup:
                    problems.append(f"{rel} was deleted but is not in the cleaned-files zip")
                elif rel in in_snapshot and in_backup[rel] != in_snapshot[rel]:
                    problems.append(f"{rel} has a different size in the cleaned-files zip than in the WTF backup")
    except Exception as exc:  # noqa: BLE001 - a check that cannot run is a problem
        problems.append(f"the check could not run: {exc}")
    return problems


def recovery_message(marker: Marker) -> str:
    return (f"The last clean of {marker.flavor} did not finish (it started {marker.started}).\n"
            f"A backup of the WTF folder from just before it is at: {marker.snapshot}\n"
            f"If files are missing: close WoW, then unzip it into {marker.flavor_path} to restore.")
