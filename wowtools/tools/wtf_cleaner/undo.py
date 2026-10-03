"""Undo last clean: put back the files one clean deleted, from its run journal. UI-free.

Entries are restored newest first. A file that exists again is left alone. Otherwise it is extracted, exclusive
create, from the cleaned-files zip (by its name in that zip), or from the flavor's WTF backup by rel when there is
no zip or the zip lacks it; the restored size must match the entry. Undo never overwrites, never deletes anything
but a restore it had just started and could not finish, and never writes outside the flavors' WTF folders (rel must
start with WTF/ and contain no ..). The journal is marked undone afterwards.
"""
from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable

from wowtools.core.events import log_event
from wowtools.core.journal import mark_undone
from wowtools.tools.wtf_cleaner.journal import read_journal

RESTORED = "restored"
SKIPPED = "skipped"
FAILED = "failed"
UndoProgress = Callable[[str, int, int, str], None]
OUTSIDE = "outside the flavor's WTF folder"
BACK = "a file is back at this path"


@dataclass(frozen=True)
class UndoOutcome:
    flavor: str  # the flavor folder, e.g. _retail_
    path: Path  # where the file goes (or would go)
    rel: str  # its path inside the flavor folder (WTF/...)
    size: int
    status: str  # RESTORED, SKIPPED or FAILED
    detail: str = ""  # why it was skipped or failed
    source: str = ""  # "zip" (the cleaned-files zip) or "backup" (the WTF backup) for a restored file


@dataclass
class UndoResult:
    journal_path: Path
    started: str  # when the clean being undone started (its journal header)
    flavors: list[str]
    outcomes: list[UndoOutcome] = field(default_factory=list)
    dry_run: bool = False  # never a dry run: lets the result screen treat it like a clean result

    def _with(self, status: str) -> list[UndoOutcome]:
        return [o for o in self.outcomes if o.status == status]

    @property
    def restored(self) -> list[UndoOutcome]:
        return self._with(RESTORED)

    @property
    def skipped(self) -> list[UndoOutcome]:
        return self._with(SKIPPED)

    @property
    def failed(self) -> list[UndoOutcome]:
        return self._with(FAILED)


def _safe_progress(progress: UndoProgress | None) -> UndoProgress:
    def report(stage: str, current: int, total: int, detail: str = "") -> None:
        if progress is None:
            return
        try:
            progress(stage, current, total, detail)
        except Exception:  # noqa: BLE001 - a broken progress display must not stop the undo
            pass
    return report


def destination(wow_root: Path, flavor: str, rel: str) -> Path | None:
    """<WoW>/<flavor>/<rel>, or None when the entry points outside that flavor's WTF folder."""
    if not flavor or flavor in (".", "..") or "/" in flavor or "\\" in flavor or ":" in flavor:
        return None
    posix = PurePosixPath(rel)
    parts = posix.parts
    if posix.is_absolute() or len(parts) < 2 or parts[0] != "WTF" or ".." in parts or "\\" in rel or ":" in rel:
        return None
    return wow_root.joinpath(flavor, *parts)


class _Zips:
    """Opens each zip once (they are big and the drive can be slow) and remembers the ones that will not open.
    Also remembers which folders are known to exist, so each is checked or made once."""

    def __init__(self) -> None:
        self.open: dict[Path, zipfile.ZipFile | None] = {}
        self.folders: dict[Path, bool] = {}

    def is_dir(self, folder: Path) -> bool:
        if folder not in self.folders:
            self.folders[folder] = folder.is_dir()
        return self.folders[folder]

    def make_dir(self, folder: Path) -> None:
        if not self.folders.get(folder):
            folder.mkdir(parents=True, exist_ok=True)
            self.folders[folder] = True

    def entry(self, zip_path: Path | None, rel: str) -> tuple[zipfile.ZipFile, zipfile.ZipInfo] | None:
        if zip_path is None:
            return None
        if zip_path not in self.open:
            try:
                self.open[zip_path] = zipfile.ZipFile(zip_path)
            except (OSError, zipfile.BadZipFile):
                self.open[zip_path] = None
        zf = self.open[zip_path]
        if zf is None:
            return None
        try:
            return zf, zf.getinfo(rel)
        except KeyError:
            return None

    def close(self) -> None:
        for zf in self.open.values():
            if zf is not None:
                zf.close()


def _extract(zf: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path, size: int, mtime: float | None) -> str | None:
    """Write one entry to dest (exclusive create; its folder exists). Returns None on success, BACK if a file
    appeared at dest, or why it failed (a partial file this call created is removed)."""
    try:
        out = open(dest, "xb")
    except FileExistsError:
        return BACK
    written = 0
    try:
        with out, zf.open(info) as src:
            while chunk := src.read(1 << 20):
                out.write(chunk)
                written += len(chunk)
    except BaseException as exc:
        _remove(dest)
        if isinstance(exc, Exception):
            return f"could not be written: {exc}"
        raise
    if written != size:
        _remove(dest)
        return f"the restored size ({written} bytes) does not match the journal ({size} bytes)"
    if mtime is not None:
        try:
            os.utime(dest, (mtime, mtime))
        except OSError:
            pass  # restored all the same; only the file's time differs
    return None


def _restore_one(entry: dict, wow_root: Path, zips: _Zips) -> UndoOutcome:
    flavor, rel, size = entry["flavor"], entry["rel"], entry["size"]
    dest = destination(wow_root, flavor, rel)
    path = dest if dest is not None else Path(str(entry.get("path") or rel))

    def outcome(status: str, detail: str = "", source: str = "") -> UndoOutcome:
        return UndoOutcome(flavor, path, rel, size, status, detail, source)

    if dest is None:
        return outcome(SKIPPED, OUTSIDE)
    if not zips.is_dir(wow_root / flavor / "WTF"):
        return outcome(FAILED, f"{flavor}\\WTF is not there any more")
    if os.path.lexists(dest):
        return outcome(SKIPPED, BACK)
    mtime = entry.get("mtime")
    mtime = float(mtime) if isinstance(mtime, (int, float)) else None
    wrong_size = ""
    for source, zip_path in (("zip", entry.get("zip")), ("backup", entry.get("snapshot"))):
        found = zips.entry(zip_path if isinstance(zip_path, Path) else None, rel)
        if found is None:
            continue
        zf, info = found
        if info.file_size != size:
            wrong_size = (f"the size in {zip_path.name} ({info.file_size} bytes) does not match the journal "
                          f"({size} bytes)")
            continue
        zips.make_dir(dest.parent)
        problem = _extract(zf, info, dest, size, mtime)
        if problem is None:
            return outcome(RESTORED, source=source)
        return outcome(SKIPPED if problem == BACK else FAILED, problem)
    return outcome(FAILED, wrong_size or "neither the cleaned-files zip nor the WTF backup holds it (moved, "
                                         "deleted or unreadable)")


def undo_clean(journal_path: Path, *, wow_root: Path, progress: UndoProgress | None = None) -> UndoResult:
    """Undo the clean recorded in journal_path. Raises OSError/ValueError only if the journal cannot be read."""
    report = _safe_progress(progress)
    journal = read_journal(journal_path)
    flavors = [str(f) for f in journal.header.get("flavors") or []]
    result = UndoResult(journal_path, journal.started, flavors)
    entries = list(reversed(journal.entries))
    log_event("clean.undo_started", journal=str(journal_path), started=journal.started, flavors=flavors,
              entries=len(entries))
    zips = _Zips()
    try:
        for index, entry in enumerate(entries):
            report("undo", index, len(entries), entry["rel"])
            try:
                outcome = _restore_one(entry, wow_root, zips)
            except OSError as exc:
                outcome = UndoOutcome(entry["flavor"], Path(str(entry.get("path") or entry["rel"])), entry["rel"],
                                      entry["size"], FAILED, str(exc))
            result.outcomes.append(outcome)
            data = {"flavor": outcome.flavor, "path": outcome.rel, "size": outcome.size}
            if outcome.status == RESTORED:
                log_event("clean.undo_restored", source=outcome.source, **data)
            elif outcome.status == SKIPPED:
                log_event("clean.undo_skipped", reason=outcome.detail, **data)
            else:
                log_event("clean.undo_failed", error=outcome.detail, **data)
        report("undo", len(entries), len(entries), "")
    finally:
        zips.close()
    not_restored = len(result.skipped) + len(result.failed)
    mark_undone(journal_path, len(result.restored), not_restored)
    log_event("clean.undo_completed", level="warning" if not_restored else None, journal=str(journal_path),
              restored=len(result.restored), skipped=len(result.skipped), failed=len(result.failed))
    return result


def _remove(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
