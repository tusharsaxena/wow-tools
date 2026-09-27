"""Safety net for a real clean: a verified snapshot of the whole WTF folder plus a marker file (spec A.4).

UI-free. The snapshot is taken before anything is deleted; the marker says a clean is in progress. After an
unexpected error the files this run deleted are put back from the snapshot. Nothing here ever restores on its
own after a crash: a leftover marker only produces a notice (recovery_message).
"""
from __future__ import annotations

import json
import os
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from wowtools.core.backup import BackupError, backup_filename, verify_backup
from wowtools.core.install import Flavor

MARKER_NAME = "clean-in-progress.json"
SNAPSHOT_PREFIX = "wtf-snapshot"

SnapshotProgress = Callable[[str, int, int, str], None]


@dataclass(frozen=True)
class Marker:
    snapshot: Path
    flavor: str
    flavor_path: Path
    started: str
    pid: int
    suite_version: str
    files: list[str]


def _wtf_files(flavor: Flavor) -> list[Path]:
    found: list[Path] = []

    def fail(exc: OSError) -> None:
        raise exc

    for dirpath, dirnames, filenames in os.walk(flavor.wtf_dir, onerror=fail):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_file() and not path.is_symlink():
                found.append(path)
    return found


def take_snapshot(flavor: Flavor, backup_dir: Path, now: datetime,
                  progress: SnapshotProgress | None = None) -> Path:
    """Zip every regular file under <flavor>/WTF (stored as WTF/...), verify it, then move it into place."""
    dest = backup_dir / backup_filename(SNAPSHOT_PREFIX, flavor.short_name, now)
    partial = dest.with_name(dest.name + ".partial")
    try:
        if not flavor.wtf_dir.is_dir():
            raise BackupError(f"{flavor.wtf_dir} is not a folder")
        files = _wtf_files(flavor)
        base = flavor.path
        expected: dict[str, int] = {}
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=False) as zf:
            for index, path in enumerate(files, 1):
                arcname = path.relative_to(base).as_posix()
                expected[arcname] = path.stat().st_size
                zf.write(path, arcname)
                if progress is not None:
                    progress("snapshot", index, len(files), arcname)
        verify_backup(partial, expected)
        os.replace(partial, dest)
    except BackupError:
        _remove(partial)
        raise
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        _remove(partial)
        raise BackupError(f"safety snapshot failed: {exc}") from exc
    return dest


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
    _remove(backup_dir / MARKER_NAME)


def remove_snapshot(snapshot: Path) -> None:
    _remove(snapshot)


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
                raise BackupError(f"the snapshot {snapshot} has no entry for {', '.join(missing)}")
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
                    out = open(dest, "xb")  # exclusive create: never overwrite a file that appeared meanwhile
                except FileExistsError:
                    continue
                try:
                    with out, zf.open(info) as src:
                        while chunk := src.read(1 << 20):
                            out.write(chunk)
                except BaseException:
                    _remove(dest)
                    raise
                mtime = time.mktime(info.date_time + (0, 0, -1))
                os.utime(dest, (mtime, mtime))
                restored.append(rel)
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile, ValueError, KeyError) as exc:
        raise BackupError(f"could not restore from {snapshot}: {exc}") from exc
    return restored


def recovery_message(marker: Marker) -> str:
    return (f"The last clean of {marker.flavor} did not finish (it started {marker.started}).\n"
            f"A safety snapshot of the WTF folder is at: {marker.snapshot}\n"
            f"If files are missing: close WoW, then unzip it into {marker.flavor_path} to restore.")


def _remove(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
