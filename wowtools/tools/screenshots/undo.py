"""Undo one run from its journal: newest entry first, and only when everything still matches what the journal
recorded. Never overwrites. Afterwards, empty YYYY/MM/DD folders the run filed into are removed."""
from __future__ import annotations

import os
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.tools.screenshots.journal import (A_COPIED, A_DUPLICATE, A_MOVED, A_SOURCE_LEFT, mark_undone,
                                                read_journal)
from wowtools.tools.screenshots.organizer import (COPY_REMOVED, FAILED, RESTORED, UNDO_SKIPPED, OrganizeResult,
                                                  Outcome, Progress, Rename, copy_verified, move_file,
                                                  safe_progress)
from wowtools.tools.screenshots.settings import SCREENSHOTS_DIR

_DATE_PARTS = (4, 2, 2)  # YYYY, MM, DD


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size if path.is_file() else None
    except OSError:
        return None


def _guard(src: Path, dst: Path, wow_root: Path) -> str | None:
    if src.parent.name != SCREENSHOTS_DIR or src.parent.parent.parent != wow_root:
        return "outside the WoW folder or not a date folder"
    parts = dst.parts
    if (len(parts) < 4 or parts[-1] != src.name or ".." in parts
            or not all(p.isdigit() and len(p) == n for p, n in zip(parts[-4:-1], _DATE_PARTS))):
        return "outside the WoW folder or not a date folder"
    return None


def _undo_one(entry: dict, wow_root: Path, rename: Rename) -> tuple[str, str]:
    src, dst, size, action = entry["src"], entry["dst"], entry["size"], entry["action"]
    refusal = _guard(src, dst, wow_root)
    if refusal:
        return UNDO_SKIPPED, refusal
    if action == A_MOVED:
        if _size(dst) != size:
            return UNDO_SKIPPED, "the filed copy is missing or was changed"
        if os.path.lexists(src):
            return UNDO_SKIPPED, "a file with this name is back in the Screenshots folder"
        if move_file(dst, src, rename):
            try:
                os.remove(dst)
            except OSError as exc:  # the screenshot is back; only the archive copy stayed behind
                return RESTORED, f"put back, but the filed copy could not be deleted: {exc}"
        return RESTORED, ""
    if action in (A_COPIED, A_SOURCE_LEFT):
        if _size(src) != size:
            return UNDO_SKIPPED, "the original is missing or was changed, so the copy is kept"
        if _size(dst) != size:
            return UNDO_SKIPPED, "the copy is missing or was changed"
        os.remove(dst)
        return COPY_REMOVED, ""
    if action == A_DUPLICATE:
        if os.path.lexists(src):
            return UNDO_SKIPPED, "a file with this name is back in the Screenshots folder"
        if _size(dst) != size:
            return UNDO_SKIPPED, "the filed copy is missing or was changed"
        copy_verified(dst, src)
        return RESTORED, ""
    return UNDO_SKIPPED, f"unknown action {action!r}"


def _prune_date_folders(day_dirs: set[Path]) -> None:
    for day_dir in sorted(day_dirs, key=lambda p: len(p.parts), reverse=True):
        folder = day_dir
        for length in reversed(_DATE_PARTS):  # DD, MM, YYYY
            if not (folder.name.isdigit() and len(folder.name) == length):
                break
            try:
                os.rmdir(folder)
            except OSError:
                break  # not empty (or gone): stop climbing
            folder = folder.parent


def undo(journal_path: Path, *, wow_root: Path, progress: Progress | None = None,
         rename: Rename = os.rename) -> OrganizeResult:
    report = safe_progress(progress)
    journal = read_journal(journal_path)
    result = OrganizeResult(dry_run=False, copy=bool(journal.header.get("copy")), journal_path=journal_path,
                            undo=True)
    entries = list(reversed(journal.entries))
    log_event("shots.undo_started", journal=str(journal_path), entries=len(entries))
    day_dirs: set[Path] = set()
    for index, entry in enumerate(entries):
        report("undo", index, len(entries), entry["dst"].name)
        flavor = entry["src"].parent.parent.name
        try:
            kind, reason = _undo_one(entry, wow_root, rename)
        except OSError as exc:
            kind, reason = FAILED, str(exc)
        if kind in (RESTORED, COPY_REMOVED):
            day_dirs.add(entry["dst"].parent)
        result.outcomes.append(Outcome(flavor, entry["src"], entry["dst"], kind, reason))
        event = {RESTORED: "shots.undo_restored", COPY_REMOVED: "shots.undo_restored",
                 UNDO_SKIPPED: "shots.undo_skipped"}.get(kind, "shots.undo_failed")
        log_event(event, action=entry["action"], src=str(entry["src"]), dst=str(entry["dst"]), reason=reason or None)
    report("undo", len(entries), len(entries), "")
    _prune_date_folders(day_dirs)
    restored = result.count(RESTORED) + result.count(COPY_REMOVED)
    skipped = result.count(UNDO_SKIPPED) + result.count(FAILED)
    mark_undone(journal_path, restored, skipped)
    log_event("shots.undo_completed", level="warning" if skipped else None, journal=str(journal_path),
              restored=restored, skipped=skipped)
    return result
