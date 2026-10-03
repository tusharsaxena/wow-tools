"""File planned screenshots into their date folders: guard, re-check, move or copy, journal.

Never overwrites. One listing per source folder and one names-only listing per target day folder; beyond that a
stat only where a hash, a copy or the no-overwrite check before a rename needs it. A dry run walks the same checks
(hashing included) and changes nothing."""
from __future__ import annotations

import errno
import hashlib
import os
import shutil
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from wowtools import __version__
from wowtools.core.events import log_event
from wowtools.core.paths import to_stored
from wowtools.tools.screenshot_organizer.journal import (A_COPIED, A_DUPLICATE, A_MOVED, A_SOURCE_LEFT, JournalWriter,
                                                         new_journal_path, prune_journals)
from wowtools.tools.screenshot_organizer.naming import day_parts, parse_shot_name
from wowtools.tools.screenshot_organizer.planner import CONFLICT, ShotItem, list_files, list_names
from wowtools.tools.screenshot_organizer.settings import source_dir, target_root

Progress = Callable[[str, int, int, str], None]
Rename = Callable[[Path, Path], None]
PARTIAL = ".partial"
CHUNK = 1024 * 1024

MOVED, COPIED, SOURCE_LEFT = "moved", "copied", "source_left"
DUPLICATE_REMOVED, ALREADY_FILED, CONFLICT_KEPT = "duplicate_removed", "already_filed", "conflict"
SKIPPED, REFUSED, FAILED = "skipped", "refused", "failed"
WOULD_MOVE, WOULD_COPY, WOULD_REMOVE_DUPLICATE = "would_move", "would_copy", "would_remove_duplicate"
RESTORED, COPY_REMOVED, UNDO_SKIPPED = "restored", "copy_removed", "undo_skipped"

_EVENTS = {MOVED: "shots.moved", COPIED: "shots.copied", SOURCE_LEFT: "shots.source_left",
           DUPLICATE_REMOVED: "shots.duplicate_removed", ALREADY_FILED: "shots.already_filed",
           CONFLICT_KEPT: "shots.conflict", SKIPPED: "shots.skipped", REFUSED: "shots.refused",
           FAILED: "shots.failed", WOULD_MOVE: "shots.would_file", WOULD_COPY: "shots.would_file",
           WOULD_REMOVE_DUPLICATE: "shots.would_file"}


@dataclass(frozen=True)
class Outcome:
    flavor: str
    src: Path
    dst: Path
    kind: str
    reason: str = ""


@dataclass
class OrganizeResult:
    dry_run: bool
    copy: bool
    outcomes: list[Outcome] = field(default_factory=list)
    journal_path: Path | None = None
    pruned: list[Path] = field(default_factory=list)
    undo: bool = False

    def of(self, kind: str) -> list[Outcome]:
        return [o for o in self.outcomes if o.kind == kind]

    def count(self, kind: str) -> int:
        return sum(1 for o in self.outcomes if o.kind == kind)

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for o in self.outcomes:
            result[o.kind] = result.get(o.kind, 0) + 1
        return result


class OrganizeError(Exception):
    """A run stopped unexpectedly. `result` holds what was done; the journal records it for Undo."""

    def __init__(self, message: str, result: OrganizeResult) -> None:
        super().__init__(message)
        self.result = result


class JournalWriteError(Exception):
    """A change was made but could not be journaled. `outcome` is that change; the run must stop, because
    every further change would be one Undo cannot reverse."""

    def __init__(self, outcome: "Outcome", cause: BaseException) -> None:
        super().__init__(f"the journal could not be written after {outcome.src.name} was {outcome.kind}: "
                         f"{type(cause).__name__}: {cause}")
        self.outcome = outcome


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def same_file_content(a: Path, b: Path) -> bool:
    return a.stat().st_size == b.stat().st_size and sha256_file(a) == sha256_file(b)


def copy_verified(src: Path, dst: Path) -> None:
    """Copy src to dst through <dst>.partial: copy bytes and times, check size and SHA-256, then rename into
    place. Refuses an existing dst. Raises OSError on any failure (the partial file is removed)."""
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, "target exists", str(dst))
    partial = dst.with_name(dst.name + PARTIAL)
    if os.path.lexists(partial):
        os.remove(partial)  # left over from an interrupted run; our own temporary name
    source_hash = hashlib.sha256()
    try:
        with src.open("rb") as reader, partial.open("xb") as writer:
            for chunk in iter(lambda: reader.read(CHUNK), b""):
                source_hash.update(chunk)
                writer.write(chunk)
        shutil.copystat(src, partial)
        if partial.stat().st_size != src.stat().st_size or sha256_file(partial) != source_hash.hexdigest():
            raise OSError(errno.EIO, "copy verification failed", str(dst))
        if os.path.lexists(dst):
            raise FileExistsError(errno.EEXIST, "target appeared during copy", str(dst))
        os.rename(partial, dst)
    except BaseException:
        try:
            os.remove(partial)
        except OSError:
            pass
        raise


def move_file(src: Path, dst: Path, rename: Rename = os.rename) -> bool:
    """Rename src to dst. Across devices (EXDEV), copy it verified instead and return True: the source is then
    still there and the caller deletes it."""
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, "target exists", str(dst))
    try:
        rename(src, dst)
        return False
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    copy_verified(src, dst)
    return True


def _guard(item: ShotItem, dest_dir: Path | None) -> str | None:
    if item.src.parent != source_dir(item.flavor):
        return "source is not directly in the flavor's Screenshots folder"
    day = parse_shot_name(item.src.name)
    if day is None or day != item.day:
        return "source name does not match the planned day"
    expected = target_root(item.flavor, dest_dir).joinpath(*day_parts(day), item.src.name)
    if item.dst != expected or ".." in item.dst.parts:
        return f"target is not {expected}"
    return None


def safe_progress(progress: Progress | None) -> Progress:
    def call(stage: str, current: int, total: int, detail: str = "") -> None:
        if progress is None:
            return
        try:
            progress(stage, current, total, detail)
        except Exception:  # noqa: BLE001 - a broken progress callback must never disturb a run
            pass
    return call


class _Run:
    def __init__(self, dest_dir: Path | None, copy: bool, dry_run: bool, journal: JournalWriter | None,
                 rename: Rename) -> None:
        self.dest_dir = dest_dir
        self.copy = copy
        self.dry_run = dry_run
        self.journal = journal
        self.rename = rename
        self.sources: dict[Path, dict[str, os.stat_result]] = {}
        self.targets: dict[Path, set[str]] = {}
        self.made: set[Path] = set()

    def _source_size(self, item: ShotItem) -> int | None:
        folder = item.src.parent
        if folder not in self.sources:
            self.sources[folder] = list_files(folder)
        st = self.sources[folder].get(item.src.name)
        return None if st is None else st.st_size

    def _target_exists(self, item: ShotItem) -> bool:
        folder = item.dst.parent
        if folder not in self.targets:
            self.targets[folder] = list_names(folder)
        # The listing is taken at execute time; move_file/copy_verified check once more right before writing.
        return item.dst.name in self.targets[folder]

    def _record(self, action: str, item: ShotItem, outcome: Outcome) -> Outcome:
        """Journal a change that has already happened. A journal failure is not a per-file error (the change
        is done): it raises JournalWriteError, which stops the run."""
        if self.journal is not None:
            try:
                self.journal.add(action, item.src, item.dst, item.size)
            except Exception as exc:  # noqa: BLE001 - OSError, or e.g. UnicodeEncodeError from an odd path
                note = f"not journaled ({type(exc).__name__}: {exc}); Undo cannot reverse it"
                reason = f"{outcome.reason}; {note}" if outcome.reason else note
                raise JournalWriteError(replace(outcome, reason=reason), exc) from exc
        return outcome

    def file_one(self, item: ShotItem) -> Outcome:
        def out(kind: str, reason: str = "") -> Outcome:
            return Outcome(item.flavor.folder, item.src, item.dst, kind, reason)

        refusal = _guard(item, self.dest_dir)
        if refusal:
            return out(REFUSED, refusal)
        if item.state == CONFLICT:
            return out(CONFLICT_KEPT, "a different file with this name is already at the target")
        size = self._source_size(item)
        if size is None:
            return out(SKIPPED, "missing since the scan")
        if size != item.size:
            return out(SKIPPED, "changed since the scan")
        if self._target_exists(item):
            if not same_file_content(item.src, item.dst):
                return out(CONFLICT_KEPT, "a different file with this name is already at the target")
            if self.copy:
                return out(ALREADY_FILED, "an identical file is already at the target")
            if self.dry_run:
                return out(WOULD_REMOVE_DUPLICATE, "identical file already at the target")
            os.remove(item.src)
            return self._record(A_DUPLICATE, item, out(DUPLICATE_REMOVED, "identical file already at the target"))
        if self.dry_run:
            return out(WOULD_COPY if self.copy else WOULD_MOVE)
        if item.dst.parent not in self.made:
            os.makedirs(item.dst.parent, exist_ok=True)
            self.made.add(item.dst.parent)
        try:
            if self.copy:
                copy_verified(item.src, item.dst)
            else:
                copied = move_file(item.src, item.dst, self.rename)
        except FileExistsError:
            return out(CONFLICT_KEPT, "a file with this name appeared at the target")
        if self.copy:
            self.targets.setdefault(item.dst.parent, set()).add(item.dst.name)
            return self._record(A_COPIED, item, out(COPIED))
        self.targets.setdefault(item.dst.parent, set()).add(item.dst.name)
        if copied:
            try:
                os.remove(item.src)
            except OSError as exc:
                return self._record(A_SOURCE_LEFT, item,
                                    out(SOURCE_LEFT, f"copied, but the source could not be deleted: {exc}"))
        return self._record(A_MOVED, item, out(MOVED))


def _log_outcome(result: OrganizeResult, outcome: Outcome, dry_run: bool) -> None:
    result.outcomes.append(outcome)
    log_event(_EVENTS[outcome.kind], dry_run=dry_run, flavor=outcome.flavor, src=str(outcome.src),
              dst=str(outcome.dst), reason=outcome.reason or None)


def execute(items: list[ShotItem], *, dest_dir: Path | None, copy: bool, dry_run: bool,
            journal_dir: Path | None, keep_journals: int, progress: Progress | None = None,
            rename: Rename = os.rename) -> OrganizeResult:
    report = safe_progress(progress)
    result = OrganizeResult(dry_run=dry_run, copy=copy)
    journal = None
    if not dry_run and journal_dir is not None:
        journal = JournalWriter(new_journal_path(journal_dir), {
            "started": datetime.now().astimezone().isoformat(timespec="seconds"), "copy": copy,
            "dest_dir": to_stored(dest_dir) if dest_dir else None, "suite_version": __version__,
            "flavors": sorted({i.flavor.folder for i in items})})
    log_event("shots.organize_started", dry_run=dry_run, copy=copy, files=len(items),
              dest_dir=str(dest_dir) if dest_dir else None)
    if journal is not None:
        try:
            journal.open()  # before anything is touched: no change is ever made that Undo cannot see
        except Exception as exc:  # noqa: BLE001
            log_event("shots.organize_stopped", error=f"{type(exc).__name__}: {exc}", done=0, journal=None)
            raise OrganizeError(f"The run journal could not be written, so nothing was filed: {exc}",
                                result) from exc
    run = _Run(dest_dir, copy, dry_run, journal, rename)
    total = len(items)
    try:
        for index, item in enumerate(items):
            report("organize", index, total, item.src.name)
            try:
                outcome = run.file_one(item)
            except JournalWriteError as exc:
                _log_outcome(result, exc.outcome, dry_run)
                raise
            except OSError as exc:
                outcome = Outcome(item.flavor.folder, item.src, item.dst, FAILED, str(exc))
            _log_outcome(result, outcome, dry_run)
        report("organize", total, total, "")
        if journal is not None:
            journal.finish()
    except (Exception, KeyboardInterrupt) as exc:
        if journal is not None:
            journal.discard_if_empty()
            result.journal_path = journal.path if journal.opened else None
        log_event("shots.organize_stopped", error=f"{type(exc).__name__}: {exc}", done=len(result.outcomes),
                  journal=str(result.journal_path) if result.journal_path else None)
        raise OrganizeError(f"The run stopped: {exc}", result) from exc
    finally:
        if journal is not None:
            journal.discard_if_empty()
    if journal is not None and journal.opened:
        result.journal_path = journal.path
        report("prune", 0, 0, "")
        result.pruned = prune_journals(journal_dir, keep_journals)
    counts = result.counts()
    log_event("shots.organize_completed", level="warning" if counts.get(FAILED) else None, dry_run=dry_run,
              copy=copy, counts=counts, journal=str(result.journal_path) if result.journal_path else None)
    return result
