"""Scan Screenshots folders and plan where each screenshot goes. Reads only: one listing per source folder and
one per target day folder, no per-file stat or resolve (slow on WSL drvfs)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from wowtools.core.events import log_event
from wowtools.core.install import Flavor
from wowtools.tools.screenshots.naming import day_parts, parse_shot_name
from wowtools.tools.screenshots.settings import source_dir, target_root

ScanProgress = Callable[[int, int, str], None]
NEW = "new"
MAYBE_DUPLICATE = "maybe_duplicate"  # a file of the same size is at the target; execute compares hashes
CONFLICT = "conflict"  # a file of another size is at the target: never touched
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


def scan(flavors: list[Flavor], dest_dir: Path | None, progress: ScanProgress | None = None) -> Plan:
    log_event("shots.scan_started", flavors=[f.folder for f in flavors],
              dest_dir=str(dest_dir) if dest_dir else None)
    plan = Plan([], dest_dir)
    targets: dict[Path, dict[str, os.stat_result]] = {}
    total = len(flavors)
    summary: dict[str, dict] = {}
    for index, flavor in enumerate(flavors):
        label = f"Reading {flavor.display_name} screenshots"
        if progress:
            progress(index, total, label)
        src_dir = source_dir(flavor)
        if not src_dir.is_dir():
            continue
        try:
            files = list_files(src_dir)
        except OSError as exc:
            plan.warnings.append(f"{src_dir}: {exc}")
            log_event("shots.scan_warning", path=str(src_dir), error=str(exc))
            continue
        root = target_root(flavor, dest_dir)
        fp = FlavorPlan(flavor, src_dir, root)
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
                    targets[day_dir] = list_files(day_dir)
                except OSError as exc:
                    plan.warnings.append(f"{day_dir}: {exc}")
                    log_event("shots.scan_warning", path=str(day_dir), error=str(exc))
                    targets[day_dir] = {}
            existing = targets[day_dir].get(name)
            state = NEW if existing is None else (MAYBE_DUPLICATE if existing.st_size == st.st_size else CONFLICT)
            fp.items.append(ShotItem(flavor, src_dir / name, day_dir / name, day, st.st_size, st.st_mtime, state))
        plan.flavors.append(fp)
        summary[flavor.folder] = {"to_file": len(fp.new), "maybe_duplicates": len(fp.maybe_duplicates),
                                  "conflicts": len(fp.conflicts), "unrecognised": len(fp.skipped),
                                  "unrecognised_sample": [s.path.name for s in fp.skipped[:SAMPLE]]}
    if progress:
        progress(total, total, "Done")
    log_event("shots.scan_completed", flavors=summary, warnings=len(plan.warnings))
    return plan
