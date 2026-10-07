"""Undo a restore: put the parts it replaced back from its safety backup (pre-restore zip), with the same
extract-and-swap as a restore but no further safety backup and no warnings, then make again the links the restore
removed (the journal's `link_removed` entries: a zip never holds a link). UI-free."""
from __future__ import annotations

import os
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

from wowtools.core.backup import BackupError, verify_backup
from wowtools.core.events import log_event
from wowtools.core.fsutil import (is_link, is_real_dir, make_link, remove_tree_no_follow, rename_no_replace,
                                  safe_progress)
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.journal import Journal, mark_undone
from wowtools.core.paths import to_stored
from wowtools.tools.interface_backup.catalog import SAFETY
from wowtools.tools.interface_backup.journal import read_restore_journal
from wowtools.tools.interface_backup.restore import (ZIP_ERRORS, BackupContents, PartOutcome, Rename, RestoreError,
                                                     RestoreResult, RestoreStopped, SwapError, case_key, log_part,
                                                     open_backup, plan_restore, replace_part, split_entry)
from wowtools.tools.interface_backup.scanner import PARTS, leftover_folders, scan_flavor


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _refuse(journal_path: Path, reason: str, cause: BaseException | None = None) -> NoReturn:
    log_event("ibackup.undo_failed", journal=to_stored(journal_path), refused=True, reason=reason)
    raise RestoreError(reason) from cause


def _journal_flavor(journal: Journal, wow_root: Path) -> Flavor | None:
    """The flavor the journal is for, when it is a flavor folder of wow_root (same name and same path)."""
    folder = journal.header.get("flavor")
    flavor_path = journal.header.get("flavor_path")
    flavor = next((f for f in WowInstall(wow_root).flavors() if f.folder == folder), None)
    if flavor is None or not isinstance(flavor_path, Path) or not _same(flavor_path, flavor.path):
        return None
    return flavor


def _replaced_entries(journal: Journal) -> list[tuple[str, bool]] | None:
    """(part, existed) for each `replaced` entry, in journal order; None when one names an unknown part, has no
    yes/no `existed`, or a part comes twice."""
    found: list[tuple[str, bool]] = []
    for entry in journal.entries:
        if entry.get("action") != "replaced":
            continue
        part, existed = entry.get("part"), entry.get("existed")
        if part not in PARTS or not isinstance(existed, bool) or any(part == p for p, _ in found):
            return None
        found.append((part, existed))
    return found


# A link the restore removed: (rel inside the part, target as read_link gave it, a Windows junction).
RemovedLink = tuple[str, str, bool]


def _removed_links(journal: Journal) -> dict[str, list[RemovedLink]] | None:
    """part -> the links the restore removed there, from its `link_removed` entries; None when one is damaged (an
    unknown part, a path that could leave the part folder, no target)."""
    found: dict[str, list[RemovedLink]] = {}
    for entry in journal.entries:
        if entry.get("action") != "link_removed":
            continue
        part, rel, target, junction = entry.get("part"), entry.get("rel"), entry.get("target"), entry.get("junction")
        if (part not in PARTS or not isinstance(rel, str) or not isinstance(target, str) or not target
                or not isinstance(junction, bool)):
            return None
        try:
            split_entry(f"{part}/{rel}", windows=False)
        except RestoreError:
            return None
        found.setdefault(part, []).append((rel, target, junction))
    return found


def _check(journal_path: Path, wow_root: Path,
           root: Path) -> tuple[Flavor, BackupContents, list[tuple[str, bool]], dict[str, list[RemovedLink]]]:
    """Every guard before anything changes; refuses (RestoreError, logged) with the reason."""
    try:
        journal = read_restore_journal(journal_path)
    except (OSError, ValueError) as exc:
        _refuse(journal_path, f"the restore journal cannot be read: {exc}", exc)
    if journal.undone is not None:
        _refuse(journal_path, "this restore was already undone")
    flavor = _journal_flavor(journal, wow_root)
    if flavor is None:
        _refuse(journal_path, "the restore journal is not for a flavor of the configured WoW folder")
    replaced = _replaced_entries(journal)
    if replaced is None:
        _refuse(journal_path, "the restore journal is damaged: a replaced part is not Interface or WTF")
    if not replaced:
        _refuse(journal_path, "the restore replaced nothing, so there is nothing to undo")
    links = _removed_links(journal)
    if links is None:
        _refuse(journal_path, "the restore journal is damaged: a removed link is not valid")
    safety = next((e for e in journal.entries if e.get("action") == "safety_backup"), None)
    zip_path = safety.get("zip") if safety is not None else None
    if not isinstance(zip_path, Path) or not _same(zip_path.parent, root):
        _refuse(journal_path, "the restore's safety backup is not in the backup folder")
    if is_link(zip_path) or not zip_path.is_file():
        _refuse(journal_path, f"the restore's safety backup is gone: {zip_path.name}")
    leftovers = leftover_folders(flavor)
    if leftovers:
        _refuse(journal_path, "a folder from an interrupted restore is still there: "
                + ", ".join(to_stored(p) for p in leftovers))
    try:
        contents = open_backup(zip_path)
    except RestoreError as exc:
        _refuse(journal_path, f"the safety backup cannot be used: {exc}", exc)
    if contents.kind != SAFETY or case_key(contents.flavor_folder) != case_key(flavor.folder):
        _refuse(journal_path, f"{zip_path.name} is not this restore's safety backup")
    absent = [part for part, existed in replaced if existed and part not in contents.parts]
    if absent:
        _refuse(journal_path, f"the safety backup has no {' or '.join(absent)} folder")
    return flavor, contents, replaced, links


def _remove_created(flavor: Flavor, part: str, rename: Rename, report: Callable[..., None]) -> str | None:
    """Take away a part the restore created (it did not exist before): rename it to <part>.replaced, then delete
    that without following links. Returns why it could not be fully deleted, or None. Raises SwapError when it was
    left as it is."""
    live, old = flavor.path / part, flavor.path / f"{part}.replaced"
    if not os.path.lexists(live):
        return None  # already gone: the part is as it was before the restore
    if not is_real_dir(live):
        raise SwapError(f"{part} is not a plain folder (a link or a file); it was left alone", rolled_back=True)
    if os.path.lexists(old):
        raise SwapError(f"{old.name} is left from an interrupted restore", rolled_back=True)
    report("swap", 0, 0, part)
    try:
        rename(live, old)
    except OSError as exc:
        raise SwapError(f"{part} could not be moved away: {exc}", rolled_back=True) from exc
    report("cleanup", 0, 0, to_stored(old))
    try:
        remove_tree_no_follow(old)
    except OSError as exc:
        return f"the restored copy could not be fully deleted: {to_stored(old)} ({exc.strerror or exc})"
    return None


def _make_links_again(live: Path, links: list[RemovedLink]) -> list[str]:
    """Make each link the restore removed from this part again, where nothing is now. Returns what could not be
    made (the link and its target, to make by hand)."""
    problems = []
    for rel, target, junction in links:
        path = live.joinpath(*rel.split("/"))
        try:
            if os.path.lexists(path):
                raise FileExistsError("something else is there now")
            path.parent.mkdir(parents=True, exist_ok=True)
            make_link(target, path, junction=junction)
        except OSError as exc:
            problems.append(f"the link {live.name}/{rel} to {target} could not be made again "
                            f"({exc.strerror or exc}); make it by hand")
    return problems


def _undo_part(zf: zipfile.ZipFile, contents: BackupContents, flavor: Flavor, part: str, existed: bool,
               links: list[RemovedLink], rename: Rename, report: Callable[..., None]) -> PartOutcome:
    try:
        if existed:
            plan = plan_restore(contents, scan_flavor(flavor, with_stats=False, parts=(part,)), (part,))
            keep = [rel for p, rel in plan.links_kept if p == part]
            left = replace_part(zf, contents.files[part], flavor.path, part, keep, progress=report, rename=rename)
        else:
            left = _remove_created(flavor, part, rename, report)
    except SwapError as exc:
        return PartOutcome(part, "rolled_back" if exc.rolled_back else "failed", str(exc))
    except RestoreError as exc:  # the part turned into a link since the restore: nothing touched
        return PartOutcome(part, "rolled_back", str(exc))
    problems = _make_links_again(flavor.path / part, links) if existed else []
    if problems:  # the folder is back, but not exactly: a link is missing
        return PartOutcome(part, "failed", "; ".join(([left] if left else []) + problems))
    return PartOutcome(part, "replaced_left" if left else "restored", left or "")


def undo_restore(journal_path: Path, *, wow_root: Path, root: Path, progress: Callable[..., None] | None = None,
                 rename: Rename = rename_no_replace) -> RestoreResult:
    """Undo the restore journal_path records: each part it replaced, newest first, is put back from its safety
    backup (or taken away again when the restore created it), and the links the restore removed from it are made
    again (a part where one cannot be made is `failed`, its reason naming the link). Guards first: the journal not
    undone, its flavor a flavor folder of wow_root, its parts Interface or WTF, its `link_removed` entries valid,
    its safety backup in `root`, present and verified, no leftover folders; a refusal raises RestoreError with nothing changed. A part that fails is left as it was and
    the next one goes on. The journal is marked undone unless every part was left as it was (then the same Undo
    can be tried again). Stages: verify, extract, swap, cleanup. Raises RestoreStopped when it stopped part-way."""
    report = safe_progress(progress)
    flavor, contents, replaced, links = _check(journal_path, wow_root, root)
    zip_path = contents.path
    try:
        verify_backup(zip_path, contents.sizes(), progress=lambda i, n, name: report("verify", i, n, name))
    except (BackupError, *ZIP_ERRORS) as exc:
        _refuse(journal_path, f"the safety backup did not verify, nothing was changed: {exc}", exc)
    result = RestoreResult(flavor, zip_path, journal_path=journal_path, undo=True)
    log_event("ibackup.undo_started", flavor=flavor.folder, journal=to_stored(journal_path),
              safety=to_stored(zip_path), parts=[part for part, _ in reversed(replaced)])
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for part, existed in reversed(replaced):
                outcome = _undo_part(zf, contents, flavor, part, existed, links.get(part, []), rename, report)
                result.parts.append(outcome)
                log_part(flavor, outcome, undo=True)
        restored = sum(p.kind in ("restored", "replaced_left") for p in result.parts)
        changed = any(p.kind != "rolled_back" for p in result.parts)
        if changed:
            mark_undone(journal_path, restored, len(result.parts) - restored)
    except Exception as exc:
        log_event("ibackup.undo_failed", flavor=flavor.folder, journal=to_stored(journal_path), stopped=True,
                  reason=f"{type(exc).__name__}: {exc}")
        raise RestoreStopped(f"{type(exc).__name__}: {exc}", result) from exc
    log_event("ibackup.undo_completed", level=None if result.ok else "warning", flavor=flavor.folder,
              parts={p.part: p.kind for p in result.parts}, ok=result.ok, marked_undone=changed)
    return result
