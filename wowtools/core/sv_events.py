"""Who runs the shared SavedVariables write pipeline (core/sv_apply.py, sv_undo.py): the tool's name (its folders,
journal and zip headers) and its event prefix, plus the pipeline's event specs under that prefix. UI-free.

Events stay per tool (SV Browser spec D20): each tool registers sv_events(<its prefix>) with its own events, so the
Ace3 Profile Manager keeps its ace.* names and the SV Browser gets svb.* ones with the same levels and texts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from wowtools.core.events import EventSpec
from wowtools.core.journal import ToolJournals
from wowtools.core.sv_journal import read_edit_journal

# name after the prefix -> (level, description)
_EVENTS: dict[str, tuple[str, str]] = {
    "apply_started": ("info", "Apply (or a dry run) of the pending changes started."),
    "wow_running": ("warning", "Apply or Undo was refused because WoW of that flavor is running."),
    "file_changed": ("warning", "A file changed since the scan; its changes were skipped."),
    "file_locked": ("error", "Apply or Undo stopped before changing anything: files are locked by another program."),
    "probe_recovered": ("warning", "A SavedVariables file left as <name>.wowtools-lockcheck by an interrupted lock check was renamed back."),
    "snapshot_taken": ("info", "The whole-WTF snapshot was written and verified."),
    "snapshot_failed": ("error", "The whole-WTF snapshot failed; nothing was changed."),
    "files_backed_up": ("info", "The originals of the files to change were zipped and verified."),
    "backup_failed": ("error", "The zip of the original files failed; nothing was changed."),
    "earlier_unfinished": ("error", "Apply was refused: an earlier Apply did not finish (its crash marker is there); nothing was changed."),
    "marker_failed": ("error", "The crash marker could not be written; nothing was changed."),
    "marker_left": ("warning", "Apply finished but its crash marker could not be removed (another program held it); the next scan offers the run as unfinished, and putting the originals back then only removes the marker."),
    "marker_stale": ("info", "Recovery found that the run named by the crash marker had finished (its journal says so for every file it wrote, and the files it skipped are not at what it would have written): no file was changed, only the marker is removed (logged at warning with marker_left when it could not be removed either: the next scan offers it again)."),
    "file_edited": ("info", "A SavedVariables file was rewritten with the pending changes."),
    "would_edit": ("info", "Dry run: a file that would be rewritten, with its changes (checked, not written)."),
    "verify_failed": ("error", "An edited file did not re-read as expected; it was not written and the run stopped."),
    "write_failed": ("error", "A SavedVariables file could not be written; the run stopped."),
    "rolled_back": ("warning", "After a failure, the files this run had already written were put back."),
    "rollback_failed": ("error", "A file could not be put back after a failure; restore it from the zip the message names."),
    "apply_completed": ("info", "Apply finished (logged at warning if any file was skipped or failed)."),
    "dry_run_completed": ("info", "A dry run finished."),
    "flavors_stopped": ("warning", "An Apply over several flavors stopped at one flavor; the flavors after it were not started."),
    "snapshot_discarded": ("info", "A whole-WTF snapshot taken before an Undo whose other snapshot failed was deleted: nothing was changed, so it protected nothing."),
    "snapshots_pruned": ("info", "Older whole-WTF snapshots of the flavor were deleted to keep the newest N (keep_backups)."),
    "journal_failed": ("error", "The run journal could not be written; nothing was changed."),
    "journal_pruned": ("info", "Older journals (and the zips only they used) were deleted to keep the newest N (keep_journals)."),
    "undo_started": ("info", "Undo last change started, from the newest journal."),
    "file_restored": ("info", "Undo or recovery: a file was put back to its original bytes."),
    "file_skipped": ("warning", "Undo or recovery: a file was left alone (it changed since the run, or is outside the WTF folder)."),
    "undo_failed": ("error", "Undo or recovery: a file could not be put back (its zip is missing or does not match)."),
    "undo_completed": ("info", "Undo last change finished (logged at warning if any file was skipped or failed)."),
    "recovery_offered": ("warning", "A marker from an Apply that did not finish was found by a scan (on opening or a rescan), or Apply was pressed while it is there."),
    "recovery_done": ("info", "The user chose what to do about an unfinished Apply (put back or leave); logged at warning with marker_left when its crash marker could not be removed (the next scan offers it again)."),
}


def sv_events(prefix: str) -> dict[str, EventSpec]:
    """The pipeline's events named <prefix>.<event>, for the tool to register with its own."""
    return {f"{prefix}.{name}": EventSpec(level, text) for name, (level, text) in _EVENTS.items()}


@dataclass
class SvTool:
    """A tool on the pipeline: name is its TOOL_NAME, prefix its event prefix (ace, svb). journals is its
    ToolJournals (journal folder, reader, pruned event)."""
    name: str
    prefix: str
    journals: ToolJournals = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.journals = ToolJournals(self.name, read_edit_journal, self.event("journal_pruned"))

    def event(self, name: str) -> str:
        return f"{self.prefix}.{name}"
