"""Apply staged profile changes to one flavor's SavedVariables (spec §9). UI-free.

Order: refuse while an earlier Apply's crash marker is there (its recovery would be lost), guard every path, re-read each file and check it is still what the scan saw (SHA-256), compile and verify
every edit in memory, then (real runs only) open the journal, recover lock-probe leftovers, refuse locked files,
take the whole-WTF snapshot, zip the original bytes of every file to change, write the crash marker, and write
each file atomically (re-read and compared), journalling each one. Any failure while writing puts the files
already written back from their original bytes, then the run stops. A dry run stops after the verify step and
writes nothing at all.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from wowtools import __version__
from wowtools.core import marker as core_marker
from wowtools.core.backup import BackupEntry, BackupError, create_backup
from wowtools.core.events import log_event
from wowtools.core.fsutil import atomic_write_bytes, free_name, safe_progress
from wowtools.core.install import Flavor
from wowtools.core.journal import now_iso
from wowtools.core.snapshot import prune_snapshots, take_snapshot
from wowtools.core.svfiles import (SvFile, SvFileError, SvGuard, find_locked, locked_message, lstat_or_none,
                                   recover_probe_leftovers, sha256_of)
from wowtools.tools.ace3_profile_manager.events import TOOL_NAME
from wowtools.tools.ace3_profile_manager.journal import ProfileJournal
from wowtools.tools.ace3_profile_manager.ops import DbState, FileEdit, compile_file
from wowtools.tools.ace3_profile_manager.verify import verify_edit

SNAPSHOT_SUBDIR = "snapshots"
SNAPSHOT_PREFIX = "snapshot"
EDITED_SUBDIR = "edited"
MARKER_NAME = "edit-in-progress.json"
ALL_ACCOUNTS = "all"
CHANGED = "changed since the scan; rescan"
ApplyProgress = Callable[[str, int, int, str], None]


class ApplyError(Exception):
    """Apply was refused or stopped. rolled_back: files put back after a failure; files_left: files that could
    not be put back (the marker is kept; the originals are in the edited-*.zip it names); result: what the run
    did before it stopped (outcomes, snapshot, originals zip), set by apply_flavor."""

    def __init__(self, message: str, *, rolled_back: list[str] | None = None,
                 files_left: list[str] | None = None) -> None:
        super().__init__(message)
        self.rolled_back = list(rolled_back or [])
        self.files_left = list(files_left or [])
        self.result: ApplyResult | None = None


@dataclass
class FileOutcome:
    file: SvFile
    status: str
    detail: str = ""
    changes: list[str] = field(default_factory=list)


@dataclass
class ApplyResult:
    flavor: Flavor
    dry_run: bool
    outcomes: list[FileOutcome] = field(default_factory=list)
    snapshot: Path | None = None
    backup_zip: Path | None = None
    pruned: list[Path] = field(default_factory=list)

    def _with(self, status: str) -> list[FileOutcome]:
        return [o for o in self.outcomes if o.status == status]

    @property
    def edited(self) -> list[FileOutcome]:
        return self._with("edited")

    @property
    def would_edit(self) -> list[FileOutcome]:
        return self._with("would_edit")

    @property
    def skipped(self) -> list[FileOutcome]:
        return self._with("skipped")

    @property
    def failed(self) -> list[FileOutcome]:
        return self._with("failed")

    @property
    def rolled_back(self) -> list[FileOutcome]:
        return self._with("rolled_back")


@dataclass
class Marker:
    flavor: str
    flavor_path: Path
    zip: Path
    files: dict[str, str]  # rel -> SHA-256 of the original
    started: str
    pid: int
    suite_version: str
    after: dict[str, str] = field(default_factory=dict)  # rel -> SHA-256 of what the run writes


def write_marker(root: Path, marker: Marker) -> None:
    core_marker.write_marker(root, MARKER_NAME, asdict(marker))


def read_marker(root: Path | None) -> Marker | None:
    """The marker left by an Apply that did not finish, or None (missing or unreadable). Never raises."""
    data = core_marker.read_marker(root, MARKER_NAME)
    if data is None:
        return None
    try:
        files, after = data["files"], data.get("after", {})
        if not all(isinstance(d, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in d.items())
                   for d in (files, after)):
            return None
        return Marker(str(data["flavor"]), Path(data["flavor_path"]), Path(data["zip"]), dict(files),
                      str(data["started"]), int(data["pid"]), str(data["suite_version"]), dict(after))
    except Exception:  # noqa: BLE001 - an unreadable marker is no usable marker
        return None


def clear_marker(root: Path) -> None:
    core_marker.clear_marker(root, MARKER_NAME)


def edited_zip_path(root: Path, flavor_short: str, account: str | None, now: datetime) -> Path:
    return free_name(root / EDITED_SUBDIR,
                     f"edited-{flavor_short}-{account or ALL_ACCOUNTS}-{now:%Y%m%d-%H%M%S}", ".zip")


def group_by_file(states: list[DbState]) -> dict[Path, list[DbState]]:
    grouped: dict[Path, list[DbState]] = {}
    for state in states:
        grouped.setdefault(state.file.path, []).append(state)
    return grouped


def _prepare(flavor: Flavor, states: list[DbState], result: ApplyResult,
             report: ApplyProgress) -> list[tuple[SvFile, FileEdit, bytes]]:
    """Guard, recheck, compile and verify every file. Raises ApplyError on a guard or verify failure."""
    guard = SvGuard(flavor)
    grouped = group_by_file(states)
    ready: list[tuple[SvFile, FileEdit, bytes]] = []
    for index, (path, file_states) in enumerate(grouped.items(), 1):
        file = file_states[0].file
        try:
            guard.check(path, lstat_or_none(path))
        except SvFileError as exc:
            raise ApplyError(str(exc)) from None
        try:
            data = path.read_bytes()
        except OSError as exc:
            result.outcomes.append(FileOutcome(file, "skipped", f"could not read it: {exc.strerror or exc}"))
            continue
        if sha256_of(data) != file.sha256:
            result.outcomes.append(FileOutcome(file, "skipped", CHANGED))
            log_event("ace.file_changed", flavor=flavor.folder, path=file.rel)
            continue
        edit = compile_file(file_states, data)
        problems = verify_edit(edit, data)
        if problems:
            log_event("ace.verify_failed", flavor=flavor.folder, path=file.rel, problems=problems[:10])
            raise ApplyError(f"{file.rel}: the change did not check out ({'; '.join(problems[:3])}). "
                             f"Nothing was changed.")
        ready.append((file, edit, data))
        report("check", index, len(grouped), file.rel)
    return ready


def _refuse_locked(ready: list[tuple[SvFile, FileEdit, bytes]], flavor: Flavor, report: ApplyProgress) -> None:
    locked = find_locked([(file.rel, file.path) for file, _, _ in ready],
                         lambda exc: ApplyError(f"{exc} Nothing was changed."), report)
    if locked:
        log_event("ace.file_locked", flavor=flavor.folder, files=len(locked), details=[r for r, _ in locked[:20]])
        raise ApplyError(locked_message(locked, "apply"))


def _refuse_unfinished(root: Path, flavor: Flavor) -> None:
    """ApplyError while an earlier Apply's marker is there: a new run would overwrite (then clear) the only pointer
    to that run's originals, as the WTF Cleaner refuses too."""
    earlier = read_marker(root)
    if earlier is None:
        return
    log_event("ace.earlier_unfinished", flavor=flavor.folder, earlier_flavor=earlier.flavor,
              started=earlier.started, zip=str(earlier.zip))
    raise ApplyError(f"An earlier change (started {earlier.started}) did not finish; its original files are in "
                     f"{earlier.zip}. Press r to rescan and choose what to do about it (put the originals back or "
                     f"leave as is), then apply again. Nothing was changed.")


def apply_flavor(flavor: Flavor, states: list[DbState], *, root: Path, journal: ProfileJournal | None,
                 dry_run: bool, keep_snapshots: int, account: str | None = None, now: datetime | None = None,
                 progress: ApplyProgress | None = None,
                 write: Callable[[Path, bytes], None] = atomic_write_bytes) -> ApplyResult:
    """Raises ApplyError when refused or stopped; its result holds what was done until then."""
    result = ApplyResult(flavor, dry_run)
    try:
        return _apply(result, states, root=root, journal=journal, keep_snapshots=keep_snapshots, account=account,
                      now=now or datetime.now(), report=safe_progress(progress), write=write)
    except ApplyError as exc:
        exc.result = result
        raise


def _apply(result: ApplyResult, states: list[DbState], *, root: Path, journal: ProfileJournal | None,
           keep_snapshots: int, account: str | None, now: datetime, report: ApplyProgress,
           write: Callable[[Path, bytes], None]) -> ApplyResult:
    flavor, dry_run = result.flavor, result.dry_run
    log_event("ace.apply_started", flavor=flavor.folder, dry_run=dry_run, databases=len(states))
    if not dry_run:
        _refuse_unfinished(root, flavor)
    ready = _prepare(flavor, states, result, report)
    if dry_run:
        for file, edit, _ in ready:
            result.outcomes.append(FileOutcome(file, "would_edit", changes=edit.changes))
            log_event("ace.would_edit", flavor=flavor.folder, path=file.rel, changes=edit.changes[:50])
        log_event("ace.dry_run_completed", flavor=flavor.folder, files=len(ready))
        return result
    if not ready:
        return result
    assert journal is not None, "a real run needs a journal"
    try:
        journal.open()
    except OSError as exc:
        log_event("ace.journal_failed", error=str(exc))
        raise ApplyError(f"The run journal could not be written ({exc}). Nothing was changed.") from exc
    recover_probe_leftovers(sorted({f.path.parent for f, _, _ in ready}), on_recovered=lambda p: log_event(
        "ace.probe_recovered", flavor=flavor.folder, path=p.relative_to(flavor.path).as_posix()))
    _refuse_locked(ready, flavor, report)
    rels = [file.rel for file, _, _ in ready]
    try:
        result.snapshot = take_snapshot(flavor, root / SNAPSHOT_SUBDIR, SNAPSHOT_PREFIX, now, progress=report,
                                        must_hold=rels)
    except BackupError as exc:
        log_event("ace.snapshot_failed", flavor=flavor.folder, error=str(exc))
        raise ApplyError(f"The WTF backup failed ({exc}). Nothing was changed.") from exc
    log_event("ace.snapshot_taken", flavor=flavor.folder, path=str(result.snapshot))
    try:
        result.backup_zip = create_backup(
            [BackupEntry(file.path, size=len(data)) for file, _, data in ready], flavor.path,
            edited_zip_path(root, flavor.short_name, account, now),
            {"tool": TOOL_NAME, "kind": "originals", "flavor": flavor.folder, "suite_version": __version__,
             "sha256": {file.rel: file.sha256 for file, _, _ in ready}},
            on_file=lambda i, n, name: report("backup", i, n, name))
    except BackupError as exc:
        log_event("ace.backup_failed", flavor=flavor.folder, error=str(exc))
        raise ApplyError(f"Saving the original files failed ({exc}). Nothing was changed.") from exc
    log_event("ace.files_backed_up", flavor=flavor.folder, path=str(result.backup_zip), files=len(ready))
    try:
        write_marker(root, Marker(flavor.folder, flavor.path, result.backup_zip,
                                  {file.rel: file.sha256 for file, _, _ in ready}, now_iso(), os.getpid(),
                                  __version__, {file.rel: sha256_of(edit.data) for file, edit, _ in ready}))
    except OSError as exc:
        log_event("ace.marker_failed", flavor=flavor.folder, error=str(exc))
        raise ApplyError(f"The crash marker could not be written ({exc}). Nothing was changed.") from exc
    written: list[tuple[SvFile, bytes]] = []
    current_file: SvFile | None = None
    try:
        for index, (file, edit, data) in enumerate(ready, 1):
            current_file = file
            current = file.path.read_bytes()
            if sha256_of(current) != file.sha256:
                result.outcomes.append(FileOutcome(file, "skipped", CHANGED))
                log_event("ace.file_changed", flavor=flavor.folder, path=file.rel)
                continue
            write(file.path, edit.data)
            written.append((file, data))
            if file.path.read_bytes() != edit.data:
                raise OSError(f"{file.rel} did not read back as written")
            journal.add_edited(flavor=flavor.folder, path=file.path, rel=file.rel, zip_path=result.backup_zip,
                               sha_before=file.sha256, sha_after=sha256_of(edit.data), size_before=len(data),
                               size_after=len(edit.data), changes=edit.changes)
            result.outcomes.append(FileOutcome(file, "edited", changes=edit.changes))
            log_event("ace.file_edited", flavor=flavor.folder, path=file.rel, changes=edit.changes[:50])
            report("edit", index, len(ready), file.rel)
            current_file = None
    except BaseException as exc:  # noqa: BLE001 - roll back on anything (even Ctrl+C), then re-raise
        _roll_back(exc, written, current_file, result, journal, root, flavor)
    clear_marker(root)
    result.pruned = prune_snapshots(root / SNAPSHOT_SUBDIR, SNAPSHOT_PREFIX, flavor.short_name, keep_snapshots)
    if result.pruned:
        log_event("ace.snapshots_pruned", flavor=flavor.folder, removed=[p.name for p in result.pruned])
    return result


def restore_original(path: Path, data: bytes) -> None:
    """Put a file's original bytes back (roll-back after a failure); its own name so tests can fail it."""
    atomic_write_bytes(path, data)


def _roll_back(exc: BaseException, written: list[tuple[SvFile, bytes]], failing: SvFile | None,
               result: ApplyResult, journal: ProfileJournal, root: Path, flavor: Flavor) -> None:
    """Put back every file this run wrote, newest first, then raise ApplyError (or re-raise a non-Exception).
    failing is the file being written when it failed; its outcome is added here."""
    put_back, left = [], []
    for file, original in reversed(written):
        try:
            restore_original(file.path, original)
            put_back.append(file.rel)
        except OSError as error:
            left.append(file.rel)
            log_event("ace.rollback_failed", flavor=flavor.folder, path=file.rel, error=str(error))
    if put_back:
        try:
            journal.add_rolled_back(flavor=flavor.folder, rels=put_back)
        except OSError:
            pass
    done, not_back = set(put_back), set(left)
    left_detail = f"could not be put back after the failure; its original is in {result.backup_zip}"
    for outcome in result.outcomes:
        if outcome.status == "edited" and outcome.file.rel in done:
            outcome.status = "rolled_back"
        elif outcome.status == "edited" and outcome.file.rel in not_back:
            outcome.status, outcome.detail = "failed", left_detail
    if failing is not None and not any(o.file is failing for o in result.outcomes):
        if failing.rel in done:
            result.outcomes.append(FileOutcome(failing, "rolled_back", f"writing it failed ({exc})"))
        elif failing.rel in not_back:
            result.outcomes.append(FileOutcome(failing, "failed", left_detail))
        else:
            result.outcomes.append(FileOutcome(failing, "failed", f"not written ({exc})"))
    log_event("ace.rolled_back", flavor=flavor.folder, files=put_back, left=left, error=str(exc))
    if not left:
        clear_marker(root)
    if not isinstance(exc, Exception):
        raise exc
    log_event("ace.write_failed", flavor=flavor.folder, error=str(exc))
    message = f"Writing the changes failed ({exc})."
    if put_back:
        message += f" The {len(put_back)} file(s) already written were put back."
    if left:
        message += (f" {len(left)} file(s) could not be put back: their originals are in "
                    f"{result.backup_zip}. Close WoW and use Undo, or unzip them by hand.")
    raise ApplyError(message, rolled_back=put_back, files_left=left) from exc
