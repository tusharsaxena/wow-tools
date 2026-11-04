"""Run the staged CVar changes (config tools spec CE8, X5): every file whose bytes change becomes a ClientChange
(ops.build_changes: lines not changed keep their bytes and place, added lines are appended with the file's own line
ending) for the shared client-file pipeline (core/client_apply.py: refused while WoW runs, dry run, SHA-256 recheck
against what the scan read, whole-WTF snapshot, originals zip, crash marker, journal, atomic write and read-back).
One Apply is one run over every flavor it touches, so one journal and one Undo. Only Config.wtf (directly in WTF)
and config-cache.wtf (in an account or a real character folder) are ever written (the guard refuses anything else,
X4); a file that does not exist yet is created, never over one that appeared since. UI-free."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from wowtools.core.client_apply import ClientChange, apply_client_flavors
from wowtools.core.install import Flavor
from wowtools.core.sv_apply import ApplyError, MultiApplyResult, WowRunning
from wowtools.tools.config_editor.events import SV_TOOL
from wowtools.tools.config_editor.model import FILE_NAMES, ConfigTarget
from wowtools.tools.config_editor.ops import ConfigStaged, build_changes

__all__ = ["NAMES", "ApplyError", "WowRunning", "changes_by_flavor", "run_apply"]

NAMES = FILE_NAMES  # the only files the pipeline may touch for this tool


def changes_by_flavor(staged: ConfigStaged,
                      targets: Sequence[ConfigTarget]) -> list[tuple[Flavor, list[ClientChange]]]:
    """The staged changes as the pipeline takes them: (flavor, its ClientChanges), flavors and files in `targets`
    order, a flavor with nothing to write left out."""
    flavor_of = {target.path: target.flavor for target in targets}
    out: dict[str, tuple[Flavor, list[ClientChange]]] = {}
    for change in build_changes(staged, targets):
        flavor = flavor_of[change.path]
        out.setdefault(flavor.folder, (flavor, []))[1].append(change)
    return list(out.values())


def run_apply(staged: ConfigStaged, targets: Sequence[ConfigTarget], *, root: Path, journal_dir: Path,
              keep_journals: int, keep_snapshots: int, dry_run: bool, wow_check, now: datetime | None = None,
              progress=None) -> MultiApplyResult:
    """Write everything staged as one run. Raises WowRunning (nothing written) for a real run while WoW runs; a
    file changed since the scan (or, to be created, that exists now) is skipped and the rest written, as on every
    run of the pipeline. `progress(flavor, stage, current, total, detail)`."""
    return apply_client_flavors(SV_TOOL, changes_by_flavor(staged, targets), names=NAMES, root=root,
                                journal_dir=journal_dir, keep_journals=keep_journals, keep_snapshots=keep_snapshots,
                                dry_run=dry_run, wow_check=wow_check, now=now, progress=progress)
