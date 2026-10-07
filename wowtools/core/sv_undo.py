"""Undo the latest Apply of a SavedVariables-editing tool, and recover from one that did not finish (Ace3 spec §10,
SV Browser spec D15). UI-free; the tool brings its name and event prefix (SvTool).

A file is put back from the edited-*.zip only when it is still byte-for-byte what the run wrote (sha_after); a file
WoW (or anything else) saved since is skipped and never overwritten. Undo and recovery are refused while that
flavor's WoW runs, refuse locked files, and take a whole-WTF snapshot of each flavor first (Undo: several flavors
up to [general] parallelism at once, core/parallel.py).
"""
from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PureWindowsPath

from wowtools.core.backup import BackupError
from wowtools.core.events import log_event
from wowtools.core.fsutil import atomic_write_bytes, safe_progress
from wowtools.core.install import Flavor
from wowtools.core.journal import mark_undone
from wowtools.core.parallel import run_units
from wowtools.core.paths import to_stored
from wowtools.core.snapshot import prune_snapshots, take_snapshot
from wowtools.core.sv_apply import (EDITED_SUBDIR, SNAPSHOT_PREFIX, SNAPSHOT_SUBDIR, Marker, UndoError, WowRunning,
                                    clear_marker, refuse_running)
from wowtools.core.sv_events import SvTool
from wowtools.core.sv_journal import read_edit_journal, record_recovered
from wowtools.core.svfiles import find_locked, locked_message
from wowtools.core.undo import FAILED, RESTORED, SKIPPED, UndoResultBase, safe_destination

__all__ = ["CHANGED_SINCE", "UndoError", "UndoOutcome", "UndoResult", "WowRunning", "destination", "recover",
           "undo_flavors", "undo_run"]

CHANGED_SINCE = "changed since the change was made (WoW may have saved it); left as it is"


@dataclass
class UndoOutcome:
    flavor: str
    rel: str
    path: Path | None
    status: str
    detail: str = ""


@dataclass
class UndoResult(UndoResultBase):
    outcomes: list[UndoOutcome] = field(default_factory=list)
    journal_path: Path | None = None
    snapshots: list[Path] = field(default_factory=list)


def destination(wow_root: Path, flavor: str, rel: str) -> Path | None:
    """<WoW>/<flavor>/<rel> when rel is WTF/Account/.../SavedVariables/<file>; None for anything else."""
    return safe_destination(wow_root, flavor, rel, prefix=("WTF", "Account"), min_parts=5, parent="SavedVariables")


def undo_flavors(wow_root: Path, entries: Iterable[dict]) -> list[Flavor]:
    """The flavors Undo backs up, sorted: only those with an entry whose destination passed safe_destination, so a
    crafted flavor ("../x") is never zipped or pruned (STD-5.25). The Undo popup builds its rows from the same list."""
    return [Flavor(folder, wow_root / folder)
            for folder in sorted({e["flavor"] for e in entries if destination(wow_root, e["flavor"], e["rel"])})]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _current_sha(path: Path) -> str | None:
    try:
        return _sha(path.read_bytes())
    except OSError:
        return None


def _moved_zip(zip_path: Path, root: Path) -> Path:
    """zip_path, or the zip of that name in root's edited folder when zip_path is gone and that one is there: the
    tool's folder was moved (renamed) after the journal or marker recorded the path."""
    if zip_path.exists():
        return zip_path
    moved = root / EDITED_SUBDIR / PureWindowsPath(zip_path).name  # either separator: a path from the other OS
    return moved if moved.exists() else zip_path


def _put_back(zip_path: Path, rel: str, dest: Path, sha_before: str) -> str | None:
    """Write the original bytes of rel from zip_path over dest. Returns a problem, or None when done."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            original = zf.read(rel)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        return f"its original could not be read from {zip_path.name}: {exc}"
    if _sha(original) != sha_before:
        return f"the copy in {zip_path.name} is not the original"
    try:
        atomic_write_bytes(dest, original)
    except OSError as exc:
        return f"could not be written: {exc.strerror or exc}"
    return None


def _refuse_locked(tool: SvTool, targets: list[tuple[str, Path | None]], action: str) -> None:
    """UndoError when a file to put back is held by another program (RaiderIO, WeakAuras Companion)."""
    locked = find_locked([(rel, dest) for rel, dest in targets if dest is not None and dest.exists()],
                         lambda exc: UndoError(f"{exc} Nothing was changed."))
    if locked:
        log_event(tool.event("file_locked"), action=action, files=len(locked))
        raise UndoError(locked_message(locked, "try"))


def _snapshot(tool: SvTool, flavor: Flavor, root: Path, now: datetime | None, report, action: str) -> Path:
    try:
        return take_snapshot(flavor, root / SNAPSHOT_SUBDIR, SNAPSHOT_PREFIX, now or datetime.now(), progress=report)
    except BackupError as exc:
        log_event(tool.event("snapshot_failed"), flavor=flavor.folder, error=str(exc))
        raise UndoError(f"The WTF backup before {action} failed ({exc}). Nothing was changed.") from exc


def _prune(tool: SvTool, flavors: list[Flavor], root: Path, keep_snapshots: int | None) -> None:
    """Keep only the newest keep_snapshots WTF backups of each flavor, as Apply does."""
    if keep_snapshots is None:
        return
    for flavor in flavors:
        pruned = prune_snapshots(root / SNAPSHOT_SUBDIR, SNAPSHOT_PREFIX, flavor.short_name, keep_snapshots)
        if pruned:
            log_event(tool.event("snapshots_pruned"), flavor=flavor.folder, removed=[p.name for p in pruned])


def _snapshots(tool: SvTool, flavors: list[Flavor], root: Path, now: datetime | None, report, parallelism: int,
               on_flavor: Callable[[Flavor], None] | None,
               on_flavor_done: Callable[[Flavor], None] | None) -> list[Path]:
    """Each flavor's whole-WTF snapshot before Undo, up to `parallelism` at once: every snapshot is its own zip of
    its own flavor's WTF folder. The first that fails (in flavor order) is raised once the running ones ended; the
    flavors not started by then never start, so with parallelism 1 it stops where the serial loop did. The
    snapshots that were made are deleted then: nothing was changed, so they protect nothing, and no prune follows
    a failed Undo to keep them within keep_backups."""
    started, ended = safe_progress(on_flavor), safe_progress(on_flavor_done)
    results = run_units(flavors, lambda flavor, _report: _snapshot(tool, flavor, root, now, report, "undo"),
                        parallelism=parallelism, what=tool.event("undo_snapshot"), label=lambda flavor: flavor.folder,
                        on_start=lambda flavor, _index, _total: started(flavor),
                        on_done=lambda result: ended(result.unit), stop_on_error=True)
    made = [result.value for result in results if result.value is not None]
    failed = next((result.error for result in results if result.error is not None), None)
    if failed is not None:
        for path in made:
            try:
                path.unlink()
            except OSError:
                continue  # left for the next prune
            log_event(tool.event("snapshot_discarded"), path=path.name)
        raise failed
    return made


def undo_run(tool: SvTool, journal_path: Path, *, wow_root: Path, root: Path, keep_snapshots: int,
             wow_check: Callable[[], list[str] | None] | None = None, now: datetime | None = None,
             progress: Callable[[str, int, int, str], None] | None = None, parallelism: int = 1,
             on_flavor: Callable[[Flavor], None] | None = None,
             on_flavor_done: Callable[[Flavor], None] | None = None) -> UndoResult:
    """Put back the files of the journal's run that are still what it wrote. The WTF snapshots come first, up to
    `parallelism` flavors at once; on_flavor(flavor) runs in the snapshot's thread before it starts (its progress
    reports then come from that thread) and on_flavor_done(flavor) once it ended. The files are put back after
    every snapshot succeeded, in this thread; a snapshot that failed means nothing was changed (UndoError)."""
    report = safe_progress(progress)
    journal = read_edit_journal(journal_path)
    entries = list(reversed(journal.entries))
    log_event(tool.event("undo_started"), journal=journal_path.name, files=len(entries))
    refuse_running(tool, wow_check, "undo", "files")
    targets = [(e, destination(wow_root, e["flavor"], e["rel"])) for e in entries]
    _refuse_locked(tool, [(entry["rel"], dest) for entry, dest in targets], "undo")
    result = UndoResult(journal_path=journal_path)
    flavors = undo_flavors(wow_root, entries)
    result.snapshots.extend(_snapshots(tool, flavors, root, now, report, parallelism, on_flavor, on_flavor_done))
    skipped = tool.event("file_skipped")
    for index, (entry, dest) in enumerate(targets, 1):
        rel, flavor = entry["rel"], entry["flavor"]
        report("undo", index, len(targets), rel)
        if dest is None:
            result.outcomes.append(UndoOutcome(flavor, rel, None, SKIPPED, "it is outside the WTF folder"))
            log_event(skipped, flavor=flavor, path=rel, reason="outside")
            continue
        try:
            current = dest.read_bytes()
        except OSError:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, SKIPPED, "the file is gone"))
            log_event(skipped, flavor=flavor, path=rel, reason="gone")
            continue
        if _sha(current) != entry["sha_after"]:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, SKIPPED, CHANGED_SINCE))
            log_event(skipped, flavor=flavor, path=rel, reason="changed")
            continue
        problem = _put_back(_moved_zip(entry["zip"], root), rel, dest, entry["sha_before"])
        if problem is None:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, RESTORED))
            log_event(tool.event("file_restored"), flavor=flavor, path=rel)
        else:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, FAILED, problem))
            log_event(tool.event("undo_failed"), flavor=flavor, path=rel, error=problem)
    if result.restored or not result.failed:
        mark_undone(journal_path, len(result.restored), len(result.skipped))
    _prune(tool, flavors, root, keep_snapshots)
    level_bad = result.skipped or result.failed
    log_event(tool.event("undo_completed"), restored=len(result.restored), skipped=len(result.skipped),
              failed=len(result.failed), level="warning" if level_bad else None)
    return result


def _marker_flavor(marker: Marker, wow_root: Path) -> Flavor:
    """The marker's flavor as a folder of wow_root. UndoError (nothing changed) when its name is not one plain
    folder name, or that folder is not in wow_root (another WoW folder is configured now)."""
    if destination(wow_root, marker.flavor, "WTF/Account/x/SavedVariables/x.lua") is None:
        raise UndoError("The unfinished change names a game version folder that is not valid. Nothing was changed.")
    flavor = Flavor(marker.flavor, wow_root / marker.flavor)
    if not flavor.path.is_dir():
        raise UndoError(f"{marker.flavor} is not in the WoW folder {to_stored(wow_root)}. Nothing was changed.")
    return flavor


def recover(tool: SvTool, marker: Marker, *, wow_root: Path, root: Path, journal_dir: Path | None = None,
            keep_snapshots: int | None = None, wow_check: Callable[[], list[str] | None] | None = None,
            now: datetime | None = None, progress: Callable[[str, int, int, str], None] | None = None) -> UndoResult:
    """After an Apply that did not finish: put back every file of the marker that is still what the run wrote.
    A file still at its original is left alone; one that is neither (the run skipped it as changed since the scan,
    or WoW saved it since) is skipped and never overwritten. As Undo: refused while that flavor's WoW runs or a
    file is locked, and the flavor's WTF folder is backed up first (when there is something to put back), then
    pruned to keep_snapshots. The files now at their original get a rolled_back entry in the run's journal (in
    journal_dir), so Undo does not offer them again.

    Every file resolves under wow_root, the configured WoW folder, never under the marker's own flavor_path: a
    marker written on the other OS (Windows or WSL) names a folder this process cannot open, and a hand-edited one
    could name any folder (STD-4.4, STD-5.25). A marker whose flavor is not a folder in wow_root is refused
    (UndoError) and kept, so nothing is cleared for files that were never looked at."""
    report = safe_progress(progress)
    flavor = _marker_flavor(marker, wow_root)
    refuse_running(tool, wow_check, "recover", "files")
    targets = {rel: destination(wow_root, marker.flavor, rel) for rel in marker.files}
    _refuse_locked(tool, sorted(targets.items()), "recover")
    result = UndoResult()
    original: list[str] = []
    if any(dest is not None and _current_sha(dest) == marker.after.get(rel) for rel, dest in targets.items()):
        result.snapshots.append(_snapshot(tool, flavor, root, now, report, "recovery"))
    skipped = tool.event("file_skipped")
    for index, (rel, sha_before) in enumerate(sorted(marker.files.items()), 1):
        report("undo", index, len(marker.files), rel)
        dest = targets[rel]
        if dest is None:
            result.outcomes.append(UndoOutcome(marker.flavor, rel, None, SKIPPED, "it is outside the WTF folder"))
            log_event(skipped, flavor=marker.flavor, path=rel, reason="outside")
            continue
        current = _current_sha(dest)
        if current == sha_before:
            original.append(rel)
            continue
        if current is None or current != marker.after.get(rel):
            detail = "the file is gone or could not be read" if current is None else CHANGED_SINCE
            result.outcomes.append(UndoOutcome(marker.flavor, rel, dest, SKIPPED, detail))
            log_event(skipped, flavor=marker.flavor, path=rel, reason="gone" if current is None else "changed")
            continue
        problem = _put_back(_moved_zip(marker.zip, root), rel, dest, sha_before)
        status = RESTORED if problem is None else FAILED
        result.outcomes.append(UndoOutcome(marker.flavor, rel, dest, status, problem or ""))
        log_event(tool.event("file_restored" if problem is None else "undo_failed"), flavor=marker.flavor, path=rel)
    back = original + [o.rel for o in result.restored]
    if back:
        record_recovered(journal_dir, marker.flavor, marker.zip.name, back)
    if result.snapshots:
        _prune(tool, [flavor], root, keep_snapshots)
    if not result.failed:
        clear_marker(root)
    log_event(tool.event("recovery_done"), choice="put_back", restored=len(result.restored),
              skipped=len(result.skipped), failed=len(result.failed))
    return result
