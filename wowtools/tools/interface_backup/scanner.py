"""What a flavor's Interface and WTF folders hold: files (with sizes when cheap or asked for), links that are not
followed, and folders left by an interrupted restore. Directory listings only: never resolve(), never follow a
link. UI-free."""
from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.backup import walk_files
from wowtools.core.events import log_event
from wowtools.core.fsutil import is_link, safe_progress
from wowtools.core.install import Flavor
from wowtools.core.paths import to_stored

PARTS = ("Interface", "WTF")
STAGING_SUFFIXES = (".restoring", ".replaced")
# DirEntry.stat() comes free with the directory listing on Windows; over WSL drvfs it costs a disk round trip per
# file, so a summary scan there counts files only and leaves sizes unknown.
CHEAP_STATS = os.name == "nt"
SAMPLE = 20  # at most this many scan warnings logged per part

Progress = Callable[[str, int, int, str], None]


@dataclass(frozen=True)
class FileInfo:
    rel: str  # path inside the part folder, with forward slashes
    size: int | None  # None when the scan did not read sizes
    mtime: float | None


def _total(sizes: Iterable[int | None]) -> int | None:
    """The sum, or None when any size is unknown."""
    total = 0
    for size in sizes:
        if size is None:
            return None
        total += size
    return total


@dataclass
class PartScan:
    name: str  # "Interface" or "WTF"
    path: Path
    exists: bool = False  # a real folder (not a link) that was scanned
    linked: bool = False  # the part folder itself is a link: never backed up or restored
    files: list[FileInfo] = field(default_factory=list)
    links: list[str] = field(default_factory=list)  # rel paths of links inside, not followed
    errors: list[str] = field(default_factory=list)

    @property
    def size(self) -> int | None:
        return _total(f.size for f in self.files)


@dataclass
class FlavorScan:
    flavor: Flavor
    parts: dict[str, PartScan]
    leftovers: list[Path] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return sum(len(p.files) for p in self.parts.values())

    @property
    def link_count(self) -> int:
        return sum(len(p.links) for p in self.parts.values())

    @property
    def size(self) -> int | None:
        return _total(p.size for p in self.parts.values() if p.exists)

    @property
    def has_data(self) -> bool:
        return any(p.exists for p in self.parts.values())


def leftover_folders(flavor: Flavor) -> list[Path]:
    """<part>.restoring / <part>.replaced folders an interrupted restore left in the flavor folder."""
    candidates = (flavor.path / f"{part}{suffix}" for part in PARTS for suffix in STAGING_SUFFIXES)
    return [path for path in candidates if os.path.lexists(path)]


def _rel(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()  # lexical: both come from the same directory listing


def _reason(exc: OSError) -> str:
    return str(exc.strerror or exc)


def scan_part(path: Path, name: str, *, with_stats: bool, on_count: Callable[[int], None] | None = None) -> PartScan:
    """One part folder. A link as the part is reported and not scanned; an unreadable sub-folder is listed in
    `errors` and skipped."""
    part = PartScan(name, path)
    if is_link(path):
        part.linked = True
        part.errors.append(f"{name} is a link to another folder; it is not backed up or restored")
        return part
    if not path.is_dir():
        return part
    part.exists = True
    try:
        entries = walk_files(path, on_link=lambda p: part.links.append(_rel(p, path)),
                             on_error=lambda p, exc: part.errors.append(f"{to_stored(p)}: {_reason(exc)}"),
                             on_count=on_count)
    except OSError as exc:
        part.errors.append(f"{to_stored(path)}: {_reason(exc)}")
        return part
    for entry in entries:
        size = mtime = None
        if with_stats:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:  # vanished since the listing: not part of this scan
                part.errors.append(f"{to_stored(Path(entry.path))}: {_reason(exc)}")
                continue
            size, mtime = info.st_size, info.st_mtime
        part.files.append(FileInfo(_rel(Path(entry.path), path), size, mtime))
    return part


def scan_flavor(flavor: Flavor, *, with_stats: bool = CHEAP_STATS, parts: tuple[str, ...] = PARTS,
                progress: Progress | None = None) -> FlavorScan:
    """Scan the chosen parts of one flavor (a part not chosen is left empty, exists=False). Progress is
    progress("scan", files_found, 0, detail): at the start of each part, then every 100 files."""
    report = safe_progress(progress)
    scans: dict[str, PartScan] = {}
    for name in PARTS:
        if name not in parts:
            scans[name] = PartScan(name, flavor.path / name)
            continue
        label = f"{flavor.display_name}: {name}"
        report("scan", 0, 0, label)
        scans[name] = scan_part(flavor.path / name, name, with_stats=with_stats,
                                on_count=lambda n, label=label: report("scan", n, 0, f"{label} ({n} files)"))
    return FlavorScan(flavor, scans, leftover_folders(flavor))


def scan_flavors(flavors: list[Flavor], *, with_stats: bool = CHEAP_STATS,
                 progress: Progress | None = None) -> list[FlavorScan]:
    """Scan each flavor and log what was found."""
    log_event("ibackup.scan_started", flavors=[f.folder for f in flavors], with_stats=with_stats)
    scans = []
    for flavor in flavors:
        scan = scan_flavor(flavor, with_stats=with_stats, progress=progress)
        for part in scan.parts.values():
            for error in part.errors[:SAMPLE]:
                log_event("ibackup.scan_warning", flavor=flavor.folder, part=part.name, error=error)
            if len(part.errors) > SAMPLE:
                log_event("ibackup.scan_warning", flavor=flavor.folder, part=part.name,
                          error=f"{len(part.errors) - SAMPLE} more not logged")
        for path in scan.leftovers:
            log_event("ibackup.leftover_found", flavor=flavor.folder, path=to_stored(path))
        log_event("ibackup.scan_completed", flavor=flavor.folder,
                  parts={p.name: {"exists": p.exists, "linked": p.linked, "files": len(p.files), "bytes": p.size,
                                  "links": len(p.links)}
                         for p in scan.parts.values()})
        scans.append(scan)
    return scans
