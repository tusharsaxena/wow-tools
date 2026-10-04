"""Events emitted by the Screenshot Organizer. Levels are fixed here; see docs/events.md.

Event names are global across tools, so every name here starts with `shots.`."""
from __future__ import annotations

from wowtools.core.events import EventSpec, register_events

TOOL_NAME = "screenshot-organizer"

EVENTS: dict[str, EventSpec] = {
    "shots.scan_started": EventSpec("info", "A scan of the chosen flavors' Screenshots folders started."),
    "shots.scan_completed": EventSpec("info", "A scan finished: per flavor, files to file, possible duplicates, conflicts, copies already filed (copy mode) and unrecognised names."),
    "shots.scan_warning": EventSpec("warning", "A Screenshots or target folder could not be read during a scan."),
    "shots.organize_started": EventSpec("info", "A run (or dry run) started: mode, destination and file count."),
    "shots.moved": EventSpec("info", "A screenshot was moved into its date folder."),
    "shots.copied": EventSpec("info", "A screenshot was copied into its date folder (copy mode)."),
    "shots.would_file": EventSpec("info", "Dry run: a screenshot that would have been filed."),
    "shots.duplicate_removed": EventSpec("info", "The source was identical to the file already at the target and was removed."),
    "shots.already_filed": EventSpec("info", "Copy mode: an identical file was already at the target."),
    "shots.conflict": EventSpec("warning", "A different file with the same name is already at the target; both were left alone."),
    "shots.skipped": EventSpec("warning", "A screenshot was skipped because it vanished or changed after the scan."),
    "shots.source_left": EventSpec("warning", "A screenshot was copied across drives but the source could not be deleted."),
    "shots.refused": EventSpec("error", "The path guard refused a screenshot (its source or target is not where it should be)."),
    "shots.failed": EventSpec("error", "A screenshot could not be filed."),
    "shots.organize_completed": EventSpec("info", "A run finished, with totals (logged at warning if any file failed)."),
    "shots.organize_stopped": EventSpec("error", "A run stopped unexpectedly; the journal holds what was done so far."),
    "shots.journal_pruned": EventSpec("info", "Older run journals were deleted to keep the newest N (keep_journals)."),
    "shots.undo_started": EventSpec("info", "Undo of a run journal started."),
    "shots.undo_restored": EventSpec("info", "Undo put one screenshot back (or removed one copy)."),
    "shots.undo_skipped": EventSpec("warning", "Undo left an entry alone because it could not be reversed safely."),
    "shots.undo_failed": EventSpec("error", "Undo hit an error on one entry."),
    "shots.undo_completed": EventSpec("info", "Undo finished, with totals."),
}

register_events(TOOL_NAME, EVENTS)
