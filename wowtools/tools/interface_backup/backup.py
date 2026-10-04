"""Back up a flavor's Interface and WTF folders to one verified zip, then prune that flavor's older backups.
UI-free. Nothing in the game folders changes, so there is no journal."""
from __future__ import annotations

import errno
import json
import os
import shutil
import stat
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from wowtools import __version__
from wowtools.core.backup import MANIFEST_NAME, BackupError, verify_backup
from wowtools.core.events import log_event
from wowtools.core.fsutil import is_real_dir, remove_quietly, rename_no_replace, safe_progress
from wowtools.core.install import Flavor
from wowtools.core.journal import now_iso
from wowtools.core.paths import to_stored
from wowtools.tools.interface_backup.catalog import BACKUP, new_backup_path, prune_backups
from wowtools.tools.interface_backup.scanner import PARTS, SAMPLE, FlavorScan

Progress = Callable[[str, int, int, str], None]
MANIFEST_VERSION = 1
# A zip entry's date is DOS time: 1980 to 2107. A file stamped outside it is stored with the nearest end.
_ZIP_FIRST = (1980, 1, 1, 0, 0, 0)
_ZIP_LAST = (2107, 12, 31, 23, 59, 58)
# POSIX: open never follows a symlink (ELOOP) and never waits on a FIFO; the opened file's own fstat says whether it
# is a regular file, so there is no separate lstat (a path round trip, slow on drvfs). Windows has neither flag.
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_BINARY = getattr(os, "O_BINARY", 0)


@dataclass
class ZipStats:
    path: Path
    files: int
    bytes_in: int  # bytes stored (as read while zipping, not as scanned)
    bytes_zip: int
    missing: list[str]  # "<Part>/<rel>" gone (or no longer a plain file, or under a linked folder) since the
    # scan; a bare "<Part>" when the whole part folder is gone or is a link now
    links: list[str]  # "<Part>/<rel>" links that were not followed; a bare "<Part>" when the part itself is one
    parts_existing: list[str]  # the parts written (each still a real folder with something read from it)


@dataclass
class BackupOutcome:
    flavor: Flavor
    kind: str  # created | skipped | failed
    path: Path | None = None
    files: int = 0
    bytes_in: int = 0
    bytes_zip: int = 0
    links: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reason: str = ""
    pruned: list[Path] = field(default_factory=list)


def _date_time(mtime: float) -> tuple[int, int, int, int, int, int]:
    try:
        t = time.localtime(mtime)
    except (OverflowError, OSError, ValueError):
        return _ZIP_FIRST
    return min(max((t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec), _ZIP_FIRST), _ZIP_LAST)


def _zip_info(arcname: str, st: os.stat_result) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(arcname, _date_time(st.st_mtime))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (st.st_mode & 0xFFFF) << 16
    info.file_size = st.st_size  # lets zipfile pick ZIP64 for files over 2 GiB
    return info


def _open_regular(path: Path) -> tuple[int, os.stat_result]:
    """An open file descriptor and its stat, for a regular file only (never through a link). FileNotFoundError for
    anything else (a link, a folder, a FIFO); OSError(ELOOP) for a symlink on POSIX."""
    if os.name == "nt":
        st = os.lstat(path)  # no O_NOFOLLOW on Windows: check first
        if not stat.S_ISREG(st.st_mode):
            raise FileNotFoundError(str(path))
        return os.open(path, os.O_RDONLY | _BINARY), st
    fd = os.open(path, os.O_RDONLY | _NOFOLLOW | _NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise FileNotFoundError(str(path))
    except BaseException:
        os.close(fd)
        raise
    return fd, st


def write_zip(scan: FlavorScan, dest: Path, *, kind: str, parts: tuple[str, ...] = PARTS,
              progress: Progress | None = None) -> ZipStats:
    """Zip the scanned parts of a flavor to dest as <Part>/<rel> plus manifest.json, through dest.partial, verify
    it, then move it into place without replacing anything. Links are never followed: a file gone since the scan,
    no longer a plain file (e.g. now a link) or under a folder that is now a link is left out and listed in
    missing; so is a whole part whose folder is gone or now a link, or none of whose files could be read (it is
    not claimed in the manifest, so a restore of this zip leaves that folder alone). A part that is itself a link
    is listed in links as "<Part>". Stages "backup" and "verify". Raises BackupError (also when no chosen part
    could be read at all); never leaves the .partial behind, even on Ctrl+C."""
    report = safe_progress(progress)
    flavor = scan.flavor
    chosen = [scan.parts[p] for p in PARTS if p in parts and scan.parts[p].exists]
    total = sum(len(p.files) for p in chosen)
    partial = dest.with_name(dest.name + ".partial")
    expected: dict[str, int] = {}
    files: list[dict] = []
    missing: list[str] = []
    links: list[str] = []
    for name in PARTS:
        if name in parts and scan.parts[name].linked:
            links.append(name)
        elif name in parts and scan.parts[name].exists:
            links.extend(f"{name}/{rel}" for rel in scan.parts[name].links)
    written: list[str] = []
    real_dirs: dict[Path, bool] = {}  # one lstat per folder

    def real_dir(path: Path) -> bool:
        if path not in real_dirs:
            real_dirs[path] = is_real_dir(path)
        return real_dirs[path]

    def under_real_dirs(base: Path, rel_parts: list[str]) -> bool:
        folder = base
        for name in rel_parts[:-1]:
            folder = folder / name
            if not real_dir(folder):
                return False
        return True

    done = 0
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(partial, "w", allowZip64=True) as zf:
            for part in chosen:
                if not real_dir(part.path):  # gone, or now a link, since the scan: never followed
                    missing.append(part.name)
                    done += len(part.files)
                    report("backup", done, total, part.name)
                    continue
                read_before = len(files)
                for info in part.files:
                    done += 1
                    arcname = f"{part.name}/{info.rel}"
                    rel_parts = info.rel.split("/")
                    source = part.path.joinpath(*rel_parts)
                    try:
                        if not under_real_dirs(part.path, rel_parts):
                            raise FileNotFoundError(arcname)  # a folder on the way is a link now: never followed
                        fd, st = _open_regular(source)  # a link or folder now: never followed
                        with open(fd, "rb") as src, zf.open(_zip_info(arcname, st), "w") as out:
                            shutil.copyfileobj(src, out, 1 << 20)
                    except (FileNotFoundError, NotADirectoryError):
                        missing.append(arcname)
                        report("backup", done, total, arcname)
                        continue
                    except OSError as exc:
                        if exc.errno != errno.ELOOP:  # ELOOP: a link now
                            raise
                        missing.append(arcname)
                        report("backup", done, total, arcname)
                        continue
                    stored = zf.getinfo(arcname).file_size  # the bytes actually stored, even if the file grew
                    expected[arcname] = stored
                    files.append({"path": arcname, "size": stored, "mtime": st.st_mtime})
                    report("backup", done, total, arcname)
                if part.files and len(files) == read_before:
                    missing.append(part.name)  # every file vanished: do not claim the part
                else:
                    written.append(part.name)
            if chosen and not written:
                raise BackupError("nothing could be read: the folders changed since the scan")
            manifest = {"version": MANIFEST_VERSION, "kind": kind, "flavor": flavor.short_name,
                        "flavor_folder": flavor.folder, "created": now_iso(), "suite_version": __version__,
                        "parts": written, "parts_existing": written, "files": files, "links": links}
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False))
        verify_backup(partial, expected, progress=lambda i, n, name: report("verify", i, n, name))
        rename_no_replace(partial, dest)  # never replaces an existing backup
        bytes_zip = dest.stat().st_size
    except BackupError:
        remove_quietly(partial)
        raise
    except (OSError, zipfile.BadZipFile, ValueError, RuntimeError) as exc:  # RuntimeError: a file grew past ZIP64
        remove_quietly(partial)
        raise BackupError(f"the backup failed: {exc}") from exc
    except BaseException:  # e.g. Ctrl+C while zipping: never leave a stray .partial behind
        remove_quietly(partial)
        raise
    return ZipStats(dest, len(files), sum(expected.values()), bytes_zip, missing, links, written)


def skip_reason(scan: FlavorScan) -> str | None:
    """Why a flavor has nothing to back up (no real Interface or WTF folder: missing, or links), or None."""
    if scan.has_data:
        return None
    linked = [name for name in PARTS if scan.parts[name].linked]
    if linked:
        return f"{' and '.join(linked)} {'is a link' if len(linked) == 1 else 'are links'} (not followed)"
    return "no Interface or WTF folder"


def back_up(scan: FlavorScan, root: Path, *, keep: int, now: datetime | None = None,
            progress: Progress | None = None) -> BackupOutcome:
    """One flavor: zip, verify, then prune its older backups (only after a success). Never raises BackupError."""
    flavor = scan.flavor
    reason = skip_reason(scan)
    if reason is not None:
        linked = [name for name in PARTS if scan.parts[name].linked]
        log_event("ibackup.backup_skipped", flavor=flavor.folder, reason=reason, links=linked)
        return BackupOutcome(flavor, "skipped", links=linked, reason=reason)
    dest = new_backup_path(root, flavor.short_name, now or datetime.now(), kind=BACKUP)
    try:
        stats = write_zip(scan, dest, kind=BACKUP, progress=progress)
    except BackupError as exc:
        log_event("ibackup.backup_failed", flavor=flavor.folder, path=to_stored(dest), error=str(exc))
        return BackupOutcome(flavor, "failed", reason=str(exc))
    log_event("ibackup.backup_created", flavor=flavor.folder, path=to_stored(stats.path), files=stats.files,
              bytes_in=stats.bytes_in, bytes_zip=stats.bytes_zip, missing=len(stats.missing),
              missing_sample=stats.missing[:SAMPLE])
    if stats.links:
        log_event("ibackup.links_skipped", flavor=flavor.folder, count=len(stats.links), sample=stats.links[:SAMPLE])
    safe_progress(progress)("prune", 0, 0, flavor.display_name)
    pruned = prune_backups(root, flavor.short_name, keep, protect=stats.path)  # never the zip just made
    if pruned:
        log_event("ibackup.pruned", flavor=flavor.folder, keep=keep, removed=[p.name for p in pruned])
    return BackupOutcome(flavor, "created", stats.path, stats.files, stats.bytes_in, stats.bytes_zip, stats.links,
                         stats.missing, "", pruned)


def back_up_all(scans: list[FlavorScan], root: Path, *, keep: int, progress: Progress | None = None,
                on_flavor: Callable[[str], None] | None = None) -> list[BackupOutcome]:
    """Each flavor in turn; one failing never stops the next. on_flavor(display name) before each one."""
    log_event("ibackup.backup_started", flavors=[s.flavor.folder for s in scans], dest=to_stored(root))
    announce = safe_progress(on_flavor)
    outcomes = []
    for scan in scans:
        announce(scan.flavor.display_name)
        outcomes.append(back_up(scan, root, keep=keep, progress=progress))
    return outcomes
