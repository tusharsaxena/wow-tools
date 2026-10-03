"""Events emitted by the WTF Cleaner. Levels are fixed here; see docs/events.md."""
from __future__ import annotations

from wowtools.core.events import EventSpec, register_events

TOOL_NAME = "wtf-cleaner"

EVENTS: dict[str, EventSpec] = {
    "scan.started": EventSpec("info", "A scan of one flavor started."),
    "scan.addons": EventSpec("debug", "Installed and enabled addon lists found by the scan."),
    "scan.completed": EventSpec("info", "A scan finished, with counts."),
    "scan.warning": EventSpec("warning", "Something was skipped during a scan (unreadable folder, bad AddOns.txt line)."),
    "proposal.built": EventSpec("info", "The cleanup proposal was built from scan results and criteria."),
    "proposal.item": EventSpec("debug", "One addon group in the proposal."),
    "clean.started": EventSpec("info", "A clean (or dry run) started."),
    "backup.created": EventSpec("info", "The cleaned-files zip was written and verified (a dry run writes it too)."),
    "backup.failed": EventSpec("error", "The cleaned-files zip failed; nothing was deleted."),
    "sv.deleted": EventSpec("info", "A SavedVariables file was deleted."),
    "sv.would_delete": EventSpec("info", "Dry run: a SavedVariables file that would have been deleted."),
    "sv.skipped": EventSpec("warning", "A selected file was skipped because it vanished or changed after the scan."),
    "sv.failed": EventSpec("error", "A SavedVariables file could not be deleted."),
    "clean.completed": EventSpec("info", "A clean finished (logged at warning if any file failed)."),
    "clean.flavors_stopped": EventSpec("warning", "A clean of several flavors stopped at one flavor; the flavors after it were not started."),
    "snapshot.created": EventSpec("info", "The backup of the whole WTF folder (backup/backup-<flavor>-<stamp>.zip) was written and verified."),
    "snapshot.pruned": EventSpec("info", "Older WTF backups of the flavor were deleted to keep its newest N (keep_backups)."),
    "locker.running_warning": EventSpec("warning", "A program known to lock WTF files (e.g. the Raider.IO client) appears to be running."),
    "clean.locked": EventSpec("error", "A real clean stopped before the WTF backup: selected files are locked by another program."),
    "clean.validated": EventSpec("info", "After a clean, the WTF folder matched the WTF backup and the cleaned-files zip."),
    "clean.check_failed": EventSpec("warning", "The post-clean check found problems; see the WTF backup it names."),
    "snapshot.failed": EventSpec("error", "The WTF backup failed; nothing was deleted."),
    "restore.completed": EventSpec("warning", "A clean stopped unexpectedly; the files it had deleted were restored."),
    "restore.failed": EventSpec("error", "Restoring from the WTF backup failed; the marker was kept."),
    "clean.journal_failed": EventSpec("error", "The run journal could not be written; the clean stopped before deleting anything."),
    "clean.journal_pruned": EventSpec("info", "Older clean journals were deleted to keep the newest N (keep_journals)."),
    "clean.undo_started": EventSpec("info", "Undo last clean started, from the newest clean journal."),
    "clean.undo_restored": EventSpec("info", "Undo: a deleted file was put back from the cleaned-files zip or the WTF backup."),
    "clean.undo_skipped": EventSpec("warning", "Undo: a file was left alone (one is back at its path, or its journal entry is outside the WTF folder)."),
    "clean.undo_failed": EventSpec("error", "Undo: a file could not be put back (no zip holds it, or the size did not match)."),
    "clean.undo_completed": EventSpec("info", "Undo last clean finished (logged at warning if any file was skipped or failed)."),
    "recovery.incomplete_clean": EventSpec("warning", "A marker from an unfinished clean was found at startup."),
}

register_events(TOOL_NAME, EVENTS)
