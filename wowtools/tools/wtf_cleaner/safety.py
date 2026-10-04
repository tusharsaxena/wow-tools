"""Safety net for a real clean: a verified backup of the whole WTF folder plus a marker file (spec A.4, D).

UI-free. The backup ("snapshot" in the code) is taken before anything is deleted, to
<backup folder>/backup/backup-<flavor>-<YYYYMMDD-HHMMSS>.zip, and kept afterwards; prune_snapshots() keeps the
newest N of each flavor.
The marker says a clean is in progress. After an unexpected error the files this run deleted are put back from
the snapshot. Nothing here ever restores on its own after a crash: a leftover marker only produces a notice.
"""
from __future__ import annotations

import json
import os
import re
import time
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from wowtools.core.backup import BackupError, verify_backup, walk_files
from wowtools.core.fsutil import free_name, remove_quietly, rename_no_replace
from wowtools.core.install import Flavor

MARKER_NAME = "clean-in-progress.json"
SNAPSHOT_SUBDIR = "backup"
SNAPSHOT_NAME = re.compile(r"^backup-(?P<flavor>.+?)-(?P<stamp>\d{8}-\d{6})(?:-(?P<n>\d+))?\.zip$")
DEFAULT_KEEP_SNAPSHOTS = 5

SnapshotProgress = Callable[[str, int, int, str], None]
LIST_REPORT_EVERY = 100


@dataclass(frozen=True)
class Marker:
    snapshot: Path
    flavor: str
    flavor_path: Path
    started: str
    pid: int
    suite_version: str
    files: list[str]


def wtf_files(flavor: Flavor, progress: SnapshotProgress | None = None, stage: str = "snapshot_list") -> list[Path]:
    """Every regular file under <flavor>/WTF, sorted. Uses directory entries only (no per-file stat), so it stays
    fast on slow drives. progress(stage, found, 0, label) is called every LIST_REPORT_EVERY files and once at the
    end with found == total. Links are skipped."""
    def counted(found: int) -> None:
        progress(stage, found, 0, f"{found} files found")

    found = [Path(entry.path) for entry in walk_files(flavor.wtf_dir, on_count=None if progress is None else counted,
                                                      every=LIST_REPORT_EVERY)]
    if progress is not None:
        progress(stage, len(found), len(found), f"{len(found)} files found")
    return found


def take_snapshot(flavor: Flavor, backup_dir: Path, now: datetime,
                  progress: SnapshotProgress | None = None) -> Path:
    """Zip every regular file under <flavor>/WTF (stored as WTF/...), verify it, then move it into place."""
    dest = snapshot_path(backup_dir, flavor.short_name, now)
    partial = dest.with_name(dest.name + ".partial")
    try:
        if not flavor.wtf_dir.is_dir():
            raise BackupError(f"{flavor.wtf_dir} is not a folder")
        files = wtf_files(flavor, progress)
        base = flavor.path
        expected: dict[str, int] = {}
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=False) as zf:
            for index, path in enumerate(files, 1):
                arcname = path.relative_to(base).as_posix()
                zf.write(path, arcname)
                expected[arcname] = zf.getinfo(arcname).file_size  # the bytes actually stored
                if progress is not None:
                    progress("snapshot", index, len(files), arcname)
        verify_backup(partial, expected,
                      progress=None if progress is None else lambda i, n, name: progress("snapshot_verify", i, n, name))
        rename_no_replace(partial, dest)  # never replaces an existing backup
    except BackupError:
        remove_quietly(partial)
        raise
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        remove_quietly(partial)
        raise BackupError(f"the WTF backup failed: {exc}") from exc
    except BaseException:  # e.g. Ctrl+C while zipping: never leave a stray .partial behind
        remove_quietly(partial)
        raise
    return dest


def snapshot_path(backup_dir: Path, flavor_short: str, now: datetime) -> Path:
    """<backup folder>/backup/backup-<flavor>-<YYYYMMDD-HHMMSS>.zip, e.g. backup-retail-20261003-140311.zip, with
    -2, -3, ... before .zip when that name is taken (two cleans in the same second)."""
    return free_name(backup_dir / SNAPSHOT_SUBDIR, f"backup-{flavor_short}-{now:%Y%m%d-%H%M%S}", ".zip")


def prune_snapshots(backup_dir: Path, flavor_short: str, keep: int) -> list[Path]:
    """Delete all but the newest `keep` (at least 1) WTF backups of this flavor (backup-<flavor>-<stamp>.zip) in
    <backup_dir>/backup. Other flavors' backups and other files are never touched. Returns what was removed."""
    folder = backup_dir / SNAPSHOT_SUBDIR
    try:
        matches = [(m, p) for p in folder.iterdir() if (m := SNAPSHOT_NAME.match(p.name)) and p.is_file()]
    except OSError:
        return []
    found = [p for m, p in sorted(matches, key=lambda mp: (mp[0]["stamp"], int(mp[0]["n"] or 1)), reverse=True)
             if m["flavor"] == flavor_short]
    removed: list[Path] = []
    for path in found[max(1, keep):]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            pass
    return removed


def write_marker(backup_dir: Path, marker: Marker) -> None:
    data = asdict(marker)
    data["snapshot"] = str(marker.snapshot)
    data["flavor_path"] = str(marker.flavor_path)
    target = backup_dir / MARKER_NAME
    partial = target.with_name(target.name + ".partial")
    backup_dir.mkdir(parents=True, exist_ok=True)
    partial.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(partial, target)


def read_marker(backup_dir: Path | None) -> Marker | None:
    """The marker left by an unfinished clean, or None (missing or unreadable). Never raises."""
    if backup_dir is None:
        return None
    try:
        data = json.loads((backup_dir / MARKER_NAME).read_text(encoding="utf-8"))
        files = data["files"]
        if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
            return None
        pid = data["pid"]
        if not isinstance(pid, int):
            return None
        return Marker(snapshot=Path(data["snapshot"]), flavor=str(data["flavor"]),
                      flavor_path=Path(data["flavor_path"]), started=str(data["started"]), pid=pid,
                      suite_version=str(data["suite_version"]), files=list(files))
    except Exception:  # noqa: BLE001 - any unreadable marker means "no usable marker"
        return None


def clear_marker(backup_dir: Path) -> None:
    remove_quietly(backup_dir / MARKER_NAME)


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
