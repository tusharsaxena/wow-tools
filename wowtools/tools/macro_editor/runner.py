"""Run the staged macro changes (config tools spec ME13, X5): every set whose bytes change becomes a ClientChange
(ops.build_changes: unchanged macros keep their bytes) for the shared client-file pipeline (core/client_apply.py:
refused while WoW runs, dry run, SHA-256 recheck against what the scan read, whole-WTF snapshot, originals zip, crash
marker, journal, atomic write and read-back). One Apply is one run over every flavor it touches, so one journal and
one Undo. Only macros-cache.txt is ever written (the guard refuses anything else, X4); a set with no file yet gets
one created, never over a file that appeared since. UI-free."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from wowtools.core.client_apply import ClientChange, apply_client_flavors
from wowtools.core.install import Flavor
from wowtools.core.sv_apply import ApplyError, MultiApplyResult, WowRunning
from wowtools.tools.macro_editor.events import SV_TOOL
from wowtools.tools.macro_editor.model import MACRO_FILE, MacroSet
from wowtools.tools.macro_editor.ops import Staged, build_changes

__all__ = ["NAMES", "ApplyError", "WowRunning", "changes_by_flavor", "run_apply"]

NAMES = frozenset({MACRO_FILE})  # the only file the pipeline may touch for this tool


def changes_by_flavor(staged: Staged, sets: Sequence[MacroSet]) -> list[tuple[Flavor, list[ClientChange]]]:
    """The staged changes as the pipeline takes them: (flavor, its ClientChanges), flavors and files in `sets`
    order, a flavor with nothing to write left out."""
    flavor_of = {mset.path: mset.flavor for mset in sets}
    out: dict[str, tuple[Flavor, list[ClientChange]]] = {}
    for change in build_changes(staged, sets):
        flavor = flavor_of[change.path]
        out.setdefault(flavor.folder, (flavor, []))[1].append(change)
    return list(out.values())


def run_apply(staged: Staged, sets: Sequence[MacroSet], *, root: Path, journal_dir: Path, keep_journals: int,
              keep_snapshots: int, dry_run: bool, wow_check, now: datetime | None = None,
              progress=None) -> MultiApplyResult:
    """Write everything staged as one run. Raises WowRunning (nothing written) for a real run while WoW runs; a
    file changed since the scan (or, to be created, that exists now) is skipped and the rest written, as on every
    run of the pipeline. `progress(flavor, stage, current, total, detail)`."""
    return apply_client_flavors(SV_TOOL, changes_by_flavor(staged, sets), names=NAMES, root=root,
                                journal_dir=journal_dir, keep_journals=keep_journals, keep_snapshots=keep_snapshots,
                                dry_run=dry_run, wow_check=wow_check, now=now, progress=progress)
