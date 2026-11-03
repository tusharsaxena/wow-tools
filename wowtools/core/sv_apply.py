"""Apply edits to SavedVariables files, per flavor and over several flavors (Ace3 spec §9, SV Browser spec D14-D16).
UI-free; the tool brings its name and event prefix (SvTool) and how one file's edit is built and checked.

Per flavor (apply_flavor): refuse while an earlier Apply's crash marker is there (its recovery would be lost), guard
every path, re-read each file and check it is still what the scan saw (SHA-256), compile and verify every edit in
memory (the tool's callbacks), then (real runs only) open the journal, recover lock-probe leftovers, refuse locked
files, take the whole-WTF snapshot, zip the original bytes of every file to change, write the crash marker, and
write each file atomically (re-read and compared), journalling each one, then journal the flavor as completed and
remove the marker. Any failure while writing puts the files already written back from their original bytes, then
the run stops (no completed record). A dry run stops after the verify step and
writes nothing at all.

Over several flavors (apply_flavors): one journal for the whole run; the flavors are applied one after another,
never in parallel ([general] parallelism does not apply): they share the one crash marker (edit-in-progress.json
under the tool's folder, which the recovery screen reads as one pointer), and the run stops at the first flavor
that fails, the rest "not started".

The guard is pluggable (`guard=`, default SvGuard) and a unit whose SvFile.sha256 is None is a file the run creates:
it must not exist at the check nor at the write (else it is skipped, EXISTS), is written with atomic_create_bytes
(never replacing a file that appeared), journaled "created", listed in the marker's `created` (it has no original
to zip, so the originals zip may hold only its manifest) and deleted by a roll-back. Only the client-file pipeline
(core/client_apply.py) uses either; the SavedVariables tools' runs are unchanged.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, TypeVar

from wowtools import __version__
from wowtools.core import marker as core_marker
from wowtools.core.backup import BackupEntry, BackupError, create_backup
from wowtools.core.events import log_event
from wowtools.core.fsutil import atomic_create_bytes, atomic_write_bytes, free_name, safe_progress
from wowtools.core.install import Flavor
from wowtools.core.journal import new_journal_path, now_iso
from wowtools.core.paths import to_native
from wowtools.core.snapshot import prune_snapshots, take_snapshot
from wowtools.core.sv_events import SvTool
from wowtools.core.sv_journal import EditJournal, referenced_zips
from wowtools.core.svfiles import (SvFile, SvFileError, SvGuard, find_locked, locked_message, lstat_or_none,
                                   recover_probe_leftovers, sha256_of)

SNAPSHOT_SUBDIR = "snapshots"
SNAPSHOT_PREFIX = "snapshot"
EDITED_SUBDIR = "edited"
MARKER_NAME = "edit-in-progress.json"
ALL_ACCOUNTS = "all"
CHANGED = "changed since the scan; rescan"
EXISTS = "it exists now; rescan"  # a file the run was to create is there already: never replaced
CREATED = "created"  # FileOutcome.detail of a file the run created
EDITED_NAME = re.compile(r"^edited-.+-\d{8}-\d{6}(?:-\d+)?\.zip$")
ApplyProgress = Callable[[str, int, int, str], None]
P = TypeVar("P")


class Guard(Protocol):
    """Refuses (SvFileError) a path the run may not touch: SvGuard, or core/client_apply.ClientFileGuard."""

    def check(self, path: Path, info: os.stat_result | None) -> Any: ...


class Edit(Protocol):
    """What a tool's compile callback returns for one file: the new bytes and one line per change."""
    data: bytes
    changes: list[str]


Compile = Callable[[SvFile, Any, bytes], Edit]  # (file, the tool's payload for it, its bytes now) -> edit
Verify = Callable[[Any, bytes], list[str]]  # (edit, the file's bytes now) -> problems; [] when it checks out


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


class UndoError(Exception):
    """Undo or recovery was refused or stopped before changing anything (core/sv_undo.py)."""


class WowRunning(ApplyError, UndoError):
    """That flavor's WoW runs: it would overwrite at logout what Apply writes or Undo puts back."""

    def __init__(self, running: list[str], what: str = "changes") -> None:
        super().__init__("WoW is running: " + ", ".join(running) + f". Close it first; it would overwrite the {what}.")
        self.running = running


def refuse_running(tool: SvTool, wow_check: Callable[[], list[str] | None] | None, action: str,
                   what: str) -> None:
    """WowRunning when the check finds that flavor's WoW (no check: allowed)."""
    if wow_check is None:
        return
    running = wow_check()
    if running:
        log_event(tool.event("wow_running"), action=action, running=running)
        raise WowRunning(running, what)


@dataclass
class FileOutcome:
    file: SvFile
    status: str
    detail: str = ""
    changes: list[str] = field(default_factory=list)


class _ByStatus:
    outcomes: list[FileOutcome]

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
class ApplyResult(_ByStatus):
    flavor: Flavor
    dry_run: bool
    outcomes: list[FileOutcome] = field(default_factory=list)
    snapshot: Path | None = None
    backup_zip: Path | None = None
    pruned: list[Path] = field(default_factory=list)
    marker_left: bool = False  # the run finished but its crash marker could not be removed


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
    created: list[str] = field(default_factory=list)  # rels the run creates (not in files: no original)


def write_marker(root: Path, marker: Marker) -> None:
    core_marker.write_marker(root, MARKER_NAME, asdict(marker))


def read_marker(root: Path | None) -> Marker | None:
    """The marker left by an Apply that did not finish, or None (missing or unreadable). Never raises."""
    data = core_marker.read_marker(root, MARKER_NAME)
    if data is None:
        return None
    try:
        files, after, created = data["files"], data.get("after", {}), data.get("created", [])
        if not all(isinstance(d, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in d.items())
                   for d in (files, after)):
            return None
        if not isinstance(created, list) or not all(isinstance(rel, str) for rel in created):
            return None
        return Marker(str(data["flavor"]), to_native(data["flavor_path"]), to_native(data["zip"]), dict(files),
                      str(data["started"]), int(data["pid"]), str(data["suite_version"]), dict(after),
                      list(created))
    except Exception:  # noqa: BLE001 - an unreadable marker is no usable marker
        return None


def clear_marker(root: Path) -> bool:
    """Remove the crash marker; False when it is still there after the retries (core/marker.clear_marker)."""
    return core_marker.clear_marker(root, MARKER_NAME)


def edited_zip_path(root: Path, flavor_short: str, account: str | None, now: datetime) -> Path:
    return free_name(root / EDITED_SUBDIR,
                     f"edited-{flavor_short}-{account or ALL_ACCOUNTS}-{now:%Y%m%d-%H%M%S}", ".zip")


Ready = list[tuple[SvFile, Any, bytes | None]]  # (file, its edit, its original bytes; None: the run creates it)


def _skip(tool: SvTool, result: ApplyResult, file: SvFile, detail: str) -> None:
    """A file changed (or, to be created, appeared) since the scan: skipped, logged as file_changed."""
    result.outcomes.append(FileOutcome(file, "skipped", detail))
    log_event(tool.event("file_changed"), flavor=file.flavor.folder, path=file.rel)


def _read_unit(tool: SvTool, file: SvFile, info: os.stat_result | None,
               result: ApplyResult) -> tuple[bool, bytes | None]:
    """(go on, the file's bytes now; None for a file to create), or (False, None) once it is skipped."""
    if file.sha256 is None:
        if info is not None or os.path.lexists(file.path):
            _skip(tool, result, file, EXISTS)
            return False, None
        if not file.path.parent.is_dir():
            result.outcomes.append(FileOutcome(file, "skipped", "its folder is gone; rescan"))
            return False, None
        return True, None
    try:
        data = file.path.read_bytes()
    except OSError as exc:
        result.outcomes.append(FileOutcome(file, "skipped", f"could not read it: {exc.strerror or exc}"))
        return False, None
    if sha256_of(data) != file.sha256:
        _skip(tool, result, file, CHANGED)
        return False, None
    return True, data


def _prepare(tool: SvTool, flavor: Flavor, units: Sequence[tuple[SvFile, Any]], compile_file: Compile,
             verify: Verify, result: ApplyResult, report: ApplyProgress, guard: Guard) -> Ready:
    """Guard, recheck, compile and verify every file. Raises ApplyError on a guard or verify failure."""
    ready: Ready = []
    for index, (file, payload) in enumerate(units, 1):
        info = lstat_or_none(file.path)
        try:
            guard.check(file.path, info)
        except SvFileError as exc:
            raise ApplyError(str(exc)) from None
        go_on, data = _read_unit(tool, file, info, result)
        if not go_on:
            continue
        edit = compile_file(file, payload, data or b"")
        problems = verify(edit, data or b"")
        if problems:
            log_event(tool.event("verify_failed"), flavor=flavor.folder, path=file.rel, problems=problems[:10])
            raise ApplyError(f"{file.rel}: the change did not check out ({'; '.join(problems[:3])}). "
                             f"Nothing was changed.")
        ready.append((file, edit, data))
        report("check", index, len(units), file.rel)
    return ready


def _refuse_locked(tool: SvTool, ready: Ready, flavor: Flavor, report: ApplyProgress) -> None:
    locked = find_locked([(file.rel, file.path) for file, _, _ in ready],
                         lambda exc: ApplyError(f"{exc} Nothing was changed."), report)
    if locked:
        log_event(tool.event("file_locked"), flavor=flavor.folder, files=len(locked),
                  details=[r for r, _ in locked[:20]])
        raise ApplyError(locked_message(locked, "apply"))


def _refuse_unfinished(tool: SvTool, root: Path, flavor: Flavor) -> None:
    """ApplyError while an earlier Apply's marker is there: a new run would overwrite (then clear) the only pointer
    to that run's originals, as the WTF Cleaner refuses too."""
    earlier = read_marker(root)
    if earlier is None:
        return
    log_event(tool.event("earlier_unfinished"), flavor=flavor.folder, earlier_flavor=earlier.flavor,
              started=earlier.started, zip=str(earlier.zip))
    raise ApplyError(f"An earlier change (started {earlier.started}) did not finish; its original files are in "
                     f"{earlier.zip}. Press r to rescan and choose what to do about it (put the originals back or "
                     f"leave as is), then apply again. Nothing was changed.")


def apply_flavor(tool: SvTool, flavor: Flavor, units: Sequence[tuple[SvFile, Any]], compile_file: Compile,
                 verify: Verify, *, root: Path, journal: EditJournal | None, dry_run: bool, keep_snapshots: int,
                 account: str | None = None, now: datetime | None = None, progress: ApplyProgress | None = None,
                 write: Callable[[Path, bytes], None] = atomic_write_bytes,
                 started: dict[str, Any] | None = None, guard: Guard | None = None,
                 create: Callable[[Path, bytes], None] = atomic_create_bytes) -> ApplyResult:
    """Apply one flavor's units, (file, payload) once per file: compile_file(file, payload, bytes) builds the edit,
    verify(edit, bytes) lists its problems. `started` holds the apply_started event's fields (default: files).
    guard checks every path (default SvGuard(flavor)); create writes a file the run creates (sha256 None).
    Raises ApplyError when refused or stopped; its result holds what was done until then."""
    result = ApplyResult(flavor, dry_run)
    try:
        return _apply(tool, result, units, compile_file, verify, root=root, journal=journal,
                      keep_snapshots=keep_snapshots, account=account, now=now or datetime.now(),
                      report=safe_progress(progress), write=write, create=create,
                      started={"files": len(units)} if started is None else started,
                      guard=SvGuard(flavor) if guard is None else guard)
    except ApplyError as exc:
        exc.result = result
        raise


def _apply(tool: SvTool, result: ApplyResult, units: Sequence[tuple[SvFile, Any]], compile_file: Compile,
           verify: Verify, *, root: Path, journal: EditJournal | None, keep_snapshots: int, account: str | None,
           now: datetime, report: ApplyProgress, write: Callable[[Path, bytes], None],
           create: Callable[[Path, bytes], None], started: dict[str, Any], guard: Guard) -> ApplyResult:
    flavor, dry_run = result.flavor, result.dry_run
    log_event(tool.event("apply_started"), flavor=flavor.folder, dry_run=dry_run, **started)
    if not dry_run:
        _refuse_unfinished(tool, root, flavor)
    ready = _prepare(tool, flavor, units, compile_file, verify, result, report, guard)
    if dry_run:
        for file, edit, data in ready:
            result.outcomes.append(FileOutcome(file, "would_edit", CREATED if data is None else "", edit.changes))
            log_event(tool.event("would_edit"), flavor=flavor.folder, path=file.rel, changes=edit.changes[:50])
        log_event(tool.event("dry_run_completed"), flavor=flavor.folder, files=len(ready))
        return result
    if not ready:
        return result
    assert journal is not None, "a real run needs a journal"
    try:
        journal.open()
    except OSError as exc:
        log_event(tool.event("journal_failed"), error=str(exc))
        raise ApplyError(f"The run journal could not be written ({exc}). Nothing was changed.") from exc
    recover_probe_leftovers(sorted({f.path.parent for f, _, _ in ready}), on_recovered=lambda p: log_event(
        tool.event("probe_recovered"), flavor=flavor.folder, path=p.relative_to(flavor.path).as_posix()))
    _refuse_locked(tool, ready, flavor, report)
    replaced = [(file, data) for file, _, data in ready if data is not None]
    created = [file.rel for file, _, data in ready if data is None]
    try:
        result.snapshot = take_snapshot(flavor, root / SNAPSHOT_SUBDIR, SNAPSHOT_PREFIX, now, progress=report,
                                        must_hold=[file.rel for file, _ in replaced])
    except BackupError as exc:
        log_event(tool.event("snapshot_failed"), flavor=flavor.folder, error=str(exc))
        raise ApplyError(f"The WTF backup failed ({exc}). Nothing was changed.") from exc
    log_event(tool.event("snapshot_taken"), flavor=flavor.folder, path=str(result.snapshot))
    try:
        meta = {"tool": tool.name, "kind": "originals", "flavor": flavor.folder, "suite_version": __version__,
                "sha256": {file.rel: file.sha256 for file, _ in replaced}}
        if created:
            meta["created"] = created
        result.backup_zip = create_backup(
            [BackupEntry(file.path, size=len(data)) for file, data in replaced], flavor.path,
            edited_zip_path(root, flavor.short_name, account, now), meta,
            on_file=lambda i, n, name: report("backup", i, n, name), allow_empty=bool(created))
    except BackupError as exc:
        log_event(tool.event("backup_failed"), flavor=flavor.folder, error=str(exc))
        raise ApplyError(f"Saving the original files failed ({exc}). Nothing was changed.") from exc
    log_event(tool.event("files_backed_up"), flavor=flavor.folder, path=str(result.backup_zip), files=len(replaced))
    try:
        write_marker(root, Marker(flavor.folder, flavor.path, result.backup_zip,
                                  {file.rel: file.sha256 for file, _ in replaced}, now_iso(), os.getpid(),
                                  __version__, {file.rel: sha256_of(edit.data) for file, edit, _ in ready},
                                  created))
    except OSError as exc:
        log_event(tool.event("marker_failed"), flavor=flavor.folder, error=str(exc))
        raise ApplyError(f"The crash marker could not be written ({exc}). Nothing was changed.") from exc
    written: list[tuple[SvFile, bytes | None]] = []
    current_file: SvFile | None = None
    try:
        for index, (file, edit, data) in enumerate(ready, 1):
            current_file = file
            if data is None:
                if not _create_one(tool, file, edit, result, journal, create, written):
                    current_file = None
                    continue
            else:
                current = file.path.read_bytes()
                if sha256_of(current) != file.sha256:
                    _skip(tool, result, file, CHANGED)
                    current_file = None
                    continue
                write(file.path, edit.data)
                written.append((file, data))
                if file.path.read_bytes() != edit.data:
                    raise OSError(f"{file.rel} did not read back as written")
                journal.add_edited(flavor=flavor.folder, path=file.path, rel=file.rel, zip_path=result.backup_zip,
                                   sha_before=file.sha256, sha_after=sha256_of(edit.data), size_before=len(data),
                                   size_after=len(edit.data), changes=edit.changes)
                result.outcomes.append(FileOutcome(file, "edited", changes=edit.changes))
                log_event(tool.event("file_edited"), flavor=flavor.folder, path=file.rel, changes=edit.changes[:50])
            report("edit", index, len(ready), file.rel)
            current_file = None
    except BaseException as exc:  # noqa: BLE001 - roll back on anything (even Ctrl+C), then re-raise
        _roll_back(tool, exc, written, current_file, result, journal, root, flavor)
    if result.edited:
        try:  # before the marker goes: a marker left from here on belongs to a finished flavor (recover's guard)
            journal.add_completed(flavor=flavor.folder, zip_path=result.backup_zip)
        except OSError:
            pass  # recovery then treats the flavor as unfinished and puts back what is still at its after
    if not clear_marker(root):
        result.marker_left = True
        log_event(tool.event("marker_left"), flavor=flavor.folder, path=str(root / MARKER_NAME))
    result.pruned = prune_snapshots(root / SNAPSHOT_SUBDIR, SNAPSHOT_PREFIX, flavor.short_name, keep_snapshots)
    if result.pruned:
        log_event(tool.event("snapshots_pruned"), flavor=flavor.folder, removed=[p.name for p in result.pruned])
    return result


def _create_one(tool: SvTool, file: SvFile, edit: Any, result: ApplyResult, journal: EditJournal,
                create: Callable[[Path, bytes], None], written: list[tuple[SvFile, bytes | None]]) -> bool:
    """Write a file the run creates, unless one appeared at its name since the check (skipped, EXISTS: never
    replaced). True when it was written, read back and journaled."""
    if os.path.lexists(file.path):
        _skip(tool, result, file, EXISTS)
        return False
    try:
        create(file.path, edit.data)
    except FileExistsError:  # it appeared between the check and the rename
        _skip(tool, result, file, EXISTS)
        return False
    written.append((file, None))
    if file.path.read_bytes() != edit.data:
        raise OSError(f"{file.rel} did not read back as written")
    journal.add_created(flavor=file.flavor.folder, path=file.path, rel=file.rel, zip_path=result.backup_zip,
                        sha_after=sha256_of(edit.data), size_after=len(edit.data), changes=edit.changes)
    result.outcomes.append(FileOutcome(file, "edited", CREATED, edit.changes))
    log_event(tool.event("file_created"), flavor=file.flavor.folder, path=file.rel, changes=edit.changes[:50])
    return True


def restore_original(path: Path, data: bytes) -> None:
    """Put a file's original bytes back (roll-back after a failure); its own name so tests can fail it."""
    atomic_write_bytes(path, data)


def remove_created(path: Path) -> None:
    """Delete a file the run created (roll-back after a failure); its own name so tests can fail it."""
    os.remove(path)


def _roll_back(tool: SvTool, exc: BaseException, written: list[tuple[SvFile, bytes | None]],
               failing: SvFile | None, result: ApplyResult, journal: EditJournal, root: Path, flavor: Flavor) -> None:
    """Put back every file this run wrote (a file it created is deleted), newest first, then raise ApplyError (or
    re-raise a non-Exception). failing is the file being written when it failed; its outcome is added here."""
    put_back, left, left_created = [], [], set()
    for file, original in reversed(written):
        try:
            if original is None:
                remove_created(file.path)
            else:
                restore_original(file.path, original)
            put_back.append(file.rel)
        except OSError as error:
            left.append(file.rel)
            if original is None:
                left_created.add(file.rel)
            log_event(tool.event("rollback_failed"), flavor=flavor.folder, path=file.rel, error=str(error))
    if put_back:
        try:
            journal.add_rolled_back(flavor=flavor.folder, rels=put_back)
        except OSError:
            pass
    done, not_back = set(put_back), set(left)

    def left_detail(rel: str) -> str:
        if rel in left_created:  # no original in the zip: the fix is to delete it
            return ("was created by this run and could not be removed after the failure; close WoW and use Undo "
                    "or the recovery screen, or delete it by hand")
        return f"could not be put back after the failure; its original is in {result.backup_zip}"
    for outcome in result.outcomes:
        if outcome.status == "edited" and outcome.file.rel in done:
            outcome.status = "rolled_back"
        elif outcome.status == "edited" and outcome.file.rel in not_back:
            outcome.status, outcome.detail = "failed", left_detail(outcome.file.rel)
    if failing is not None and not any(o.file is failing for o in result.outcomes):
        if failing.rel in done:
            result.outcomes.append(FileOutcome(failing, "rolled_back", f"writing it failed ({exc})"))
        elif failing.rel in not_back:
            result.outcomes.append(FileOutcome(failing, "failed", left_detail(failing.rel)))
        else:
            result.outcomes.append(FileOutcome(failing, "failed", f"not written ({exc})"))
    log_event(tool.event("rolled_back"), flavor=flavor.folder, files=put_back, left=left, error=str(exc))
    if not left:
        clear_marker(root)
    if not isinstance(exc, Exception):
        raise exc
    log_event(tool.event("write_failed"), flavor=flavor.folder, error=str(exc))
    message = f"Writing the changes failed ({exc})."
    if put_back:
        message += f" The {len(put_back)} file(s) already written were put back."
    replaced_left = [rel for rel in left if rel not in left_created]
    if replaced_left:
        message += (f" {len(replaced_left)} file(s) could not be put back: their originals are in "
                    f"{result.backup_zip}. Close WoW and use Undo, or unzip them by hand.")
    if left_created:
        message += (f" {len(left_created)} file(s) this run created could not be removed. Close WoW and use Undo "
                    "or the recovery screen, or delete them by hand.")
    raise ApplyError(message, rolled_back=put_back, files_left=left) from exc


@dataclass
class FlavorRun:
    flavor: Flavor
    result: ApplyResult | None = None
    error: str | None = None

    @property
    def status(self) -> str:
        if self.error is not None:
            return "stopped"
        return "done" if self.result is not None else "not_started"


@dataclass
class MultiApplyResult(_ByStatus):
    dry_run: bool
    runs: list[FlavorRun] = field(default_factory=list)
    journal_path: Path | None = None

    @property
    def outcomes(self) -> list[FileOutcome]:
        return [o for r in self.runs if r.result is not None for o in r.result.outcomes]

    @property
    def marker_left(self) -> bool:
        return any(r.result is not None and r.result.marker_left for r in self.runs)

    @property
    def stopped(self) -> FlavorRun | None:
        return next((r for r in self.runs if r.status == "stopped"), None)


def prune_edited_zips(root: Path, journal_dir: Path | None, keep_names: set[str] = frozenset()) -> list[Path]:
    """Delete edited-*.zip files no journal names any more (and not the crash marker's). Deletes nothing when a
    journal could not be read."""
    folder = root / EDITED_SUBDIR
    referenced = referenced_zips(journal_dir)
    if referenced is None:
        return []
    marker = read_marker(root)
    keep = set(keep_names) | referenced | ({marker.zip.name} if marker else set())
    removed = []
    try:
        candidates = sorted(p for p in folder.iterdir() if EDITED_NAME.match(p.name) and p.is_file())
    except OSError:
        return []
    for path in candidates:
        if path.name not in keep:
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                pass
    return removed


ApplyOne = Callable[..., ApplyResult]  # (flavor, payload, *, root, journal, dry_run, keep_snapshots, account, now,
#                                        progress) -> ApplyResult; raises ApplyError


def apply_flavors(tool: SvTool, plan: Sequence[tuple[Flavor, P]], apply_one: ApplyOne, *, root: Path,
                  journal_dir: Path, keep_journals: int, keep_snapshots: int, dry_run: bool,
                  account: str | None = None, wow_check: Callable[[], list[str] | None] | None = None,
                  now: datetime | None = None,
                  progress: Callable[[Flavor, str, int, int, str], None] | None = None) -> MultiApplyResult:
    """Apply each (flavor, payload) of plan with apply_one (the tool's apply_flavor) under one journal."""
    now = now or datetime.now()
    if not dry_run:
        refuse_running(tool, wow_check, "apply", "changes")
    result = MultiApplyResult(dry_run, [FlavorRun(flavor) for flavor, _ in plan])
    journal = None
    if not dry_run:
        journal = EditJournal(new_journal_path(journal_dir, now),
                              {"tool": tool.name, "kind": "apply", "flavors": [f.folder for f, _ in plan],
                               "root": root, "suite_version": __version__})
        result.journal_path = journal.path
    try:
        for run, (flavor, payload) in zip(result.runs, plan):
            report = None if progress is None else (lambda *a, f=flavor: progress(f, *a))
            try:
                run.result = apply_one(flavor, payload, root=root, journal=journal, dry_run=dry_run,
                                       keep_snapshots=keep_snapshots, account=account, now=now, progress=report)
            except ApplyError as exc:
                run.error = str(exc)
                run.result = exc.result
                later = [r.flavor.folder for r in result.runs if r.status == "not_started" and r is not run]
                if later:
                    log_event(tool.event("flavors_stopped"), flavor=flavor.folder, not_started=later)
                break
    finally:
        if journal is not None:
            if journal.count:
                journal.finish()
            journal.discard_if_empty()
            if not journal.opened:
                result.journal_path = None
    if not dry_run:
        tool.journals.prune(journal_dir, keep_journals)
        prune_edited_zips(root, journal_dir)
        log_event(tool.event("apply_completed"), files=len(result.edited), skipped=len(result.skipped),
                  stopped=result.stopped.flavor.folder if result.stopped else None,
                  level="warning" if result.skipped or result.failed or result.stopped else None)
    return result
