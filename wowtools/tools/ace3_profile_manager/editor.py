"""Apply staged profile changes to one flavor's SavedVariables (spec §9): the shared pipeline (core/sv_apply.py:
guard, recheck, journal, lock probe, snapshot, originals zip, crash marker, atomic writes, roll-back) with this
tool's compile (ops.compile_file) and verify (verify.verify_edit) per file. UI-free."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from wowtools.core import sv_apply
from wowtools.core.fsutil import atomic_write_bytes
from wowtools.core.install import Flavor
from wowtools.core.sv_apply import (ApplyError, ApplyProgress, ApplyResult, FileOutcome, Marker, clear_marker,
                                    read_marker, write_marker)
from wowtools.core.sv_journal import EditJournal
from wowtools.core.svfiles import SvFile
from wowtools.tools.ace3_profile_manager.events import SV_TOOL
from wowtools.tools.ace3_profile_manager.ops import DbState, FileEdit, compile_file
from wowtools.tools.ace3_profile_manager.verify import verify_edit

__all__ = ["ApplyError", "ApplyResult", "FileOutcome", "Marker", "apply_flavor", "clear_marker", "group_by_file",
           "read_marker", "write_marker"]


def group_by_file(states: list[DbState]) -> dict[Path, list[DbState]]:
    grouped: dict[Path, list[DbState]] = {}
    for state in states:
        grouped.setdefault(state.file.path, []).append(state)
    return grouped


def _compile(file: SvFile, states: list[DbState], data: bytes) -> FileEdit:
    return compile_file(states, data)


def apply_flavor(flavor: Flavor, states: list[DbState], *, root: Path, journal: EditJournal | None,
                 dry_run: bool, keep_snapshots: int, account: str | None = None, now: datetime | None = None,
                 progress: ApplyProgress | None = None,
                 write: Callable[[Path, bytes], None] = atomic_write_bytes) -> ApplyResult:
    """Raises ApplyError when refused or stopped; its result holds what was done until then."""
    units = [(file_states[0].file, file_states) for file_states in group_by_file(states).values()]
    return sv_apply.apply_flavor(SV_TOOL, flavor, units, _compile, verify_edit, root=root, journal=journal,
                                 dry_run=dry_run, keep_snapshots=keep_snapshots, account=account, now=now,
                                 progress=progress, write=write, started={"databases": len(states)})
