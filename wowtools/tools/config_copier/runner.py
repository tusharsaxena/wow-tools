"""Run a copy (config tools spec CC6, CC8, X5): the pairs to write become ClientChanges for the shared client-file
pipeline (core/client_apply.py: refused while that flavor's WoW runs, dry run, SHA-256 recheck against what the
review read, whole-WTF snapshot, originals zip, crash marker, journal, atomic write and read-back, one Undo). Only the
five COPY_FILES names are ever written (the guard refuses anything else, X4); a pair the target has no file for is
created, never over a file that appeared since. UI-free."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from wowtools.core.client_apply import ClientChange, apply_client_changes
from wowtools.core.install import Character, Flavor
from wowtools.core.sv_apply import ApplyError, ApplyProgress, MultiApplyResult, WowRunning
from wowtools.tools.config_copier.events import SV_TOOL
from wowtools.tools.config_copier.model import CONFIG_FILE, COPY_FILES, PairPlan

__all__ = ["COPYABLE", "NAMES", "ApplyError", "WowRunning", "copy_changes", "run_copy"]

NAMES = frozenset(COPY_FILES)  # the only files the pipeline may touch for this tool
COPYABLE = ("new", "replace")  # the statuses a copy writes; unchanged, no-source and unreadable pairs never are


def copy_changes(source: Character, plans: Iterable[PairPlan]) -> list[ClientChange]:
    """One ClientChange per pair that writes something (COPYABLE), in plan order: its target's file, the bytes the
    review planned and the SHA-256 of the file the review read (None: the file is created). Each carries one line
    for the journal, the dry run and the log."""
    changes = []
    for plan in plans:
        if plan.status not in COPYABLE or plan.new is None:
            continue
        verb = "merged from" if plan.name == CONFIG_FILE else "copied from"
        line = f"{plan.name}: {verb} {source.account}/{source.label}"
        changes.append(ClientChange(plan.target.path / plan.name, plan.new, plan.old_sha256, (line,)))
    return changes


def run_copy(flavor: Flavor, source: Character, plans: Sequence[PairPlan], *, root: Path, journal_dir: Path,
             keep_journals: int, keep_snapshots: int, dry_run: bool, wow_check, now: datetime | None = None,
             progress: ApplyProgress | None = None) -> MultiApplyResult:
    """Write the copyable pairs of `plans` (all targets of `flavor`) as one run: one journal, one Undo. Raises
    WowRunning (nothing written) for a real run while that flavor's WoW runs; a pair whose target file changed
    since the review (or appeared, for a new one) is skipped and the rest written, as on every run of the
    pipeline."""
    return apply_client_changes(SV_TOOL, flavor, copy_changes(source, plans), names=NAMES, root=root,
                                journal_dir=journal_dir, keep_journals=keep_journals,
                                keep_snapshots=keep_snapshots, dry_run=dry_run, wow_check=wow_check, now=now,
                                progress=progress)
