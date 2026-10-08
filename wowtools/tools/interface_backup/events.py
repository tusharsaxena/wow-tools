"""Events emitted by Interface Backup. Levels are fixed here; see docs/events.md.

Event names are global across tools, so every name here starts with `ibackup.`."""
from __future__ import annotations

from wowtools.core.events import EventSpec, register_events

TOOL_NAME = "interface-backup"

EVENTS: dict[str, EventSpec] = {
    "ibackup.scan_started": EventSpec("info", "A scan of the chosen flavors' Interface and WTF folders started."),
    "ibackup.scan_completed": EventSpec("info", "A flavor was scanned: files, bytes (when known) and links per part."),
    "ibackup.scan_warning": EventSpec("warning", "A folder could not be read during a scan, or a part is itself a link."),
    "ibackup.leftover_found": EventSpec("warning", "A .restoring or .replaced folder from an interrupted restore was found."),
    "ibackup.backup_started": EventSpec("info", "A backup run started: flavors and destination."),
    "ibackup.backup_created": EventSpec("info", "A backup zip was written and verified: path, files, sizes."),
    "ibackup.backup_skipped": EventSpec("warning", "A flavor was skipped: it has no real Interface or WTF folder (missing, or links)."),
    "ibackup.backup_failed": EventSpec("error", "A flavor's backup failed; no zip was left behind."),
    "ibackup.links_skipped": EventSpec("info", "Links (symlinks, junctions) that were not followed: count and up to 20 paths."),
    "ibackup.zips_moved": EventSpec("info", "Zips an older version left in interface-backup/ were moved into its "
                                    "backup/ folder: count, and names left in place (taken or failed: warning, "
                                    "logged the first time a name is left only)."),
    "ibackup.pruned": EventSpec("info", "Older backups of a flavor were deleted to keep the newest N (keep_backups)."),
    "ibackup.restore_started": EventSpec("info", "A restore started: backup, flavor, parts and warning counts."),
    "ibackup.safety_created": EventSpec("info", "The pre-restore safety backup was written and verified."),
    "ibackup.part_restored": EventSpec("info", "A part (Interface or WTF) was replaced by the backup's copy."),
    "ibackup.part_rolled_back": EventSpec("warning", "A part could not be replaced: left as it was (kind rolled_back), or, at error, not fully put back (kind failed; reason says what is where)."),
    "ibackup.replaced_left": EventSpec("warning", "A part was restored but its old copy could not be fully deleted."),
    "ibackup.restore_completed": EventSpec("info", "A restore finished, with totals (logged at warning if a part failed)."),
    "ibackup.restore_failed": EventSpec("error", "A restore could not go ahead (backup did not verify, safety backup or journal failed); nothing was changed."),
    "ibackup.restore_stopped": EventSpec("error", "A restore stopped unexpectedly; the journal holds what was done so far."),
    "ibackup.journal_pruned": EventSpec("info", "Older restore journals and the safety backups only they named were deleted."),
    "ibackup.undo_started": EventSpec("info", "Undo of a restore journal started."),
    "ibackup.undo_completed": EventSpec("info", "Undo of a restore finished, with totals."),
    "ibackup.undo_failed": EventSpec("error", "Undo was refused or failed on a part."),
}

register_events(TOOL_NAME, EVENTS)
