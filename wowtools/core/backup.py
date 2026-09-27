"""Timestamped zip backups with a manifest, verified before anyone deletes anything."""
from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

MANIFEST_NAME = "manifest.json"


class BackupError(Exception):
    """The backup could not be written or verified. Nothing should be deleted."""


@dataclass(frozen=True)
class BackupEntry:
    path: Path
    reasons: tuple[str, ...] = ()


def backup_filename(tool: str, flavor_short: str, when: datetime) -> str:
    return f"{tool}_{flavor_short}_{when:%Y%m%d-%H%M%S}.zip"


def create_backup(entries: list[BackupEntry], base_dir: Path, dest_zip: Path, meta: dict,
                  on_file: Callable[[int, int, str], None] | None = None) -> Path:
    """Zip entries (stored relative to base_dir) plus manifest.json, verify, then move into place.

    on_file(current, total, arcname) is called after each file is written to the zip."""
    if not entries:
        raise BackupError("nothing to back up")
    base = base_dir.resolve()
    expected: dict[str, int] = {}
    files: list[dict] = []
    for entry in entries:
        source = entry.path.resolve()
        try:
            arcname = source.relative_to(base).as_posix()
        except ValueError as exc:
            raise BackupError(f"{entry.path} is not inside {base_dir}") from exc
        try:
            stat = source.stat()
        except OSError as exc:
            raise BackupError(f"cannot read {entry.path}: {exc}") from exc
        expected[arcname] = stat.st_size
        files.append({"path": arcname, "size": stat.st_size, "mtime": stat.st_mtime,
                      "reasons": list(entry.reasons)})

    partial = dest_zip.with_name(dest_zip.name + ".partial")
    try:
        dest_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=False) as zf:
            for index, (entry, info) in enumerate(zip(entries, files), 1):
                zf.write(entry.path, info["path"])
                if on_file is not None:
                    on_file(index, len(files), info["path"])
            zf.writestr(MANIFEST_NAME, json.dumps({**meta, "files": files}, indent=2, ensure_ascii=False))
        verify_backup(partial, expected)
        os.replace(partial, dest_zip)
    except BackupError:
        _discard(partial)
        raise
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        _discard(partial)
        raise BackupError(f"backup failed: {exc}") from exc
    return dest_zip


def verify_backup(zip_path: Path, expected: dict[str, int]) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise BackupError(f"corrupt entry in backup: {bad}")
        sizes = {info.filename: info.file_size for info in zf.infolist() if info.filename != MANIFEST_NAME}
    if sizes != expected:
        raise BackupError("backup contents do not match the selected files")


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
