"""Undo the latest Apply, and recover from one that did not finish (spec D15): the shared core/sv_undo.py under
this tool's name and events, plus Leave (keep the files as they are, drop the marker). UI-free."""
from __future__ import annotations

from pathlib import Path

from wowtools.core import sv_undo
from wowtools.core.events import log_event
from wowtools.core.sv_apply import Marker, clear_marker, read_marker
from wowtools.core.sv_undo import (CHANGED_SINCE, UndoError, UndoOutcome, UndoResult, WowRunning, destination,
                                    undo_flavors)
from wowtools.tools.sv_browser.events import SV_TOOL

__all__ = ["CHANGED_SINCE", "UndoError", "UndoOutcome", "UndoResult", "WowRunning", "destination", "leave",
           "pending_recovery", "recover", "undo_flavors", "undo_run"]


def undo_run(journal_path: Path, **options) -> UndoResult:
    """core/sv_undo.undo_run's options (wow_root, root, keep_snapshots, wow_check, now, progress, parallelism,
    on_flavor, on_flavor_done)."""
    return sv_undo.undo_run(SV_TOOL, journal_path, **options)


def pending_recovery(root: Path | None) -> Marker | None:
    """The marker of an Apply that did not finish (offered on start and on a rescan), or None."""
    return read_marker(root)


def recover(marker: Marker, **options) -> UndoResult:
    """Put back: core/sv_undo.recover's options (root, journal_dir, keep_snapshots, wow_check, now, progress)."""
    return sv_undo.recover(SV_TOOL, marker, **options)


def leave(marker: Marker, *, root: Path) -> None:
    """Leave as is: the files stay as they are now, the originals zip and the WTF backup are kept; only the marker
    goes, so the next Apply is no longer refused."""
    clear_marker(root)
    log_event(SV_TOOL.event("recovery_done"), choice="leave", flavor=marker.flavor, zip=str(marker.zip))
