"""Undo the latest Apply, and recover from one that did not finish (spec §10). UI-free.

A file is put back from the edited-*.zip only when it is still byte-for-byte what the run wrote (sha_after); a file
WoW (or anything else) saved since is skipped and never overwritten. Undo is refused while WoW runs, refuses locked
files, and takes a whole-WTF snapshot of each flavor first.
"""
from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from wowtools.core.backup import BackupError
from wowtools.core.events import log_event
from wowtools.core.fsutil import atomic_write_bytes, safe_progress
from wowtools.core.install import Flavor
from wowtools.core.journal import mark_undone
from wowtools.core.snapshot import take_snapshot
from wowtools.core.svfiles import SvFileError, probe_lock
from wowtools.tools.ace_profiles.editor import SNAPSHOT_PREFIX, SNAPSHOT_SUBDIR, Marker, clear_marker
from wowtools.tools.ace_profiles.journal import read_profile_journal

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
class UndoResult:
    outcomes: list[UndoOutcome] = field(default_factory=list)
    journal_path: Path | None = None
    snapshots: list[Path] = field(default_factory=list)

    def _with(self, status: str) -> list[UndoOutcome]:
        return [o for o in self.outcomes if o.status == status]

    @property
    def restored(self) -> list[UndoOutcome]:
        return self._with("restored")

    @property
    def skipped(self) -> list[UndoOutcome]:
        return self._with("skipped")

    @property
    def failed(self) -> list[UndoOutcome]:
        return self._with("failed")


def destination(wow_root: Path, flavor: str, rel: str) -> Path | None:
    """<WoW>/<flavor>/<rel> when rel is WTF/Account/.../SavedVariables/<file>; None for anything else."""
    pure = PurePosixPath(rel)
    parts = pure.parts
    if pure.is_absolute() or ".." in parts or len(parts) < 5 or parts[:2] != ("WTF", "Account") \
            or parts[-2] != "SavedVariables" or "/" in flavor or "\\" in flavor or flavor in ("", ".", ".."):
        return None
    return wow_root.joinpath(flavor, *parts)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def undo_run(journal_path: Path, *, wow_root: Path, root: Path, keep_snapshots: int,
             wow_check: Callable[[], list[str] | None] | None = None, now: datetime | None = None,
             progress: Callable[[str, int, int, str], None] | None = None) -> UndoResult:
    report = safe_progress(progress)
    journal = read_profile_journal(journal_path)
    entries = list(reversed(journal.entries))
    log_event("ace.undo_started", journal=journal_path.name, files=len(entries))
    if wow_check is not None:
        running = wow_check()
        if running:
            log_event("ace.wow_running", action="undo", running=running)
            raise WowRunning(running)
    targets = [(e, destination(wow_root, e["flavor"], e["rel"])) for e in entries]
    locked = []
    for entry, dest in targets:
        if dest is not None and dest.exists():
            try:
                error = probe_lock(dest)
            except SvFileError as exc:
                raise UndoError(f"{exc} Nothing was changed.") from exc
            if error is not None:
                locked.append(f"{entry['rel']} ({error})")
    if locked:
        log_event("ace.file_locked", action="undo", files=len(locked))
        raise UndoError(f"{len(locked)} files are locked by another program. Close it and undo again.\n  "
                        + "\n  ".join(locked[:10]))
    result = UndoResult(journal_path=journal_path)
    for folder in sorted({e["flavor"] for e in entries}):
        try:
            result.snapshots.append(take_snapshot(Flavor(folder, wow_root / folder), root / SNAPSHOT_SUBDIR,
                                                  SNAPSHOT_PREFIX, now or datetime.now(), progress=report))
        except BackupError as exc:
            log_event("ace.snapshot_failed", flavor=folder, error=str(exc))
            raise UndoError(f"The WTF backup before undo failed ({exc}). Nothing was changed.") from exc
    for index, (entry, dest) in enumerate(targets, 1):
        rel, flavor = entry["rel"], entry["flavor"]
        report("undo", index, len(targets), rel)
        if dest is None:
            result.outcomes.append(UndoOutcome(flavor, rel, None, "skipped", "it is outside the WTF folder"))
            log_event("ace.file_skipped", flavor=flavor, path=rel, reason="outside")
            continue
        try:
            current = dest.read_bytes()
        except OSError:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, "skipped", "the file is gone"))
            log_event("ace.file_skipped", flavor=flavor, path=rel, reason="gone")
            continue
        if _sha(current) != entry["sha_after"]:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, "skipped", CHANGED_SINCE))
            log_event("ace.file_skipped", flavor=flavor, path=rel, reason="changed")
            continue
        problem = _put_back(entry["zip"], rel, dest, entry["sha_before"])
        if problem is None:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, "restored"))
            log_event("ace.file_restored", flavor=flavor, path=rel)
        else:
            result.outcomes.append(UndoOutcome(flavor, rel, dest, "failed", problem))
            log_event("ace.undo_failed", flavor=flavor, path=rel, error=problem)
    if result.restored or not result.failed:
        mark_undone(journal_path, len(result.restored), len(result.skipped))
    level_bad = result.skipped or result.failed
    log_event("ace.undo_completed", restored=len(result.restored), skipped=len(result.skipped),
              failed=len(result.failed), level="warning" if level_bad else None)
    return result


def recover(marker: Marker, *, root: Path) -> UndoResult:
    """After an Apply that did not finish: put back every file of the marker that is still what the run wrote.
    A file still at its original is left alone; one that is neither (the run skipped it as changed since the scan,
    or WoW saved it since) is skipped and never overwritten."""
    result = UndoResult()
    for rel, sha_before in sorted(marker.files.items()):
        dest = destination(marker.flavor_path.parent, marker.flavor, rel)
        if dest is None:
            result.outcomes.append(UndoOutcome(marker.flavor, rel, None, "skipped", "it is outside the WTF folder"))
            log_event("ace.file_skipped", flavor=marker.flavor, path=rel, reason="outside")
            continue
        try:
            current = _sha(dest.read_bytes())
        except OSError:
            current = None
        if current == sha_before:
            continue
        if current is None or current != marker.after.get(rel):
            detail = "the file is gone or could not be read" if current is None else CHANGED_SINCE
            result.outcomes.append(UndoOutcome(marker.flavor, rel, dest, "skipped", detail))
            log_event("ace.file_skipped", flavor=marker.flavor, path=rel,
                      reason="gone" if current is None else "changed")
            continue
        problem = _put_back(marker.zip, rel, dest, sha_before)
        status = "restored" if problem is None else "failed"
        result.outcomes.append(UndoOutcome(marker.flavor, rel, dest, status, problem or ""))
        log_event("ace.file_restored" if problem is None else "ace.undo_failed", flavor=marker.flavor, path=rel)
    if not result.failed:
        clear_marker(root)
    log_event("ace.recovery_done", choice="put_back", restored=len(result.restored), skipped=len(result.skipped),
              failed=len(result.failed))
    return result
