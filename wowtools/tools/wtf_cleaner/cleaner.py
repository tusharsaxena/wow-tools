"""Execute a selection: guard, recheck, safety snapshot, back up (verified), then delete.

A dry run writes the backup but takes no snapshot and deletes nothing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from wowtools import __version__
from wowtools.core.backup import BackupEntry, BackupError, backup_filename, create_backup
from wowtools.core.events import log_event
from wowtools.core.install import Flavor
from wowtools.tools.wtf_cleaner.events import TOOL_NAME
from wowtools.tools.wtf_cleaner.rules import ProposalItem
from wowtools.tools.wtf_cleaner.safety import (MARKER_NAME, Marker, clear_marker, read_marker, remove_snapshot,
                                               restore_deleted, take_snapshot, write_marker)
from wowtools.tools.wtf_cleaner.scanner import SVFile

CleanProgress = Callable[[str, int, int, str], None]


class CleanError(Exception):
    """The clean was refused or stopped. `restored` lists files put back from the snapshot, if any."""

    restored: list[str] = []


@dataclass(frozen=True)
class FileOutcome:
    path: Path
    size: int
    status: str
    detail: str = ""
    reasons: tuple[str, ...] = ()


@dataclass
class CleanResult:
    dry_run: bool
    backup_path: Path | None
    outcomes: list[FileOutcome] = field(default_factory=list)
    snapshot_path: Path | None = None  # the safety snapshot used; already removed when the result is returned
    restored: list[str] = field(default_factory=list)

    def _with(self, status: str) -> list[FileOutcome]:
        return [o for o in self.outcomes if o.status == status]

    @property
    def deleted(self) -> list[FileOutcome]:
        return self._with("deleted")

    @property
    def would_delete(self) -> list[FileOutcome]:
        return self._with("would_delete")

    @property
    def skipped(self) -> list[FileOutcome]:
        return self._with("skipped")

    @property
    def failed(self) -> list[FileOutcome]:
        return self._with("failed")

    @property
    def bytes_freed(self) -> int:
        return sum(o.size for o in self.outcomes if o.status in ("deleted", "would_delete"))


def _guard(path: Path, flavor: Flavor) -> None:
    root = flavor.account_dir.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise CleanError(f"Refusing to touch {path}: it is outside {flavor.account_dir}") from None
    if resolved.parent.name != "SavedVariables":
        raise CleanError(f"Refusing to touch {path}: it is not inside a SavedVariables folder")


def _recheck(sv: SVFile) -> str | None:
    try:
        stat = sv.path.stat()
    except OSError:
        return "missing"
    if stat.st_size != sv.size or stat.st_mtime != sv.mtime:
        return "changed"
    return None


def _relative(path: Path, flavor: Flavor) -> str:
    try:
        return path.relative_to(flavor.path).as_posix()
    except ValueError:
        return str(path)


def _safe_progress(progress: CleanProgress | None) -> CleanProgress:
    """Wrap a progress callback so an error inside it can never disturb (or roll back) a clean."""
    def report(stage: str, current: int, total: int, detail: str = "") -> None:
        if progress is None:
            return
        try:
            progress(stage, current, total, detail)
        except Exception:  # noqa: BLE001 - a broken progress display must not stop the clean
            pass
    return report


def _discard_safety(backup_dir: Path, snapshot: Path) -> None:
    remove_snapshot(snapshot)
    clear_marker(backup_dir)


def _take_safety_snapshot(flavor: Flavor, backup_dir: Path | None, now: datetime, rels: list[str],
                          report: CleanProgress) -> Path:
    """Snapshot the whole WTF folder and write the in-progress marker. Raises BackupError (nothing deleted)."""
    if backup_dir is None:
        log_event("snapshot.failed", flavor=flavor.folder, error="no backup folder is configured")
        raise BackupError("no backup folder is configured (the safety snapshot needs one)")
    earlier = read_marker(backup_dir)
    if earlier is not None:
        # Starting a new clean would overwrite the only pointer to the earlier snapshot.
        log_event("snapshot.failed", flavor=flavor.folder, error="an earlier clean did not finish",
                  earlier_snapshot=str(earlier.snapshot))
        raise BackupError(f"an earlier clean (started {earlier.started}) did not finish. Its safety snapshot is "
                          f"kept at {earlier.snapshot}. Dismiss that notice in the TUI (the snapshot is kept) or "
                          f"delete {backup_dir / MARKER_NAME}, then clean again.")
    try:
        snapshot = take_snapshot(flavor, backup_dir, now, progress=report)
    except BackupError as exc:
        log_event("snapshot.failed", flavor=flavor.folder, error=str(exc))
        raise
    log_event("snapshot.created", flavor=flavor.folder, zip=str(snapshot), bytes=snapshot.stat().st_size)
    marker = Marker(snapshot=snapshot, flavor=flavor.folder, flavor_path=flavor.path,
                    started=now.isoformat(timespec="seconds"), pid=os.getpid(), suite_version=__version__,
                    files=rels)
    try:
        write_marker(backup_dir, marker)
    except OSError as exc:
        _discard_safety(backup_dir, snapshot)
        log_event("snapshot.failed", flavor=flavor.folder, error=f"could not write the clean marker: {exc}")
        raise BackupError(f"could not write the clean marker: {exc}") from exc
    except BaseException:  # interrupted before deleting anything: the snapshot is not needed
        _discard_safety(backup_dir, snapshot)
        raise
    return snapshot


def _restore_after(exc: BaseException, snapshot: Path, backup_dir: Path, flavor: Flavor,
                   deleted: list[str]) -> CleanError:
    """An unexpected error stopped the deleting: put back what this run deleted. Returns the error to raise."""
    reason = str(exc) or type(exc).__name__
    try:
        restored = restore_deleted(snapshot, flavor, deleted)
    except Exception as restore_exc:  # noqa: BLE001 - any failure keeps the marker and the snapshot
        log_event("restore.failed", flavor=flavor.folder, snapshot=str(snapshot), files=len(deleted),
                  reason=reason, error=str(restore_exc))
        return CleanError(f"Clean stopped ({reason}) and restoring the {len(deleted)} deleted files failed "
                          f"({restore_exc}). The safety snapshot is kept at {snapshot}: close WoW, then unzip "
                          f"it into {flavor.path} to restore.")
    log_event("restore.completed", flavor=flavor.folder, snapshot=str(snapshot), restored=len(restored),
              reason=reason, files=restored)
    clear_marker(backup_dir)
    error = CleanError(f"Clean stopped ({reason}); {len(restored)} deleted files were restored from {snapshot}")
    error.restored = restored
    return error


def execute(items: list[ProposalItem], flavor: Flavor, *, dry_run: bool, backup: bool,
            backup_dir: Path | None, now: datetime | None = None,
            progress: CleanProgress | None = None) -> CleanResult:
    now = now or datetime.now()
    report = _safe_progress(progress)
    selected = [(item, sv) for item in items for sv in item.files]
    log_event("clean.started", dry_run=dry_run, flavor=flavor.folder, items=len(items), files=len(selected),
              bytes=sum(sv.size for _, sv in selected), backup=backup)
    for _, sv in selected:
        _guard(sv.path, flavor)

    result = CleanResult(dry_run=dry_run, backup_path=None)
    ready: list[tuple[ProposalItem, SVFile]] = []
    for item, sv in selected:
        problem = _recheck(sv)
        if problem:
            result.outcomes.append(FileOutcome(sv.path, sv.size, "skipped", problem, tuple(item.reasons)))
            log_event("sv.skipped", dry_run=dry_run, path=_relative(sv.path, flavor), reason=problem)
        else:
            ready.append((item, sv))

    snapshot: Path | None = None
    if not dry_run and ready:
        snapshot = _take_safety_snapshot(flavor, backup_dir, now, [_relative(sv.path, flavor) for _, sv in ready],
                                         report)
        result.snapshot_path = snapshot

    try:
        if backup and ready:
            _selective_backup(result, ready, flavor, backup_dir, now, dry_run, report)
    except BaseException:
        if snapshot is not None and backup_dir is not None:
            _discard_safety(backup_dir, snapshot)  # nothing was deleted, so the snapshot is not needed
        raise

    deleted: list[str] = []
    try:
        for index, (item, sv) in enumerate(ready, 1):
            _delete_one(result, item, sv, flavor, dry_run, deleted)
            report("delete", index, len(ready), _relative(sv.path, flavor))
    except BaseException as exc:
        if snapshot is None or backup_dir is None:
            raise
        raise _restore_after(exc, snapshot, backup_dir, flavor, deleted) from exc

    if snapshot is not None and backup_dir is not None:
        _discard_safety(backup_dir, snapshot)
        log_event("snapshot.removed", flavor=flavor.folder, zip=str(snapshot))

    log_event("clean.completed", dry_run=dry_run, level="warning" if result.failed else None,
              deleted=len(result.deleted), would_delete=len(result.would_delete),
              skipped=len(result.skipped), failed=len(result.failed), bytes=result.bytes_freed,
              backup=str(result.backup_path) if result.backup_path else None)
    return result


def _selective_backup(result: CleanResult, ready: list[tuple[ProposalItem, SVFile]], flavor: Flavor,
                      backup_dir: Path | None, now: datetime, dry_run: bool, report: CleanProgress) -> None:
    if backup_dir is None:
        raise BackupError("no backup folder is configured")
    dest = backup_dir / backup_filename(TOOL_NAME, flavor.short_name, now)
    ready_bytes = sum(sv.size for _, sv in ready)
    meta = {"tool": TOOL_NAME, "suite_version": __version__, "flavor": flavor.folder,
            "created": now.isoformat(timespec="seconds")}
    try:
        create_backup([BackupEntry(sv.path, tuple(item.reasons)) for item, sv in ready],
                      flavor.path, dest, meta, on_file=lambda i, n, name: report("backup", i, n, name))
    except BackupError as exc:
        log_event("backup.failed", dry_run=dry_run, zip=str(dest), error=str(exc))
        raise
    report("verify", 1, 1, dest.name)  # create_backup verified the zip before moving it into place
    log_event("backup.created", dry_run=dry_run, zip=str(dest), files=len(ready), bytes=ready_bytes,
              verified=True)
    result.backup_path = dest


def _delete_one(result: CleanResult, item: ProposalItem, sv: SVFile, flavor: Flavor, dry_run: bool,
                deleted: list[str]) -> None:
    rel = _relative(sv.path, flavor)
    data = {"flavor": flavor.folder, "account": item.account,
            "character": item.owner_label if item.character else None,
            "path": rel, "size": sv.size, "reasons": item.reasons}
    if dry_run:
        result.outcomes.append(FileOutcome(sv.path, sv.size, "would_delete", "", tuple(item.reasons)))
        log_event("sv.would_delete", dry_run=True, **data)
        return
    # Recorded before unlinking so an interruption right after the unlink still restores it; restoring
    # skips any file that is still on disk, so a file that was not deleted is never touched.
    deleted.append(rel)
    try:
        sv.path.unlink()
    except OSError as exc:
        deleted.pop()
        result.outcomes.append(FileOutcome(sv.path, sv.size, "failed", str(exc), tuple(item.reasons)))
        log_event("sv.failed", path=rel, error=str(exc))
        return
    result.outcomes.append(FileOutcome(sv.path, sv.size, "deleted", "", tuple(item.reasons)))
    log_event("sv.deleted", dry_run=False, **data)
