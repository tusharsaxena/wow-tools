"""Restore a flavor's Interface and/or WTF folders from a backup: exact replace through a staging folder and a
folder swap, after a pre-restore safety backup, with a run journal for Undo. UI-free."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from wowtools import __version__
from wowtools.core.backup import MANIFEST_NAME, BackupError, verify_backup
from wowtools.core.events import log_event
from wowtools.core.fsutil import is_real_dir, remove_tree_no_follow, safe_progress
from wowtools.core.install import Flavor
from wowtools.core.journal import JournalWriter, list_journals, new_journal_path, prune_journals
from wowtools.core.paths import to_stored
from wowtools.tools.interface_backup.backup import write_zip
from wowtools.tools.interface_backup.catalog import SAFETY, new_backup_path, prune_safety
from wowtools.tools.interface_backup.journal import referenced_safety_zips
from wowtools.tools.interface_backup.scanner import PARTS, FlavorScan, leftover_folders, scan_flavor

NEWER_SLACK = 2.0  # zip timestamps have 2-second steps
KINDS = ("backup", "pre-restore")
_DRIVE = re.compile(r"^[A-Za-z]:")
_FLAVOR_FOLDER = re.compile(r"_[A-Za-z0-9_]+_")  # fullmatch: no trailing newline
_BAD_CHARS = frozenset('<>:"|?*\x00')  # refused everywhere: Windows cannot write them, NUL nowhere can
# Windows only: control characters, and device names ("CON", "nul.lua") that open the device, not a file. On POSIX
# these are ordinary names (a character called Aux gets an "Aux" folder), so a backup made there must restore there.
_WINDOWS_BAD_CHARS = frozenset(chr(c) for c in range(1, 32))
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL"} | {f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)})
# Reading a zip: a damaged file, an unsupported compression method or an encrypted entry.
ZIP_ERRORS = (OSError, zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, ValueError)


def _case_key(name: str) -> str:
    """A name as Windows compares it: per-character lower case, not casefold()'s full folding ("ß" is not "ss" on
    NTFS, so "Straße.lua" and "STRASSE.lua" are two files)."""
    return name.lower()


class RestoreError(Exception):
    """A backup cannot be restored (unreadable, not ours, unsafe names), or a restore cannot start. Nothing was
    changed."""


def _unsafe(name: str) -> RestoreError:
    return RestoreError(f"unsafe entry name in the backup: {name!r}")


def _bad_component(part: str, windows: bool) -> bool:
    if part in ("", ".", "..") or part != part.rstrip(". ") or _BAD_CHARS & set(part):
        return True
    return windows and (bool(_WINDOWS_BAD_CHARS & set(part)) or part.split(".")[0].upper() in _RESERVED)


def split_entry(name: str, *, windows: bool | None = None) -> tuple[str, str]:
    """('Interface', 'AddOns/A/a.lua') for a safe zip entry name; RestoreError for anything that could land
    outside the part folder, or be written as something else, on Windows or POSIX: absolute, a drive, a backslash,
    `.`/`..`, an empty component (a folder entry), `:` (alternate data stream), a trailing dot or space, `<>"|?*`
    or NUL, or a first part other than Interface or WTF (case counts). On Windows (`windows`, default: running
    there) control characters and device names (`CON`, `nul.lua`, `COM1`) are refused too."""
    if windows is None:
        windows = os.name == "nt"
    if not name or "\\" in name or name.startswith("/") or _DRIVE.match(name):
        raise _unsafe(name)
    pieces = name.split("/")
    if len(pieces) < 2 or pieces[0] not in PARTS or any(_bad_component(p, windows) for p in pieces[1:]):
        raise _unsafe(name)
    return pieces[0], "/".join(pieces[1:])


@dataclass
class BackupContents:
    path: Path
    kind: str  # backup | pre-restore
    flavor_short: str
    flavor_folder: str
    created: str
    parts: tuple[str, ...]  # the parts the backup holds (an empty one included): only these can be restored
    files: dict[str, dict[str, tuple[int, float]]]  # part -> rel -> (size, mtime); every part of PARTS is a key
    links: list[str] = field(default_factory=list)  # "<Part>/<rel>" links skipped when the backup was made

    def sizes(self, parts: tuple[str, ...] | None = None) -> dict[str, int]:
        """Entry name -> size, for verify_backup (all parts when `parts` is None; none for an empty tuple)."""
        chosen = PARTS if parts is None else parts
        return {f"{part}/{rel}": size for part in chosen for rel, (size, _) in self.files[part].items()}


def _check_names(names: list[str]) -> None:
    """Every entry safe, no two the same (ignoring case), and no file where another entry needs a folder."""
    seen: set[str] = set()
    for name in names:
        split_entry(name)
        key = _case_key(name)
        if key in seen:
            raise RestoreError(f"the backup has two entries for the same file (case ignored): {name}")
        seen.add(key)
    for key in seen:
        pieces = key.split("/")
        for depth in range(2, len(pieces)):
            if "/".join(pieces[:depth]) in seen:
                raise RestoreError(f"the backup has a file where it also needs a folder: {'/'.join(pieces[:depth])}")


def open_backup(path: Path) -> BackupContents:
    """Read a backup's manifest and check every entry name. Reads no file data but the manifest (verification is
    the restore's first stage). Raises RestoreError."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            try:
                raw = zf.read(MANIFEST_NAME)
            except KeyError:
                raise RestoreError("not an Interface Backup zip (it has no manifest.json)") from None
    except ZIP_ERRORS as exc:
        raise RestoreError(f"the backup cannot be read: {exc}") from exc
    try:
        manifest = json.loads(raw)
    except ValueError as exc:  # UnicodeDecodeError included
        raise RestoreError(f"the backup's manifest is damaged: {exc}") from exc
    try:
        if manifest["version"] != 1 or manifest["kind"] not in KINDS:
            raise RestoreError("not an Interface Backup zip (unknown manifest)")
        folder = str(manifest["flavor_folder"])
        if not _FLAVOR_FOLDER.fullmatch(folder):
            raise RestoreError(f"the backup names an invalid flavor folder: {folder!r}")
        names = [info.filename for info in infos if info.filename != MANIFEST_NAME]
        _check_names(names)
        sizes = {info.filename: info.file_size for info in infos}
        listed = {str(f["path"]): float(f["mtime"]) for f in manifest["files"]}
        if len(listed) != len(manifest["files"]) or set(listed) != set(names):
            raise RestoreError("the backup's manifest does not match its contents")
        # Only non-finite times are refused: a pre-1970 file (negative st_mtime) is ordinary input to write_zip.
        # Task 6 leaves the extraction time on a file whose time os.utime cannot set.
        if not all(math.isfinite(mtime) for mtime in listed.values()):
            raise RestoreError("the backup's manifest is damaged: a file time is not a valid date")
        if not isinstance(manifest["parts"], list):
            raise RestoreError("the backup's manifest is damaged: parts is not a list")
        parts = tuple(p for p in PARTS if p in manifest["parts"])
        files: dict[str, dict[str, tuple[int, float]]] = {part: {} for part in PARTS}
        for name, mtime in listed.items():
            part, rel = split_entry(name)
            if part not in parts:
                raise RestoreError(f"the backup's manifest does not claim the {part} folder it holds files for")
            files[part][rel] = (sizes[name], mtime)
        return BackupContents(Path(path), str(manifest["kind"]), str(manifest["flavor"]), folder,
                              str(manifest.get("created", "")), parts, files,
                              [str(link) for link in manifest.get("links", [])])
    except (KeyError, TypeError, ValueError) as exc:
        raise RestoreError(f"the backup's manifest is damaged: {exc!r}") from exc


@dataclass
class RestorePlan:
    contents: BackupContents
    flavor: Flavor
    parts: tuple[str, ...]
    removed: list[tuple[str, str]]  # (part, rel) on disk now, not in the backup: lost by the restore
    newer: list[tuple[str, str]]  # on disk now and more than NEWER_SLACK seconds newer than the backup's copy
    links_kept: list[tuple[str, str]]
    links_removed: list[tuple[str, str]]  # the backup has files there: the link (never its target) goes
    bytes_needed: int  # bytes the chosen parts take once extracted
    free_bytes: int | None  # on the flavor's drive; None when unknown
    leftovers: list[Path]  # from an interrupted restore: a new restore of this flavor is blocked
    unreadable: list[str] = field(default_factory=list)  # chosen parts' scan errors: what is there is lost unlisted

    @property
    def low_space(self) -> bool:
        return self.free_bytes is not None and self.bytes_needed > self.free_bytes


def _free_space(path: Path, disk_usage: Callable) -> int | None:
    try:
        return int(disk_usage(path).free)
    except OSError:
        return None


def plan_restore(contents: BackupContents, scan: FlavorScan, parts: tuple[str, ...], *,
                 disk_usage: Callable = shutil.disk_usage) -> RestorePlan:
    """Compare the backup's chosen parts with what is on disk now (a scan with stats, for `newer`). Paths compare
    ignoring case, as Windows does. Raises RestoreError for no parts or an unknown part name, a backup of another
    flavor, a part the backup does not hold or a part folder that is itself a link."""
    unknown = [p for p in parts if p not in PARTS]
    if unknown or not parts:
        raise RestoreError(f"no such part to restore: {unknown!r}" if unknown else "no part chosen to restore")
    if _case_key(contents.flavor_folder) != _case_key(scan.flavor.folder):
        raise RestoreError(f"the backup is of {contents.flavor_folder}, not {scan.flavor.folder}: a backup restores "
                           "only into its own flavor")
    removed: list[tuple[str, str]] = []
    newer: list[tuple[str, str]] = []
    kept: list[tuple[str, str]] = []
    dropped: list[tuple[str, str]] = []
    unreadable: list[str] = []
    needed = 0
    chosen = tuple(p for p in PARTS if p in parts)
    for part in chosen:
        if part not in contents.parts:
            raise RestoreError(f"the backup has no {part} folder")
        live = scan.parts[part]
        if live.linked:
            raise RestoreError(f"{part} is a link to another folder; restore it by hand")
        unreadable.extend(live.errors)
        backup_files = {_case_key(rel): (size, mtime) for rel, (size, mtime) in contents.files[part].items()}
        folders = {"/".join(rel.split("/")[:i]) for rel in backup_files for i in range(1, rel.count("/") + 1)}
        needed += sum(size for size, _ in backup_files.values())
        for info in live.files:
            match = backup_files.get(_case_key(info.rel))
            if match is None:
                removed.append((part, info.rel))
            elif info.mtime is not None and info.mtime > match[1] + NEWER_SLACK:
                newer.append((part, info.rel))
        for link in live.links:
            key = _case_key(link)
            (dropped if key in backup_files or key in folders else kept).append((part, link))
    return RestorePlan(contents, scan.flavor, chosen, removed, newer, kept, dropped, needed,
                       _free_space(scan.flavor.path, disk_usage), list(scan.leftovers), unreadable)


# --- Running a restore ----------------------------------------------------------------------------------------------

Rename = Callable[[Path, Path], None]
# A part whose extraction or swap fails with one of these is rolled back and the restore goes on to the next part.
_PART_ERRORS = ZIP_ERRORS


class SwapError(OSError):
    """A part could not be replaced. rolled_back says whether it is exactly as it was."""

    def __init__(self, message: str, *, rolled_back: bool) -> None:
        super().__init__(message)
        self.rolled_back = rolled_back


@dataclass
class PartOutcome:
    part: str
    kind: str  # restored | rolled_back | failed | replaced_left
    reason: str = ""


@dataclass
class RestoreResult:
    flavor: Flavor
    backup: Path
    parts: list[PartOutcome] = field(default_factory=list)
    safety_zip: Path | None = None
    journal_path: Path | None = None
    undo: bool = False

    @property
    def ok(self) -> bool:
        return all(p.kind in ("restored", "replaced_left") for p in self.parts)


class RestoreStopped(Exception):
    """A restore or undo stopped unexpectedly. `result` holds what was done; the journal records it."""

    def __init__(self, message: str, result: RestoreResult) -> None:
        super().__init__(message)
        self.result = result


def _native(base: Path, rel: str) -> Path:
    return base.joinpath(*rel.split("/"))


def _set_mtime(path: Path, mtime: float) -> None:
    """The manifest's time on an extracted file; one the platform cannot set (out of range) keeps the extraction
    time rather than failing the restore."""
    try:
        os.utime(path, (mtime, mtime))
    except (OSError, OverflowError, ValueError):
        pass


def _extract(zf: zipfile.ZipFile, part: str, files: dict[str, tuple[int, float]], staging: Path,
             report: Callable[..., None]) -> None:
    staging.mkdir()  # FileExistsError if a staging folder is already there
    total = len(files)
    for index, (rel, (_, mtime)) in enumerate(sorted(files.items()), 1):
        target = _native(staging, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(f"{part}/{rel}") as src, open(target, "xb") as out:
            shutil.copyfileobj(src, out, 1 << 20)
        _set_mtime(target, mtime)
        report("extract", index, total, f"{part}/{rel}")


def _roll_back(live: Path, staging: Path, old: Path, moved: list[str], old_moved: bool, rename: Rename) -> str | None:
    """Put <part> back exactly as it was: the old copy back in place, then the moved links back into it, then the
    staging folder deleted. Returns what could not be put back, or None."""
    if old_moved:
        try:
            rename(old, live)
        except OSError as exc:
            return f"the old copy is still in {to_stored(old)} ({exc})"
    problems = []
    for rel in reversed(moved):
        try:
            rename(_native(staging, rel), _native(live, rel))
        except OSError as exc:
            problems.append(f"the link {rel} is still in {to_stored(staging)} ({exc})")
    if not problems and os.path.lexists(staging):
        try:
            remove_tree_no_follow(staging)
        except OSError as exc:
            problems.append(f"{to_stored(staging)} could not be deleted ({exc})")
    return "; ".join(problems) or None


def _move_links(live: Path, staging: Path, keep_links: list[str], moved: list[str], rename: Rename) -> None:
    """Move each link to keep from the live part to the same place in the staging folder (never through it). A
    link gone since the plan is skipped; something already at the destination is never replaced."""
    for rel in keep_links:
        source, dest = _native(live, rel), _native(staging, rel)
        if not os.path.lexists(source):
            continue
        if os.path.lexists(dest):
            raise FileExistsError(f"{rel} is in the backup too")
        dest.parent.mkdir(parents=True, exist_ok=True)
        rename(source, dest)
        moved.append(rel)


def replace_part(zf: zipfile.ZipFile, files: dict[str, tuple[int, float]], flavor_path: Path, part: str,
                 keep_links: list[str], *, progress: Callable[..., None] | None = None, rename: Rename = os.rename,
                 on_swapped: Callable[[], None] | None = None) -> str | None:
    """Swap <flavor>/<part> for the zip's copy: extract to <part>.restoring, move the links to keep into it, rename
    <part> to <part>.replaced and <part>.restoring to <part>, call on_swapped() (the journal entry), then delete
    <part>.replaced (never through a link). Returns why the old copy could not be fully deleted, or None. Raises
    SwapError when the part could not be replaced (rolled_back=True: it is exactly as it was). Interrupted
    (Ctrl+C) before the swap, the part is rolled back too and the interrupt goes on."""
    report = safe_progress(progress)
    live, staging, old = flavor_path / part, flavor_path / f"{part}.restoring", flavor_path / f"{part}.replaced"
    if os.path.lexists(staging) or os.path.lexists(old):
        raise SwapError(f"{staging.name} or {old.name} is left from an interrupted restore", rolled_back=True)
    existed = os.path.lexists(live)
    if existed and not is_real_dir(live):
        raise SwapError(f"{part} is not a plain folder (a link or a file); it was left alone", rolled_back=True)
    moved: list[str] = []
    old_moved = False
    try:
        _extract(zf, part, files, staging, report)
        report("swap", 0, 0, part)
        _move_links(live, staging, keep_links, moved, rename)
        if existed:
            rename(live, old)
            old_moved = True
        rename(staging, live)
    except BaseException as exc:
        problem = _roll_back(live, staging, old, moved, old_moved, rename)
        if not isinstance(exc, _PART_ERRORS):
            raise
        raise SwapError(f"{part} could not be replaced: {exc}" + (f"; {problem}" if problem else ""),
                        rolled_back=problem is None) from exc
    if on_swapped is not None:
        on_swapped()
    if not existed:
        return None
    report("cleanup", 0, 0, to_stored(old))
    try:
        remove_tree_no_follow(old)
    except OSError as exc:
        return f"the old copy could not be fully deleted: {to_stored(old)} ({exc.strerror or exc})"
    return None


def log_part(flavor: Flavor, outcome: PartOutcome, *, undo: bool = False) -> None:
    """One part's outcome: part_restored, replaced_left, or (a failure) part_rolled_back / undo_failed; a part
    that could not be put back exactly is logged at error."""
    event = {"restored": "ibackup.part_restored", "replaced_left": "ibackup.replaced_left"}.get(
        outcome.kind, "ibackup.undo_failed" if undo else "ibackup.part_rolled_back")
    log_event(event, level="error" if outcome.kind == "failed" else None, flavor=flavor.folder, part=outcome.part,
              kind=outcome.kind, reason=outcome.reason, undo=undo)


def _prune(root: Path, journal_dir: Path, keep_journals: int, current: Path) -> None:
    """Keep the newest keep_journals journals, then delete the safety zips no remaining journal names. Skipped when
    this run's journal would not be kept (a clock set back), so its safety zip is never lost."""
    if current not in list_journals(journal_dir)[:max(1, keep_journals)]:
        return
    pruned = prune_journals(journal_dir, keep_journals)
    referenced = referenced_safety_zips(journal_dir)
    dropped = prune_safety(root, referenced) if referenced is not None else []
    if pruned or dropped:
        log_event("ibackup.journal_pruned", journals=[p.name for p in pruned], safety=[p.name for p in dropped])


def _check_parts(scan: FlavorScan, parts: tuple[str, ...]) -> None:
    linked = [p for p in parts if scan.parts[p].linked]
    if linked:
        raise RestoreError(f"{' and '.join(linked)} turned into a link to another folder; restore it by hand")


def restore(plan: RestorePlan, *, root: Path, journal_dir: Path, keep_journals: int, now: datetime | None = None,
            progress: Callable[..., None] | None = None, rename: Rename = os.rename) -> RestoreResult:
    """Restore the plan's parts: open the journal, verify the backup, write and verify a safety backup of the parts
    as they are now, then replace each part (one that fails is rolled back and the next one goes on), then prune
    journals and safety zips. Stages: verify, safety, safety_verify, extract, swap, cleanup. Raises RestoreError
    (nothing changed) or RestoreStopped (stopped part-way; the journal holds what was done)."""
    report = safe_progress(progress)
    flavor, contents = plan.flavor, plan.contents
    leftovers = leftover_folders(flavor)
    if leftovers:
        raise RestoreError("a folder from an interrupted restore is still there: "
                           + ", ".join(to_stored(p) for p in leftovers))
    when = now or datetime.now()
    result = RestoreResult(flavor, contents.path)
    writer = JournalWriter(new_journal_path(journal_dir, when),
                           {"flavor": flavor.folder, "flavor_path": flavor.path, "backup": contents.path,
                            "parts": list(plan.parts), "suite_version": __version__})
    try:
        writer.open()
    except OSError as exc:
        raise RestoreError(f"the restore journal cannot be written: {exc}") from exc
    result.journal_path = writer.path
    log_event("ibackup.restore_started", flavor=flavor.folder, backup=to_stored(contents.path),
              parts=list(plan.parts), removed=len(plan.removed), newer=len(plan.newer),
              links_kept=len(plan.links_kept), links_removed=len(plan.links_removed))
    try:
        try:
            verify_backup(contents.path, contents.sizes(),
                          progress=lambda i, n, name: report("verify", i, n, name))
        except (BackupError, *ZIP_ERRORS) as exc:
            raise RestoreError(f"the backup did not verify, nothing was changed: {exc}") from exc
        scan = scan_flavor(flavor, with_stats=False, parts=plan.parts)
        _check_parts(scan, plan.parts)
        safety = new_backup_path(root, flavor.short_name, when, kind=SAFETY)
        try:
            stats = write_zip(scan, safety, kind=SAFETY, parts=plan.parts,
                              progress=lambda s, i, n, d: report("safety" if s == "backup" else "safety_verify",
                                                                 i, n, d))
        except BackupError as exc:
            raise RestoreError(f"the safety backup failed, nothing was changed: {exc}") from exc
        try:
            writer.add_entry({"action": "safety_backup", "zip": safety, "parts_existing": stats.parts_existing})
        except OSError as exc:
            try:
                safety.unlink()
            except OSError:
                pass
            raise RestoreError(f"the restore journal cannot be written, nothing was changed: {exc}") from exc
        result.safety_zip = safety
        log_event("ibackup.safety_created", flavor=flavor.folder, path=to_stored(safety), files=stats.files,
                  parts_existing=stats.parts_existing, missing=len(stats.missing))
        with zipfile.ZipFile(contents.path) as zf:
            for part in plan.parts:
                keep = [rel for p, rel in plan.links_kept if p == part]
                entry = {"action": "replaced", "part": part, "existed": part in stats.parts_existing}
                try:
                    left = replace_part(zf, contents.files[part], flavor.path, part, keep, progress=report,
                                        rename=rename, on_swapped=lambda entry=entry: writer.add_entry(entry))
                except SwapError as exc:
                    outcome = PartOutcome(part, "rolled_back" if exc.rolled_back else "failed", str(exc))
                else:
                    outcome = PartOutcome(part, "replaced_left" if left else "restored", left or "")
                result.parts.append(outcome)
                log_part(flavor, outcome)
        writer.finish()
    except RestoreError as exc:
        log_event("ibackup.restore_failed", flavor=flavor.folder, error=str(exc))
        raise
    except Exception as exc:
        log_event("ibackup.restore_stopped", flavor=flavor.folder, error=f"{type(exc).__name__}: {exc}",
                  journal=to_stored(writer.path))
        raise RestoreStopped(f"{type(exc).__name__}: {exc}", result) from exc
    finally:
        writer.discard_if_empty()
    log_event("ibackup.restore_completed", level=None if result.ok else "warning", flavor=flavor.folder,
              parts={p.part: p.kind for p in result.parts}, ok=result.ok)
    report("cleanup", 0, 0, "journals")
    _prune(root, journal_dir, keep_journals, writer.path)
    return result
