"""Undo the latest Apply, and recover from one that did not finish (spec §10): the shared core/sv_undo.py under this
tool's name and events. UI-free."""
from __future__ import annotations

from pathlib import Path

from wowtools.core import sv_undo
from wowtools.core.sv_apply import Marker
from wowtools.core.sv_undo import (CHANGED_SINCE, UndoError, UndoOutcome, UndoResult, WowRunning, destination,
                                    undo_flavors)
from wowtools.tools.ace3_profile_manager.events import SV_TOOL

__all__ = ["CHANGED_SINCE", "UndoError", "UndoOutcome", "UndoResult", "WowRunning", "destination", "leave",
           "recover", "undo_flavors", "undo_run"]


def undo_run(journal_path: Path, **options) -> UndoResult:
    """core/sv_undo.undo_run's options (wow_root, root, keep_snapshots, wow_check, now, progress, parallelism,
    on_flavor, on_flavor_done)."""
    return sv_undo.undo_run(SV_TOOL, journal_path, **options)


def recover(marker: Marker, **options) -> UndoResult:
    """core/sv_undo.recover's options (wow_root, root, journal_dir, keep_snapshots, wow_check, now, progress)."""
    return sv_undo.recover(SV_TOOL, marker, **options)


def leave(marker: Marker, *, root: Path) -> bool:
    """Leave as is: core/sv_undo.leave (False when the marker could not be removed)."""
    return sv_undo.leave(SV_TOOL, marker, root=root)
