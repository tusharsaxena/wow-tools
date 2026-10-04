"""Events emitted by the Ace3 Profile Manager. Levels are fixed here; see docs/events.md."""
from __future__ import annotations

from wowtools.core.events import EventSpec, register_events

TOOL_NAME = "ace-profiles"

EVENTS: dict[str, EventSpec] = {
    "ace.scan_started": EventSpec("info", "A scan of one flavor's SavedVariables for AceDB databases started."),
    "ace.scan_completed": EventSpec("info", "A scan finished, with counts (files, databases, profiles, characters, leftover characters, seconds)."),
    "ace.file_unreadable": EventSpec("warning", "A SavedVariables file or folder could not be read; it is left out."),
    "ace.parse_failed": EventSpec("warning", "A SavedVariables file is not readable Lua; it is shown as a warning and never changed."),
    "ace.lookalike": EventSpec("debug", "A table looks like an AceDB database but is not one; it is left alone."),
    "ace.staged": EventSpec("debug", "A change was staged on the review screen (operation and counts)."),
    "ace.blacklist_changed": EventSpec("info", "A (flavor, addon) pair was added to or removed from the blacklist (flavor, addon, blacklisted), or the whole list was saved from the blacklist screen (pairs)."),
    "ace.unlocked": EventSpec("info", "A blacklisted addon of one flavor was unlocked for this session, or locked again (unlocked=false)."),
    "ace.apply_started": EventSpec("info", "Apply (or a dry run) of the staged changes started."),
    "ace.wow_running": EventSpec("warning", "Apply or Undo was refused because WoW of that flavor is running."),
    "ace.file_changed": EventSpec("warning", "A file changed since the scan; its changes were skipped."),
    "ace.file_locked": EventSpec("error", "Apply or Undo stopped before changing anything: files are locked by another program."),
    "ace.probe_recovered": EventSpec("warning", "A SavedVariables file left as <name>.wowtools-lockcheck by an interrupted lock check was renamed back."),
    "ace.snapshot_taken": EventSpec("info", "The whole-WTF snapshot was written and verified."),
    "ace.snapshot_failed": EventSpec("error", "The whole-WTF snapshot failed; nothing was changed."),
    "ace.files_backed_up": EventSpec("info", "The originals of the files to change were zipped and verified."),
    "ace.backup_failed": EventSpec("error", "The zip of the original files failed; nothing was changed."),
    "ace.earlier_unfinished": EventSpec("error", "Apply was refused: an earlier Apply did not finish (its crash marker is there); nothing was changed."),
    "ace.marker_failed": EventSpec("error", "The crash marker could not be written; nothing was changed."),
    "ace.file_edited": EventSpec("info", "A SavedVariables file was rewritten with the staged changes."),
    "ace.would_edit": EventSpec("info", "Dry run: a file that would be rewritten, with its changes (checked, not written)."),
    "ace.verify_failed": EventSpec("error", "An edited file did not re-read as expected; it was not written and the run stopped."),
    "ace.write_failed": EventSpec("error", "A SavedVariables file could not be written; the run stopped."),
    "ace.rolled_back": EventSpec("warning", "After a failure, the files this run had already written were put back."),
    "ace.rollback_failed": EventSpec("error", "A file could not be put back after a failure; restore it from the zip the message names."),
    "ace.apply_completed": EventSpec("info", "Apply finished (logged at warning if any file was skipped or failed)."),
    "ace.dry_run_completed": EventSpec("info", "A dry run finished."),
    "ace.flavors_stopped": EventSpec("warning", "An Apply over several flavors stopped at one flavor; the flavors after it were not started."),
    "ace.snapshots_pruned": EventSpec("info", "Older whole-WTF snapshots of the flavor were deleted to keep the newest N (keep_backups)."),
    "ace.journal_failed": EventSpec("error", "The run journal could not be written; nothing was changed."),
    "ace.journal_pruned": EventSpec("info", "Older journals (and the zips only they used) were deleted to keep the newest N (keep_journals)."),
    "ace.undo_started": EventSpec("info", "Undo last change started, from the newest journal."),
    "ace.file_restored": EventSpec("info", "Undo or recovery: a file was put back to its original bytes."),
    "ace.file_skipped": EventSpec("warning", "Undo or recovery: a file was left alone (it changed since the run, or is outside the WTF folder)."),
    "ace.undo_failed": EventSpec("error", "Undo or recovery: a file could not be put back (its zip is missing or does not match)."),
    "ace.undo_completed": EventSpec("info", "Undo last change finished (logged at warning if any file was skipped or failed)."),
    "ace.recovery_offered": EventSpec("warning", "A marker from an Apply that did not finish was found by a scan (on opening or a rescan), or Apply was pressed while it is there."),
    "ace.recovery_done": EventSpec("info", "The user chose what to do about an unfinished Apply (put back or leave)."),
}

register_events(TOOL_NAME, EVENTS)
