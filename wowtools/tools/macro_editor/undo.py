"""Undo the latest Apply, and recover from one that did not finish (config tools spec ME13): the shared client-file
pipeline's undo (core/client_apply.py over core/sv_undo.py) under this tool's name, events and file names. Every
replaced file is put back and every created one deleted, each only while it is still what the run wrote; Leave
keeps the files as they are and drops the marker. UI-free."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from wowtools.core import client_apply, sv_undo
from wowtools.core.install import Flavor
from wowtools.core.sv_apply import Marker, read_marker
from wowtools.core.sv_undo import CHANGED_SINCE, UndoError, UndoOutcome, UndoResult, WowRunning
from wowtools.tools.macro_editor.events import SV_TOOL
from wowtools.tools.macro_editor.runner import NAMES

__all__ = ["CHANGED_SINCE", "UndoError", "UndoOutcome", "UndoResult", "WowRunning", "leave", "pending_recovery",
           "recover", "undo_flavors", "undo_run"]


def undo_run(journal_path: Path, **options) -> UndoResult:
    """core/client_apply.undo_client_run's options (wow_root, root, keep_snapshots, wow_check, now, progress,
    parallelism, on_flavor, on_flavor_done)."""
    return client_apply.undo_client_run(SV_TOOL, journal_path, names=NAMES, **options)


def undo_flavors(wow_root: Path, entries: Iterable[dict]) -> list[Flavor]:
    """The flavors an Undo of these journal entries backs up first (one progress row each)."""
    return client_apply.client_undo_flavors(wow_root, entries, NAMES)


def pending_recovery(root: Path | None) -> Marker | None:
    """The marker of an Apply that did not finish (offered on start and on a rescan), or None."""
    return read_marker(root)


def recover(marker: Marker, **options) -> UndoResult:
    """Put back: core/client_apply.recover_client_run's options (wow_root, root, journal_dir, keep_snapshots,
    wow_check, now, progress)."""
    return client_apply.recover_client_run(SV_TOOL, marker, names=NAMES, **options)


def leave(marker: Marker, *, root: Path) -> bool:
    """Leave as is: core/sv_undo.leave (False when the marker could not be removed)."""
    return sv_undo.leave(SV_TOOL, marker, root=root)
