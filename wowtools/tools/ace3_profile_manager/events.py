"""Events emitted by the Ace3 Profile Manager. Levels are fixed here; see docs/events.md."""
from __future__ import annotations

from wowtools.core.events import EventSpec, register_events
from wowtools.core.sv_events import SvTool, sv_events

TOOL_NAME = "ace3-profile-manager"
SV_TOOL = SvTool(TOOL_NAME, "ace")  # on the shared SavedVariables write pipeline (core/sv_apply.py)

EVENTS: dict[str, EventSpec] = {
    "ace.disclaimer_accepted": EventSpec("info", "The USE AT YOUR OWN RISK warning was accepted (I understand): "
                                                 "it is not shown again this session."),
    "ace.disclaimer_declined": EventSpec("info", "The USE AT YOUR OWN RISK warning was declined (Back): "
                                                 "nothing was scanned."),
    "ace.risk_warning_changed": EventSpec("info", "The USE AT YOUR OWN RISK warning was turned off (its Don't show "
                                                   "this warning again box) or back on in the settings (shown, "
                                                   "source)."),
    "ace.scan_started": EventSpec("info", "A scan of one flavor's SavedVariables for AceDB databases started."),
    "ace.scan_completed": EventSpec("info", "A scan finished, with counts (files, databases, profiles, characters, leftover characters, seconds)."),
    "ace.file_unreadable": EventSpec("warning", "A SavedVariables file or folder could not be read; it is left out."),
    "ace.parse_failed": EventSpec("warning", "A SavedVariables file is not readable Lua; it is shown as a warning and never changed."),
    "ace.lookalike": EventSpec("debug", "A table looks like an AceDB database but is not one; it is left alone."),
    "ace.staged": EventSpec("debug", "A pending change was made on the review screen (operation and counts; not written until Apply)."),
    "ace.blacklist_changed": EventSpec("info", "A (flavor, addon) pair was added to or removed from the blacklist (flavor, addon, blacklisted), or the whole list was saved from the blacklist screen (pairs)."),
    "ace.unlocked": EventSpec("info", "A blacklisted addon of one flavor was unlocked for this session, or locked again (unlocked=false)."),
    **sv_events(SV_TOOL.prefix),
}

register_events(TOOL_NAME, EVENTS)
