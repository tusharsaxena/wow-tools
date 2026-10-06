"""Apply a plan (ops.Plan: the staged edits plus the ticked results, one FilePlan per file) to the SavedVariables
files (spec D13-D17): the shared pipeline (core/sv_apply.py: WoW-running refusal, guard, recheck of each file's
SHA-256, journal, lock probe, WTF snapshot, originals zip, crash marker, atomic writes, roll-back) with this tool's
compile (compile.compile_file) and verify (verify.verify_edit) per file, one flavor after another under one journal.
UI-free."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from wowtools.core import sv_apply
from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.install import Flavor
from wowtools.core.sv_apply import (ApplyError, ApplyProgress, ApplyResult, FileOutcome, FlavorRun, Marker,
                                    MultiApplyResult, WowRunning, clear_marker, read_marker)
from wowtools.core.sv_journal import EditJournal
from wowtools.core.svfiles import SvFile
from wowtools.tools.sv_browser.compile import compile_file
from wowtools.tools.sv_browser.events import SV_TOOL
from wowtools.tools.sv_browser.ops import FilePlan, Plan
from wowtools.tools.sv_browser.verify import verify_edit

__all__ = ["ApplyError", "ApplyResult", "FileOutcome", "FlavorRun", "Marker", "MultiApplyResult", "WowRunning",
           "apply_flavor", "apply_plan", "clear_marker", "flavor_plan", "read_marker"]

Units = list[tuple[SvFile, FilePlan]]


def flavor_plan(plan: Plan) -> list[tuple[Flavor, Units]]:
    """The plan's files grouped by flavor, flavors and files in plan order (the staging's, then the hits')."""
    grouped: dict[Path, tuple[Flavor, Units]] = {}
    for file, file_plan in plan.units():
        grouped.setdefault(file.flavor.path, (file.flavor, []))[1].append((file, file_plan))
    return list(grouped.values())


def _verify(edit, data: bytes) -> list[str]:
    return verify_edit(edit, data)  # looked up per call, so a test can patch it here


def apply_flavor(flavor: Flavor, units: Units, *, root: Path, journal: EditJournal | None, dry_run: bool,
                 keep_snapshots: int, account: str | None = None, now: datetime | None = None,
                 progress: ApplyProgress | None = None,
                 write: Callable[[Path, bytes], None] = atomic_write_bytes) -> ApplyResult:
    """One flavor's files. Raises ApplyError when refused or stopped; its result holds what was done until then."""
    return sv_apply.apply_flavor(SV_TOOL, flavor, units, compile_file, _verify, root=root, journal=journal,
                                 dry_run=dry_run, keep_snapshots=keep_snapshots, account=account, now=now,
                                 progress=progress, write=write,
                                 started={"files": len(units), "edits": sum(len(p.edits) for _, p in units)})


def apply_plan(plan: Plan, **options) -> MultiApplyResult:
    """core/sv_apply.apply_flavors's options (root, journal_dir, keep_journals, keep_snapshots, dry_run, wow_check,
    now, progress). Raises WowRunning (before anything is done) for a real run while WoW runs; a flavor that is
    refused or stopped ends the run (result.stopped), the rest "not started"."""
    return sv_apply.apply_flavors(SV_TOOL, flavor_plan(plan),
                                  lambda flavor, units, **kw: apply_flavor(flavor, units, **kw), **options)
