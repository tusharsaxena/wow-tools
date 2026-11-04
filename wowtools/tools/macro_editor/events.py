"""Events emitted by the Macro Editor (config tools spec ME1-ME14). Levels are fixed here; see docs/events.md."""
from __future__ import annotations

from wowtools.core.events import EventSpec, register_events
from wowtools.core.sv_events import SvTool, client_events

TOOL_NAME = "macro-editor"
SV_TOOL = SvTool(TOOL_NAME, "macro")  # on the client-file write pipeline (core/client_apply.py)

EVENTS: dict[str, EventSpec] = {
    "macro.started": EventSpec("info", "The Macro Editor opened its browse screen (flavors, label)."),
    "macro.scanned": EventSpec("info", "The macro files of a flavor were read (flavor, sets, macros, read-only "
                                       "sets)."),
    "macro.file_unreadable": EventSpec("warning", "A macros-cache.txt could not be read, so its set is shown "
                                                  "read-only and never written (path, reason)."),
    **client_events(SV_TOOL.prefix),
}

register_events(TOOL_NAME, EVENTS)
