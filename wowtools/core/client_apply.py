"""Write client files safely (config tools spec X5): the Config Copier, Macro Editor and Config Editor change files in
account and character folders (macros-cache.txt, config-cache.wtf, ...) and WTF/Config.wtf, outside SavedVariables.
UI-free.

Not a second pipeline: every run goes through the SavedVariables one (core/sv_apply.apply_flavor / apply_flavors,
core/sv_undo.undo_run / recover, core/sv_journal), with two things plugged in. ClientFileGuard replaces SvGuard: it
takes only the tool's own file names (X4), directly in an account folder, in a real character's folder (X3,
core/install.is_character_name) or, for Config.wtf, in WTF itself, and nothing under a link. client_destination maps
journal and marker entries back the same way (STD-5.25). A ClientChange whose expected_sha256 is None is a file the
run creates: sv_apply refuses it if it exists, creates it without ever replacing one, journals it "created", and
Undo or recovery delete it only while it is still what the run wrote. Everything else (refused while that flavor's
WoW runs, dry run, earlier-marker refusal, SHA-256 recheck, lock probe, whole-WTF snapshot, originals zip, crash
marker, atomic write and read-back, roll-back, one journal, Undo of the last run) is the shared pipeline's, so the
two cannot drift apart. cache.md5 and .old files are never in a tool's names (V2), so the guard refuses them.

A tool on this pipeline registers core/sv_events.client_events(<its prefix>) (adds file_created and file_removed).
"""
from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from wowtools.core import sv_apply, sv_undo
from wowtools.core.fsutil import atomic_create_bytes, atomic_write_bytes, is_link
from wowtools.core.install import Character, Flavor, is_character_name
from wowtools.core.sv_apply import ApplyProgress, Marker, MultiApplyResult
from wowtools.core.sv_events import SvTool
from wowtools.core.sv_undo import UndoResult
from wowtools.core.svfiles import SvFile, SvFileError, lstat_or_none
from wowtools.core.undo import safe_destination

__all__ = ["CONFIG_WTF", "EXISTS", "ClientChange", "ClientFileGuard", "apply_client_changes", "apply_client_flavors",
           "client_destination", "client_rel_ok", "client_undo_flavors", "recover_client_run", "undo_client_run"]

CONFIG_WTF = "Config.wtf"  # the machine-level file, directly in <flavor>/WTF
EXISTS = sv_apply.EXISTS
_SAVED_VARIABLES = "SavedVariables"


@dataclass(frozen=True)
class ClientChange:
    """One file a run writes: its new bytes, and the SHA-256 the review saw (None: it must not exist yet, the run
    creates it). changes: one line per change, for the journal, the dry run and the log."""
    path: Path
    new: bytes
    expected_sha256: str | None
    changes: tuple[str, ...] = field(default=())


def client_rel_ok(parts: Sequence[str], names: Iterable[str]) -> bool:
    """Whether a flavor-relative path (its parts) is one the tool may touch: a name in `names`, either
    WTF/Account/<A>/<name> or WTF/Account/<A>/<Realm>/<Char>/<name> with a real character name (and no
    SavedVariables folder in between), or WTF/Config.wtf when Config.wtf is one of the names."""
    parts = tuple(parts)
    if not parts or parts[-1] not in set(names) or any(p in ("", ".", "..") for p in parts):
        return False
    if parts[-1] == CONFIG_WTF:
        return parts == ("WTF", CONFIG_WTF)
    if len(parts) not in (4, 6) or parts[:2] != ("WTF", "Account") or _SAVED_VARIABLES in parts[2:-1]:
        return False
    return len(parts) == 4 or is_character_name(parts[4])


class ClientFileGuard:
    """Refuses (svfiles.SvFileError) any path but a listed client file of the flavor (client_rel_ok), and any path
    that is a link or passes through one below the flavor folder. Each parent folder is resolved once."""

    def __init__(self, flavor: Flavor, names: frozenset[str]) -> None:
        self.flavor = flavor
        self.names = frozenset(names)
        self.root = flavor.path.resolve()
        self.parents: dict[Path, Path] = {}

    def check(self, path: Path, info: os.stat_result | None = None) -> Path:
        """The path, resolved, when the tool may touch it."""
        path = Path(path)
        try:
            rel = path.relative_to(self.flavor.path)
        except ValueError:
            raise SvFileError(f"Refusing to touch {path}: it is outside {self.flavor.wtf_dir}") from None
        if not client_rel_ok(rel.parts, self.names):
            raise SvFileError(f"Refusing to touch {path}: it is not one of the files this tool changes, directly in "
                              f"an account or character folder")
        info = lstat_or_none(path) if info is None else info
        if (info is not None and stat.S_ISLNK(info.st_mode)) or is_link(path):
            raise SvFileError(f"Refusing to touch {path}: it is a link")
        parent = self.parents.get(path.parent)
        if parent is None:
            parent = self.parents[path.parent] = path.parent.resolve()
        if parent != self.root.joinpath(*rel.parts[:-1]):
            raise SvFileError(f"Refusing to touch {path}: a folder on its way is a link")
        return parent / path.name


def client_destination(names: frozenset[str]) -> sv_undo.Destination:
    """sv_undo's dest_for for these names: <WoW>/<flavor>/<rel> when safe_destination and client_rel_ok take it."""
    def client_file(wow_root: Path, flavor: str, rel: str) -> Path | None:
        path = safe_destination(wow_root, flavor, rel, prefix=("WTF",), min_parts=2)
        if path is None or not client_rel_ok(PurePosixPath(rel).parts, names):
            return None
        return path
    return client_file


def client_undo_flavors(wow_root: Path, entries: Iterable[dict], names: frozenset[str]) -> list[Flavor]:
    """sv_undo.undo_flavors with client_destination: the flavors an Undo of these entries backs up."""
    return sv_undo.undo_flavors(wow_root, entries, client_destination(names))


@dataclass
class _Edit:
    data: bytes
    changes: list[str]


def _unit_file(flavor: Flavor, change: ClientChange) -> SvFile:
    """The pipeline's SvFile for a change: account and character read from the path (empty for Config.wtf or a
    path the guard then refuses)."""
    account, character = "", None
    try:
        parts = change.path.relative_to(flavor.account_dir).parts
    except ValueError:
        parts = ()
    if len(parts) >= 2:
        account = parts[0]
    if len(parts) == 4:
        character = Character(parts[0], parts[1], parts[2], change.path.parent)
    info = lstat_or_none(change.path)
    return SvFile(change.path, flavor, account, character, info.st_size if info else 0,
                  info.st_mtime if info else 0.0, change.expected_sha256)


def _compile(file: SvFile, change: ClientChange, data: bytes) -> _Edit:
    default = "created" if change.expected_sha256 is None else "replaced"
    return _Edit(change.new, list(change.changes) or [default])


def _verify(edit: _Edit, data: bytes) -> list[str]:
    """The tool built and checked the new bytes; the pipeline only makes sure they are bytes."""
    return [] if isinstance(edit.data, bytes) else ["the new content is not bytes"]


def apply_client_changes(tool: SvTool, flavor: Flavor, changes: Sequence[ClientChange], *, names: frozenset[str],
                         root: Path, journal_dir: Path, keep_journals: int, keep_snapshots: int, dry_run: bool,
                         wow_check: Callable[[], list[str] | None] | None, now: datetime | None = None,
                         progress: ApplyProgress | None = None,
                         write: Callable[[Path, bytes], None] = atomic_write_bytes,
                         create: Callable[[Path, bytes], None] = atomic_create_bytes) -> MultiApplyResult:
    """Write one flavor's changes as one run (one journal, one Undo). wow_check runs now, at Apply (WowRunning:
    nothing written). A change refused by the guard stops the run before anything is written (result.stopped); one
    whose file changed since the review (or, to be created, exists) is skipped and the rest are written, as in
    every run of the pipeline. write and create are the file writers (tests replace them)."""
    report = None if progress is None else (lambda _flavor, *args: progress(*args))
    return apply_client_flavors(tool, [(flavor, changes)], names=names, root=root, journal_dir=journal_dir,
                                keep_journals=keep_journals, keep_snapshots=keep_snapshots, dry_run=dry_run,
                                wow_check=wow_check, now=now, progress=report, write=write, create=create)


def apply_client_flavors(tool: SvTool, plan: Sequence[tuple[Flavor, Sequence[ClientChange]]], *,
                         names: frozenset[str], root: Path, journal_dir: Path, keep_journals: int,
                         keep_snapshots: int, dry_run: bool, wow_check: Callable[[], list[str] | None] | None,
                         now: datetime | None = None,
                         progress: Callable[[Flavor, str, int, int, str], None] | None = None,
                         write: Callable[[Path, bytes], None] = atomic_write_bytes,
                         create: Callable[[Path, bytes], None] = atomic_create_bytes) -> MultiApplyResult:
    """apply_client_changes over several flavors (the Macro Editor's Apply, ME13): each (flavor, changes) in order
    under one journal, so one Undo puts them all back. wow_check runs once, before anything (it should cover every
    flavor of the plan); each flavor has its own guard, so a change outside its flavor's folder stops that flavor
    before it writes, and the flavors after it are not started (sv_apply.apply_flavors)."""
    def apply_one(one: Flavor, payload: list[tuple[SvFile, ClientChange]], **kwargs: Any) -> sv_apply.ApplyResult:
        return sv_apply.apply_flavor(tool, one, payload, _compile, _verify, guard=ClientFileGuard(one, names),
                                     write=write, create=create,
                                     started={"files": len(payload),
                                              "created": sum(c.expected_sha256 is None for _, c in payload)},
                                     **kwargs)
    units = [(flavor, [(_unit_file(flavor, change), change) for change in changes]) for flavor, changes in plan]
    return sv_apply.apply_flavors(tool, units, apply_one, root=root, journal_dir=journal_dir,
                                  keep_journals=keep_journals, keep_snapshots=keep_snapshots, dry_run=dry_run,
                                  wow_check=wow_check, now=now, progress=progress)


def undo_client_run(tool: SvTool, journal_path: Path, *, wow_root: Path, root: Path, keep_snapshots: int,
                    names: frozenset[str], wow_check: Callable[[], list[str] | None] | None = None,
                    now: datetime | None = None, progress: Callable[[str, int, int, str], None] | None = None,
                    parallelism: int = 1, **kwargs: Any) -> UndoResult:
    """sv_undo.undo_run with client_destination: replaced files put back, created ones deleted, each only while it
    is still what the run wrote. kwargs: on_flavor, on_flavor_done."""
    return sv_undo.undo_run(tool, journal_path, wow_root=wow_root, root=root, keep_snapshots=keep_snapshots,
                            wow_check=wow_check, now=now, progress=progress, parallelism=parallelism,
                            dest_for=client_destination(names), **kwargs)


def recover_client_run(tool: SvTool, marker: Marker, *, wow_root: Path, root: Path, names: frozenset[str],
                       **kwargs: Any) -> UndoResult:
    """sv_undo.recover with client_destination. kwargs: journal_dir, keep_snapshots, wow_check, now, progress.
    Leave as is needs nothing of its own: sv_undo.leave."""
    return sv_undo.recover(tool, marker, wow_root=wow_root, root=root, dest_for=client_destination(names), **kwargs)
