"""Events emitted by the Saved Variables Browser (spec §6). Levels are fixed here; see docs/events.md."""
from __future__ import annotations

from wowtools.core.events import EventSpec, register_events
from wowtools.core.sv_events import SvTool, sv_events

TOOL_NAME = "sv-browser"
SV_TOOL = SvTool(TOOL_NAME, "svb")  # on the shared SavedVariables write pipeline (core/sv_apply.py)

EVENTS: dict[str, EventSpec] = {
    "svb.started": EventSpec("info", "The Saved Variables Browser opened on a flavor (or All flavors)."),
    "svb.disclaimer_accepted": EventSpec("info", "The USE AT YOUR OWN RISK warning was accepted (I understand)."),
    "svb.disclaimer_declined": EventSpec("info", "The USE AT YOUR OWN RISK warning was declined (Back): nothing was scanned."),
    "svb.scan_completed": EventSpec("info", "The SavedVariables files were listed, with counts (flavors, accounts, files, bytes, seconds)."),
    "svb.file_unreadable": EventSpec("warning", "A SavedVariables file or folder could not be read or is not readable Lua; it is shown in red and never changed or searched."),
    "svb.search_started": EventSpec("info", "A search started (key and value text, modes, scope, files in scope)."),
    "svb.search_completed": EventSpec("info", "A search finished, with counts (files searched, hits, hits dropped over the cap, seconds)."),
    "svb.staged": EventSpec("debug", "A pending edit was made on the review (edit value, rename key or delete key; not written until Apply)."),
    "svb.bulk_staged": EventSpec("info", "A bulk Edit value or Rename key on the search results was staged (edits staged, results already holding it, results left out and why)."),
    "svb.unstaged": EventSpec("debug", "A pending edit was dropped on the review (Backspace on its node)."),
    **sv_events(SV_TOOL.prefix),
}

register_events(TOOL_NAME, EVENTS)
