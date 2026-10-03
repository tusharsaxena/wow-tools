"""Execute a selection: guard, recheck, back up the WTF folder, zip the files to clean (verified), delete, then
check the result.

A dry run writes the backup but takes no snapshot and deletes nothing. A real clean given a run journal opens it
(header written) before anything else, so a journal that cannot be written stops the clean with nothing deleted,
and journals each file right after deleting it.
"""
from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from wowtools import __version__
from wowtools.core.backup import BackupEntry, BackupError, create_backup
from wowtools.core.events import log_event
from wowtools.core.fsutil import free_name, rename_no_replace
from wowtools.core.install import Flavor
from wowtools.tools.wtf_cleaner.events import TOOL_NAME
from wowtools.tools.wtf_cleaner.journal import CleanJournal
from wowtools.tools.wtf_cleaner.rules import ProposalItem
from wowtools.tools.wtf_cleaner.safety import (DEFAULT_KEEP_SNAPSHOTS, MARKER_NAME, Marker, check_clean, clear_marker,
                                               prune_snapshots, read_marker, restore_deleted, take_snapshot,
                                               write_marker)
from wowtools.tools.wtf_cleaner.scanner import SVFile

CleanProgress = Callable[[str, int, int, str], None]
CLEANED_SUBDIR = "cleaned"
ALL_ACCOUNTS_LABEL = "all"


class CleanError(Exception):
    """The clean was refused or stopped. `restored` lists files put back from the snapshot, if any.
    `files_missing` is True when files were deleted and could not be put back (restore from the WTF backup)."""

    restored: list[str] = []
    files_missing: bool = False


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
    snapshot_path: Path | None = None  # the backup of the whole WTF folder taken before deleting (kept)
    restored: list[str] = field(default_factory=list)
    check_problems: list[str] = field(default_factory=list)  # what the post-clean check found ([] = passed)
    pruned: list[Path] = field(default_factory=list)  # older WTF backups removed to keep the newest N
    journal_path: Path | None = None  # the run journal this clean wrote to (set by execute_flavors)

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


class _Guard:
    """Refuses any path outside <flavor>/WTF/Account or not directly inside a SavedVariables folder.

    Resolving a path is slow on some drives (about 13ms per file on a Windows drive under WSL), so the account
    folder is resolved once and each parent folder once. A file that is itself a link is resolved in full.
    """

    def __init__(self, flavor: Flavor) -> None:
        self.flavor = flavor
        self.root = flavor.account_dir.resolve()
        self.parents: dict[Path, Path] = {}

    def check(self, path: Path, info: os.stat_result | None) -> None:
        if info is not None and stat.S_ISLNK(info.st_mode):
            resolved = path.resolve()
        else:
            parent = self.parents.get(path.parent)
            if parent is None:
                parent = self.parents[path.parent] = path.parent.resolve()
            resolved = parent / path.name
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise CleanError(f"Refusing to touch {path}: it is outside {self.flavor.account_dir}") from None
        if resolved.parent.name != "SavedVariables":
            raise CleanError(f"Refusing to touch {path}: it is not inside a SavedVariables folder")


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except OSError:
        return None


def _recheck(sv: SVFile, info: os.stat_result | None) -> str | None:
    if info is not None and stat.S_ISLNK(info.st_mode):
        info = _lstat(sv.path.resolve())
    if info is None:
        return "missing"
    if info.st_size != sv.size or info.st_mtime != sv.mtime:
        return "changed"
    return None


LOCK_PROBE_SUFFIX = ".wowtools-lockcheck"


def _probe_lock(path: Path) -> str | None:
    """Rename the file aside and straight back. Windows refuses the rename exactly when another process holds the
    file open without allowing deletion, so a failure here means the delete would fail too. Returns the error, or
    None if the file can be deleted (or is gone, which the recheck already reported)."""
    aside = path.with_name(path.name + LOCK_PROBE_SUFFIX)
    try:
        rename_no_replace(path, aside)
    except (FileNotFoundError, FileExistsError):
        return None  # gone (the recheck reported it), or never overwrite anything; the delete reports real problems
    except OSError as exc:
        return exc.strerror or str(exc)
    for attempt in range(5):
        try:
            rename_no_replace(aside, path)
            return None
        except OSError as exc:
            if attempt == 4 or isinstance(exc, FileExistsError):  # a new file at path: never replace it
                raise CleanError(f"Could not put {path.name} back after a lock check ({exc}). It is at {aside}: "
                                 f"rename it back to {path.name}. Nothing was deleted.") from exc
            time.sleep(0.1)
    return None


def _refuse_locked(ready: list[tuple[ProposalItem, SVFile]], flavor: Flavor, report: CleanProgress) -> None:
    """A real clean stops before the snapshot if any selected file is locked by another process."""
    locked: list[tuple[str, str]] = []
    for index, (_, sv) in enumerate(ready, 1):
        rel = _relative(sv.path, flavor)
        error = _probe_lock(sv.path)
        if error is not None:
            locked.append((rel, error))
        report("lock_check", index, len(ready), rel)
    if locked:
        log_event("clean.locked", flavor=flavor.folder, files=len(locked), details=[r for r, _ in locked[:20]])
        names = "\n".join(f"  {rel} ({error})" for rel, error in locked[:10])
        more = f"\n  …and {len(locked) - 10} more" if len(locked) > 10 else ""
        raise CleanError(f"{len(locked)} files are locked by another program (the Raider.IO client and WeakAuras "
                         f"Companion are known to do this). Close it and clean again.\n{names}{more}")


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


def _take_safety_snapshot(flavor: Flavor, backup_dir: Path | None, now: datetime, rels: list[str],
                          report: CleanProgress) -> Path:
    """Snapshot the whole WTF folder and write the in-progress marker. Raises BackupError (nothing deleted)."""
    if backup_dir is None:
        log_event("snapshot.failed", flavor=flavor.folder, error="no backup folder is configured")
        raise BackupError("no backup folder is configured (the WTF backup needs one)")
    earlier = read_marker(backup_dir)
    if earlier is not None:
        # Starting a new clean would overwrite the only pointer to the earlier snapshot.
        log_event("snapshot.failed", flavor=flavor.folder, error="an earlier clean did not finish",
                  earlier_snapshot=str(earlier.snapshot))
        raise BackupError(f"an earlier clean (started {earlier.started}) did not finish. The WTF backup taken "
                          f"before it is at {earlier.snapshot}. Dismiss that notice (the backup is kept) or "
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
        clear_marker(backup_dir)  # the backup itself stays: it is a good backup, nothing was deleted
        log_event("snapshot.failed", flavor=flavor.folder, error=f"could not write the clean marker: {exc}")
        raise BackupError(f"could not write the clean marker: {exc}") from exc
    except BaseException:  # interrupted before deleting anything
        clear_marker(backup_dir)
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
        error = CleanError(f"Clean stopped ({reason}) and restoring the {len(deleted)} deleted files failed "
                           f"({restore_exc}). The WTF backup is at {snapshot}: close WoW, then unzip "
                           f"it into {flavor.path} to restore.")
        error.files_missing = bool(deleted)
        return error
    log_event("restore.completed", flavor=flavor.folder, snapshot=str(snapshot), restored=len(restored),
              reason=reason, files=restored)
    clear_marker(backup_dir)
    error = CleanError(f"Clean stopped ({reason}); {len(restored)} deleted files were restored from {snapshot}")
    error.restored = restored
    return error


def execute(items: list[ProposalItem], flavor: Flavor, *, dry_run: bool, backup: bool,
            backup_dir: Path | None, now: datetime | None = None, progress: CleanProgress | None = None,
            account: str | None = None, keep_backups: int = DEFAULT_KEEP_SNAPSHOTS,
            journal: CleanJournal | None = None) -> CleanResult:
    """account is the scope of the clean (None = all accounts); it names the cleaned-files zip. journal (real
    cleans) is the run journal: opened before anything is touched, one entry after each delete."""
    now = now or datetime.now()
    report = _safe_progress(progress)
    selected = [(item, sv) for item in items for sv in item.files]
    log_event("clean.started", dry_run=dry_run, flavor=flavor.folder, items=len(items), files=len(selected),
              bytes=sum(sv.size for _, sv in selected), backup=backup)
    guard = _Guard(flavor)
    infos: list[os.stat_result | None] = []
    for index, (_, sv) in enumerate(selected, 1):
        info = _lstat(sv.path)  # one lstat per file, shared by the guard and the recheck
        guard.check(sv.path, info)
        infos.append(info)
        report("check", index, len(selected), _relative(sv.path, flavor))

    result = CleanResult(dry_run=dry_run, backup_path=None)
    ready: list[tuple[ProposalItem, SVFile]] = []
    for (item, sv), info in zip(selected, infos):
        problem = _recheck(sv, info)
        if problem:
            result.outcomes.append(FileOutcome(sv.path, sv.size, "skipped", problem, tuple(item.reasons)))
            log_event("sv.skipped", dry_run=dry_run, path=_relative(sv.path, flavor), reason=problem)
        else:
            ready.append((item, sv))

    snapshot: Path | None = None
    if not dry_run and ready:
        if journal is not None:
            _open_journal(journal, flavor)
        _refuse_locked(ready, flavor, report)
        snapshot = _take_safety_snapshot(flavor, backup_dir, now, [_relative(sv.path, flavor) for _, sv in ready],
                                         report)
        result.snapshot_path = snapshot

    try:
        if backup and ready:
            _selective_backup(result, ready, flavor, backup_dir, now, dry_run, report, account)
    except BaseException:
        if snapshot is not None and backup_dir is not None:
            clear_marker(backup_dir)  # nothing was deleted; the WTF backup is kept like any other
        raise

    deleted: list[str] = []
    try:
        for index, (item, sv) in enumerate(ready, 1):
            _delete_one(result, item, sv, flavor, dry_run, deleted)
            if journal is not None and result.outcomes[-1].status == "deleted":
                journal.add_deleted(flavor=flavor.folder, path=sv.path, rel=deleted[-1], size=sv.size,
                                    mtime=sv.mtime, zip_path=result.backup_path, snapshot=snapshot)
            report("delete", index, len(ready), _relative(sv.path, flavor))
    except BaseException as exc:
        if snapshot is None or backup_dir is None:
            raise
        error = _restore_after(exc, snapshot, backup_dir, flavor, deleted)
        if journal is not None and not getattr(error, "files_missing", False):
            _journal_rolled_back(journal, flavor, deleted)
        raise error from exc

    if snapshot is not None and backup_dir is not None:
        _finish_safety(result, snapshot, backup_dir, flavor, deleted, report)
        # Nothing deleted: keep every older WTF backup (an earlier clean's Undo may need it).
        result.pruned = prune_snapshots(backup_dir, flavor.short_name, keep_backups) if deleted else []
        if result.pruned:
            log_event("snapshot.pruned", flavor=flavor.folder, keep=keep_backups,
                      removed=[str(p) for p in result.pruned])

    log_event("clean.completed", dry_run=dry_run, flavor=flavor.folder, level="warning" if result.failed else None,
              deleted=len(result.deleted), would_delete=len(result.would_delete),
              skipped=len(result.skipped), failed=len(result.failed), bytes=result.bytes_freed,
              backup=str(result.backup_path) if result.backup_path else None)
    return result


def _journal_rolled_back(journal: CleanJournal, flavor: Flavor, deleted: list[str]) -> None:
    """Every file this flavor deleted is back on disk: tell the journal, so Undo never offers them."""
    try:
        journal.add_rolled_back(flavor=flavor.folder, rels=deleted)
    except OSError as exc:
        log_event("clean.journal_failed", flavor=flavor.folder, journal=str(journal.path), error=str(exc))


def _open_journal(journal: CleanJournal, flavor: Flavor) -> None:
    """Write the journal's header (once per run). If it cannot be written, nothing is deleted."""
    try:
        journal.open()
    except OSError as exc:
        log_event("clean.journal_failed", flavor=flavor.folder, journal=str(journal.path), error=str(exc))
        raise CleanError(f"The run journal could not be written ({journal.path}: {exc}), so nothing was deleted "
                         f"(Undo last clean needs it).") from exc


def _finish_safety(result: CleanResult, snapshot: Path, backup_dir: Path, flavor: Flavor, deleted: list[str],
                   report: CleanProgress) -> None:
    """Check the WTF folder against the backup taken before deleting, then clear the marker (the clean finished).
    The backup is kept either way."""
    problems = check_clean(snapshot, flavor, deleted, result.backup_path, report)
    clear_marker(backup_dir)
    result.check_problems = problems
    if problems:
        log_event("clean.check_failed", flavor=flavor.folder, zip=str(snapshot), problems=len(problems),
                  details=problems[:20])
    else:
        log_event("clean.validated", flavor=flavor.folder, deleted=len(deleted), zip=str(snapshot))


def cleaned_zip_path(backup_dir: Path, flavor_short: str, account: str | None, now: datetime) -> Path:
    """<backup folder>/cleaned/cleaned-<flavor>-<account or all>-<YYYYMMDD-HHMMSS>.zip, with -2, -3, ... before
    .zip when that name is taken (two runs in the same second)."""
    return free_name(backup_dir / CLEANED_SUBDIR,
                     f"cleaned-{flavor_short}-{account or ALL_ACCOUNTS_LABEL}-{now:%Y%m%d-%H%M%S}", ".zip")


def _selective_backup(result: CleanResult, ready: list[tuple[ProposalItem, SVFile]], flavor: Flavor,
                      backup_dir: Path | None, now: datetime, dry_run: bool, report: CleanProgress,
                      account: str | None) -> None:
    if backup_dir is None:
        raise BackupError("no backup folder is configured")
    dest = cleaned_zip_path(backup_dir, flavor.short_name, account, now)
    ready_bytes = sum(sv.size for _, sv in ready)
    meta = {"tool": TOOL_NAME, "suite_version": __version__, "flavor": flavor.folder,
            "account": account, "created": now.isoformat(timespec="seconds")}
    try:
        # The recheck just confirmed each file's size and mtime, so the backup does not stat them again.
        create_backup([BackupEntry(sv.path, tuple(item.reasons), sv.size, sv.mtime) for item, sv in ready],
                      flavor.path, dest, meta, on_file=lambda i, n, name: report("backup", i, n, name),
                      on_verify=lambda i, n, name: report("verify", i, n, name))
    except BackupError as exc:
        log_event("backup.failed", dry_run=dry_run, zip=str(dest), error=str(exc))
        raise
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
