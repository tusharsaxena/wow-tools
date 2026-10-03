"""Scan Screenshots folders and plan where each screenshot goes. Reads only: one listing per source folder and
one names-only listing per target day folder; a stat only for a name already at the target, no resolve (slow on
WSL drvfs)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from wowtools.core.events import log_event
from wowtools.core.install import Flavor
from wowtools.tools.screenshot_organizer.naming import day_parts, parse_shot_name
from wowtools.tools.screenshot_organizer.settings import source_dir, target_root

ScanProgress = Callable[[int, int, str], None]
NEW = "new"
MAYBE_DUPLICATE = "maybe_duplicate"  # a file of the same size is at the target; execute compares hashes
CONFLICT = "conflict"  # a file of another size is at the target: never touched
# Copy mode only: the original stays in Screenshots, and a file of the same size and modified time (copies keep
# it) is already at the target. Not waiting: listed as already filed and unticked; execute still compares hashes
# if it is ticked.
FILED = "filed"
SAME_TIME_S = 2.0  # FAT/exFAT drives store modified times in 2-second steps
UNRECOGNISED = "name not recognised"
TICK = 500  # progress tick every N files inside one folder
SAMPLE = 20


@dataclass(frozen=True)
class ShotItem:
    flavor: Flavor
    src: Path
    dst: Path
    day: date
    size: int
    mtime: float
    state: str


@dataclass(frozen=True)
class Skipped:
    flavor: Flavor
    path: Path
    reason: str


@dataclass
class FlavorPlan:
    flavor: Flavor
    source_dir: Path
    target_root: Path
    items: list[ShotItem] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    missing: bool = False  # the flavor has no Screenshots folder: listed, but nothing to do
    error: str | None = None  # the Screenshots folder could not be read

    def _state(self, state: str) -> list[ShotItem]:
        return [i for i in self.items if i.state == state]

    @property
    def new(self) -> list[ShotItem]:
        return self._state(NEW)

    @property
    def maybe_duplicates(self) -> list[ShotItem]:
        return self._state(MAYBE_DUPLICATE)

    @property
    def conflicts(self) -> list[ShotItem]:
        return self._state(CONFLICT)

    @property
    def filed(self) -> list[ShotItem]:
        return self._state(FILED)

    @property
    def to_file(self) -> list[ShotItem]:
        """What is waiting to be filed: the selectable items minus those already filed (copy mode)."""
        return [i for i in self.items if i.state not in (CONFLICT, FILED)]

    @property
    def selectable(self) -> list[ShotItem]:
        return [i for i in self.items if i.state != CONFLICT]


@dataclass
class Plan:
    flavors: list[FlavorPlan]
    dest_dir: Path | None
    warnings: list[str] = field(default_factory=list)

    @property
    def items(self) -> list[ShotItem]:
        return [i for fp in self.flavors for i in fp.items]

    @property
    def selectable(self) -> list[ShotItem]:
        return [i for fp in self.flavors for i in fp.selectable]

    @property
    def to_file(self) -> list[ShotItem]:
        return [i for fp in self.flavors for i in fp.to_file]

    @property
    def filed(self) -> list[ShotItem]:
        return [i for fp in self.flavors for i in fp.filed]

    @property
    def skipped(self) -> list[Skipped]:
        return [s for fp in self.flavors for s in fp.skipped]


def list_files(folder: Path) -> dict[str, os.stat_result]:
    """name -> stat for the regular files directly in folder ({} if it does not exist)."""
    files: dict[str, os.stat_result] = {}
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False):
                    files[entry.name] = entry.stat(follow_symlinks=False)
    except FileNotFoundError:
        return {}
    return files


def list_names(folder: Path) -> set[str]:
    """Names of the regular files directly in folder (set() if it does not exist). No stat per entry: the type
    comes from the directory listing itself."""
    try:
        with os.scandir(folder) as entries:
            return {entry.name for entry in entries if entry.is_file(follow_symlinks=False)}
    except FileNotFoundError:
        return set()


def waiting_count(flavor: Flavor, dest_dir: Path | None = None, *, copy: bool = False) -> int | None:
    """How many screenshots are waiting in a flavor's Screenshots folder (top level only: files already in date
    folders are filed), or None if it has no Screenshots folder. One listing, no stat. In copy mode the originals
    stay where they are, so a name already at its target is not waiting (an earlier copy, or a conflict that is
    never filed): one names-only listing per target day folder as well."""
    folder = source_dir(flavor)
    if not folder.is_dir():
        return None
    try:
        shots = [(name, day) for name in list_names(folder) if (day := parse_shot_name(name)) is not None]
        if not copy:
            return len(shots)
        root = target_root(flavor, dest_dir)
        targets: dict[Path, set[str]] = {}
        count = 0
        for name, day in shots:
            day_dir = root.joinpath(*day_parts(day))
            if day_dir not in targets:
                targets[day_dir] = list_names(day_dir)
            count += name not in targets[day_dir]
        return count
    except OSError:
        return None


def _same_copy(src: os.stat_result, dst: os.stat_result) -> bool:
    return src.st_size == dst.st_size and abs(src.st_mtime - dst.st_mtime) <= SAME_TIME_S


def scan(flavors: list[Flavor], dest_dir: Path | None, progress: ScanProgress | None = None, *,
         copy: bool = False) -> Plan:
    log_event("shots.scan_started", flavors=[f.folder for f in flavors],
              dest_dir=str(dest_dir) if dest_dir else None, copy=copy)
    plan = Plan([], dest_dir)
    targets: dict[Path, set[str]] = {}
    total = len(flavors)
    summary: dict[str, dict] = {}
    for index, flavor in enumerate(flavors):
        label = f"Reading {flavor.display_name} screenshots"
        if progress:
            progress(index, total, label)
        src_dir = source_dir(flavor)
        root = target_root(flavor, dest_dir)
        fp = FlavorPlan(flavor, src_dir, root)
        plan.flavors.append(fp)  # every chosen flavor is listed, even with nothing to do
        if not src_dir.is_dir():
            fp.missing = True
            summary[flavor.folder] = {"missing": True}
            continue
        try:
            files = list_files(src_dir)
        except OSError as exc:
            fp.error = str(exc)
            plan.warnings.append(f"{src_dir}: {exc}")
            log_event("shots.scan_warning", path=str(src_dir), error=str(exc))
            continue
        for count, name in enumerate(sorted(files, key=str.casefold), start=1):
            if progress and count % TICK == 0:
                progress(index, total, f"{label}: {count} files")
            st = files[name]
            day = parse_shot_name(name)
            if day is None:
                fp.skipped.append(Skipped(flavor, src_dir / name, UNRECOGNISED))
                continue
            day_dir = root.joinpath(*day_parts(day))
            if day_dir not in targets:
                try:
                    targets[day_dir] = list_names(day_dir)
                except OSError as exc:
                    plan.warnings.append(f"{day_dir}: {exc}")
                    log_event("shots.scan_warning", path=str(day_dir), error=str(exc))
                    targets[day_dir] = set()
            state = NEW
            if name in targets[day_dir]:  # stat only the names already at the target, not the whole day folder
                try:
                    existing = os.stat(day_dir / name, follow_symlinks=False)
                except FileNotFoundError:
                    existing = None
                if existing is not None:
                    if existing.st_size != st.st_size:
                        state = CONFLICT
                    elif copy and _same_copy(st, existing):
                        state = FILED
                    else:
                        state = MAYBE_DUPLICATE
            fp.items.append(ShotItem(flavor, src_dir / name, day_dir / name, day, st.st_size, st.st_mtime, state))
        summary[flavor.folder] = {"to_file": len(fp.new), "maybe_duplicates": len(fp.maybe_duplicates),
                                  "conflicts": len(fp.conflicts), "already_filed": len(fp.filed), "unrecognised": len(fp.skipped),
                                  "unrecognised_sample": [s.path.name for s in fp.skipped[:SAMPLE]]}
    if progress:
        progress(total, total, "Done")
    log_event("shots.scan_completed", flavors=summary, warnings=len(plan.warnings))
    return plan
