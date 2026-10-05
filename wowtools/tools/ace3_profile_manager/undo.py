"""Undo the latest Apply, and recover from one that did not finish (spec §10). UI-free.

A file is put back from the edited-*.zip only when it is still byte-for-byte what the run wrote (sha_after); a file
WoW (or anything else) saved since is skipped and never overwritten. Undo and recovery are refused while that
flavor's WoW runs, refuse locked files, and take a whole-WTF snapshot of each flavor first.
"""
from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from wowtools.core.backup import BackupError
from wowtools.core.events import log_event
from wowtools.core.fsutil import atomic_write_bytes, safe_progress
from wowtools.core.install import Flavor
from wowtools.core.journal import mark_undone
from wowtools.core.snapshot import prune_snapshots, take_snapshot
from wowtools.core.svfiles import SvFileError, probe_lock
from wowtools.core.undo import FAILED, RESTORED, SKIPPED, UndoResultBase, safe_destination
from wowtools.tools.ace3_profile_manager.editor import (EDITED_SUBDIR, SNAPSHOT_PREFIX, SNAPSHOT_SUBDIR, Marker,
                                                        clear_marker)
from wowtools.tools.ace3_profile_manager.journal import read_profile_journal, record_recovered

CHANGED_SINCE = "changed since the change was made (WoW may have saved it); left as it is"


class UndoError(Exception):
    pass


class WowRunning(UndoError):
    def __init__(self, running: list[str]) -> None:
        super().__init__("WoW is running: " + ", ".join(running) + ". Close it first; it would overwrite the files.")
        self.running = running


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


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _current_sha(path: Path) -> str | None:
    try:
        return _sha(path.read_bytes())
    except OSError:
        return None


def _moved_zip(zip_path: Path, root: Path) -> Path:
    """zip_path, or the zip of that name in root's edited folder when zip_path is gone and that one is there: the
    tool's folder was moved (renamed from ace-profiles) after the journal or marker recorded the path."""
    if zip_path.exists():
        return zip_path
    moved = root / EDITED_SUBDIR / zip_path.name
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


def _refuse_running(wow_check: Callable[[], list[str] | None] | None, action: str) -> None:
    """WowRunning when the check finds that flavor's WoW: it would overwrite the files put back at logout."""
    if wow_check is None:
        return
    running = wow_check()
    if running:
        log_event("ace.wow_running", action=action, running=running)
        raise WowRunning(running)


def _refuse_locked(targets: list[tuple[str, Path | None]], action: str) -> None:
    """UndoError when a file to put back is held by another program (RaiderIO, WeakAuras Companion)."""
    locked = []
    for rel, dest in targets:
        if dest is not None and dest.exists():
            try:
                error = probe_lock(dest)
            except SvFileError as exc:
                raise UndoError(f"{exc} Nothing was changed.") from exc
            if error is not None:
                locked.append(f"{rel} ({error})")
    if locked:
        log_event("ace.file_locked", action=action, files=len(locked))
        raise UndoError(f"{len(locked)} files are locked by another program. Close it and try again.\n  "
                        + "\n  ".join(locked[:10]))


def _snapshot(flavor: Flavor, root: Path, now: datetime | None, report, action: str) -> Path:
    try:
        return take_snapshot(flavor, root / SNAPSHOT_SUBDIR, SNAPSHOT_PREFIX, now or datetime.now(), progress=report)
    except BackupError as exc:
        log_event("ace.snapshot_failed", flavor=flavor.folder, error=str(exc))
        raise UndoError(f"The WTF backup before {action} failed ({exc}). Nothing was changed.") from exc


def _prune(flavors: list[Flavor], root: Path, keep_snapshots: int | None) -> None:
    """Keep only the newest keep_snapshots WTF backups of each flavor, as Apply does."""
    if keep_snapshots is None:
        return
    for flavor in flavors:
        pruned = prune_snapshots(root / SNAPSHOT_SUBDIR, SNAPSHOT_PREFIX, flavor.short_name, keep_snapshots)
        if pruned:
            log_event("ace.snapshots_pruned", flavor=flavor.folder, removed=[p.name for p in pruned])


def undo_run(journal_path: Path, *, wow_root: Path, root: Path, keep_snapshots: int,
             wow_check: Callable[[], list[str] | None] | None = None, now: datetime | None = None,
             progress: Callable[[str, int, int, str], None] | None = None) -> UndoResult:
    report = safe_progress(progress)
    journal = read_profile_journal(journal_path)
    entries = list(reversed(journal.entries))
    log_event("ace.undo_started", journal=journal_path.name, files=len(entries))
    _refuse_running(wow_check, "undo")
    targets = [(e, destination(wow_root, e["flavor"], e["rel"])) for e in entries]
    _refuse_locked([(entry["rel"], dest) for entry, dest in targets], "undo")
    result = UndoResult(journal_path=journal_path)
    flavors = [Flavor(folder, wow_root / folder) for folder in sorted({e["flavor"] for e in entries})]
    for flavor in flavors:
        result.snapshots.append(_snapshot(flavor, root, now, report, "undo"))
    for index, (entry, dest) in enumerate(targets, 1):
        rel, flavor = entry["rel"], entry["flavor"]
        report("undo", index, len(targets), rel)
        if dest is None:
            result.outcomes.append(UndoOutcome(flavor, rel, None, SKIPPED, "it is outside the WTF folder"))
            log_event("ace.file_skipped", flavor=flavor, path=rel, reason="outside")
            continue
        try:
            current = dest.read_bytes()
        except OSError:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, SKIPPED, "the file is gone"))
            log_event("ace.file_skipped", flavor=flavor, path=rel, reason="gone")
            continue
        if _sha(current) != entry["sha_after"]:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, SKIPPED, CHANGED_SINCE))
            log_event("ace.file_skipped", flavor=flavor, path=rel, reason="changed")
            continue
        problem = _put_back(_moved_zip(entry["zip"], root), rel, dest, entry["sha_before"])
        if problem is None:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, RESTORED))
            log_event("ace.file_restored", flavor=flavor, path=rel)
        else:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, FAILED, problem))
            log_event("ace.undo_failed", flavor=flavor, path=rel, error=problem)
    if result.restored or not result.failed:
        mark_undone(journal_path, len(result.restored), len(result.skipped))
    _prune(flavors, root, keep_snapshots)
    level_bad = result.skipped or result.failed
    log_event("ace.undo_completed", restored=len(result.restored), skipped=len(result.skipped),
              failed=len(result.failed), level="warning" if level_bad else None)
    return result


def recover(marker: Marker, *, root: Path, journal_dir: Path | None = None, keep_snapshots: int | None = None,
            wow_check: Callable[[], list[str] | None] | None = None,
            now: datetime | None = None, progress: Callable[[str, int, int, str], None] | None = None) -> UndoResult:
    """After an Apply that did not finish: put back every file of the marker that is still what the run wrote.
    A file still at its original is left alone; one that is neither (the run skipped it as changed since the scan,
    or WoW saved it since) is skipped and never overwritten. As Undo: refused while that flavor's WoW runs or a
    file is locked, and the flavor's WTF folder is backed up first (when there is something to put back), then
    pruned to keep_snapshots. The files now at their original get a rolled_back entry in the run's journal (in
    journal_dir), so Undo does not offer them again."""
    report = safe_progress(progress)
    _refuse_running(wow_check, "recover")
    targets = {rel: destination(marker.flavor_path.parent, marker.flavor, rel) for rel in marker.files}
    _refuse_locked(sorted(targets.items()), "recover")
    result = UndoResult()
    original: list[str] = []
    if any(dest is not None and _current_sha(dest) == marker.after.get(rel) for rel, dest in targets.items()):
        result.snapshots.append(_snapshot(Flavor(marker.flavor, marker.flavor_path), root, now, report, "recovery"))
    for index, (rel, sha_before) in enumerate(sorted(marker.files.items()), 1):
        report("undo", index, len(marker.files), rel)
        dest = targets[rel]
        if dest is None:
            result.outcomes.append(UndoOutcome(marker.flavor, rel, None, SKIPPED, "it is outside the WTF folder"))
            log_event("ace.file_skipped", flavor=marker.flavor, path=rel, reason="outside")
            continue
        current = _current_sha(dest)
        if current == sha_before:
            original.append(rel)
            continue
        if current is None or current != marker.after.get(rel):
            detail = "the file is gone or could not be read" if current is None else CHANGED_SINCE
            result.outcomes.append(UndoOutcome(marker.flavor, rel, dest, SKIPPED, detail))
            log_event("ace.file_skipped", flavor=marker.flavor, path=rel,
                      reason="gone" if current is None else "changed")
            continue
        problem = _put_back(_moved_zip(marker.zip, root), rel, dest, sha_before)
        status = RESTORED if problem is None else FAILED
        result.outcomes.append(UndoOutcome(marker.flavor, rel, dest, status, problem or ""))
        log_event("ace.file_restored" if problem is None else "ace.undo_failed", flavor=marker.flavor, path=rel)
    back = original + [o.rel for o in result.restored]
    if back:
        record_recovered(journal_dir, marker.flavor, marker.zip.name, back)
    if result.snapshots:
        _prune([Flavor(marker.flavor, marker.flavor_path)], root, keep_snapshots)
    if not result.failed:
        clear_marker(root)
    log_event("ace.recovery_done", choice="put_back", restored=len(result.restored), skipped=len(result.skipped),
              failed=len(result.failed))
    return result
