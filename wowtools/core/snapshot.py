"""A verified zip of a flavor's whole WTF folder, taken before a tool changes or deletes SavedVariables.

UI-free. Shared by the WTF Cleaner (<backup folder>/backup/backup-<flavor>-<stamp>.zip) and the Ace3 Profile
Manager (<tool root>/snapshots/snapshot-<flavor>-<stamp>.zip): the folder and the name prefix are parameters.
prune_snapshots() keeps the newest N of one prefix and flavor (0 = all).
"""
from __future__ import annotations

import re
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from wowtools.core.backup import BackupError, verify_backup, walk_files
from wowtools.core.fsutil import fsync_file, free_name, remove_quietly, rename_no_replace
from wowtools.core.install import Flavor

SnapshotProgress = Callable[[str, int, int, str], None]
LIST_REPORT_EVERY = 100


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


def take_snapshot(flavor: Flavor, folder: Path, prefix: str, now: datetime,
                  progress: SnapshotProgress | None = None, must_hold: list[str] | None = None) -> Path:
    """Zip every regular file under <flavor>/WTF (stored as WTF/...) into folder/<prefix>-<flavor>-<stamp>.zip,
    verify it, then move it into place (never replacing a file). must_hold: flavor-relative paths ("WTF/...") the
    caller will change or delete; a BackupError if any of them is not among the files backed up (e.g. under a
    link, which the backup never follows): nothing could put it back."""
    dest = snapshot_path(folder, prefix, flavor.short_name, now)
    partial = dest.with_name(dest.name + ".partial")
    try:
        if not flavor.wtf_dir.is_dir():
            raise BackupError(f"{flavor.wtf_dir} is not a folder")
        files = wtf_files(flavor, progress)
        base = flavor.path
        if must_hold:
            held = {path.relative_to(base).as_posix() for path in files}
            absent = [rel for rel in must_hold if rel not in held]
            if absent:
                raise BackupError(f"{len(absent)} file(s) to delete would not be in the WTF backup (under a link?), "
                                  f"so nothing was deleted: {', '.join(absent[:5])}")
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
        fsync_file(partial)  # on the disk before it is in place (F-012)
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


def snapshot_path(folder: Path, prefix: str, flavor_short: str, now: datetime) -> Path:
    """folder/<prefix>-<flavor>-<YYYYMMDD-HHMMSS>.zip, e.g. backup-retail-20261003-140311.zip, with -2, -3, ...
    before .zip when that name is taken (two runs in the same second)."""
    return free_name(folder, f"{prefix}-{flavor_short}-{now:%Y%m%d-%H%M%S}", ".zip")


def _name_pattern(prefix: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(prefix)}-(?P<flavor>.+?)-(?P<stamp>\d{{8}}-\d{{6}})(?:-(?P<n>\d+))?\.zip$")


def prune_snapshots(folder: Path, prefix: str, flavor_short: str, keep: int) -> list[Path]:
    """Delete all but the newest `keep` snapshots of this prefix and flavor (<prefix>-<flavor>-<stamp>.zip) in
    folder; keep 0 (or less) keeps all. Other prefixes, other flavors and other files are never touched. Returns
    what was removed."""
    if keep <= 0:
        return []
    pattern = _name_pattern(prefix)
    try:
        matches = [(m, p) for p in folder.iterdir() if (m := pattern.match(p.name)) and p.is_file()]
    except OSError:
        return []
    found = [p for m, p in sorted(matches, key=lambda mp: (mp[0]["stamp"], int(mp[0]["n"] or 1)), reverse=True)
             if m["flavor"] == flavor_short]
    removed: list[Path] = []
    for path in found[keep:]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            pass
    return removed
