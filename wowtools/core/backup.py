"""Timestamped zip backups with a manifest, verified before anyone deletes anything."""
from __future__ import annotations

import json
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from wowtools.core.fsutil import remove_quietly, rename_no_replace

MANIFEST_NAME = "manifest.json"


class BackupError(Exception):
    """The backup could not be written or verified. Nothing should be deleted."""


@dataclass(frozen=True)
class BackupEntry:
    """One file to back up. Give size and mtime when the caller has just checked them, to skip another stat."""

    path: Path
    reasons: tuple[str, ...] = ()
    size: int | None = None
    mtime: float | None = None


def _arcname(path: Path, base_dir: Path, resolved_base: list[Path]) -> str:
    """path relative to base_dir. Lexical when possible (no disk access); resolves only as a fallback."""
    if path.is_absolute() and ".." not in path.parts:
        try:
            return path.relative_to(base_dir).as_posix()
        except ValueError:
            pass
    if not resolved_base:
        resolved_base.append(base_dir.resolve())
    try:
        return path.resolve().relative_to(resolved_base[0]).as_posix()
    except ValueError as exc:
        raise BackupError(f"{path} is not inside {base_dir}") from exc


def create_backup(entries: list[BackupEntry], base_dir: Path, dest_zip: Path, meta: dict,
                  on_file: Callable[[int, int, str], None] | None = None,
                  on_verify: Callable[[int, int, str], None] | None = None) -> Path:
    """Zip entries (stored relative to base_dir) plus manifest.json, verify, then move into place.

    on_file(current, total, arcname) is called after each file is written to the zip, and on_verify(current,
    total, arcname) after each entry is checked."""
    if not entries:
        raise BackupError("nothing to back up")
    resolved_base: list[Path] = []
    expected: dict[str, int] = {}
    files: list[dict] = []
    for entry in entries:
        arcname = _arcname(entry.path, base_dir, resolved_base)
        size, mtime = entry.size, entry.mtime
        if size is None or mtime is None:
            try:
                stat = entry.path.stat()
            except OSError as exc:
                raise BackupError(f"cannot read {entry.path}: {exc}") from exc
            size, mtime = stat.st_size, stat.st_mtime
        expected[arcname] = size
        files.append({"path": arcname, "size": size, "mtime": mtime, "reasons": list(entry.reasons)})

    partial = dest_zip.with_name(dest_zip.name + ".partial")
    try:
        dest_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=False) as zf:
            for index, (entry, info) in enumerate(zip(entries, files), 1):
                zf.write(entry.path, info["path"])
                if on_file is not None:
                    on_file(index, len(files), info["path"])
            zf.writestr(MANIFEST_NAME, json.dumps({**meta, "files": files}, indent=2, ensure_ascii=False))
        verify_backup(partial, expected, progress=on_verify)
        rename_no_replace(partial, dest_zip)  # never replaces an existing backup
    except BackupError:
        remove_quietly(partial)
        raise
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        remove_quietly(partial)
        raise BackupError(f"backup failed: {exc}") from exc
    return dest_zip


def verify_backup(zip_path: Path, expected: dict[str, int],
                  progress: Callable[[int, int, str], None] | None = None) -> None:
    """Read every entry back (which checks its CRC), then compare the entry sizes with expected."""
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        for index, info in enumerate(infos, 1):
            try:
                with zf.open(info) as src:
                    while src.read(1 << 20):
                        pass
            except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
                raise BackupError(f"corrupt entry in backup: {info.filename}") from exc
            if progress is not None:
                progress(index, len(infos), info.filename)
        sizes = {info.filename: info.file_size for info in infos if info.filename != MANIFEST_NAME}
    if sizes != expected:
        raise BackupError("backup contents do not match the selected files")
