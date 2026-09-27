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
    "backup.created": EventSpec("info", "A backup zip was written and verified."),
    "backup.would_create": EventSpec("info", "Dry run: the backup zip that would have been written."),
    "backup.failed": EventSpec("error", "The backup failed; nothing was deleted."),
    "sv.deleted": EventSpec("info", "A SavedVariables file was deleted."),
    "sv.would_delete": EventSpec("info", "Dry run: a SavedVariables file that would have been deleted."),
    "sv.skipped": EventSpec("warning", "A selected file was skipped because it vanished or changed after the scan."),
    "sv.failed": EventSpec("error", "A SavedVariables file could not be deleted."),
    "clean.completed": EventSpec("info", "A clean finished (logged at warning if any file failed)."),
}

register_events(TOOL_NAME, EVENTS)
