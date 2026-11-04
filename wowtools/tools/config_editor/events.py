"""Events emitted by the Config Editor (config tools spec CE1-CE8). Levels are fixed here; see docs/events.md."""
from __future__ import annotations

from wowtools.core.events import EventSpec, register_events
from wowtools.core.sv_events import SvTool, client_events

TOOL_NAME = "config-editor"
SV_TOOL = SvTool(TOOL_NAME, "cvar")  # on the client-file write pipeline (core/client_apply.py); `config.` is core's

EVENTS: dict[str, EventSpec] = {
    "cvar.started": EventSpec("info", "The Config Editor opened its browse screen (flavors, label)."),
    "cvar.scanned": EventSpec("info", "The CVar files of a flavor were read (flavor, files, files that exist, "
                                      "read-only files)."),
    "cvar.file_unreadable": EventSpec("warning", "A Config.wtf or config-cache.wtf could not be read, so it is shown "
                                                 "read-only and never written (path, reason)."),
    **client_events(SV_TOOL.prefix),
}

register_events(TOOL_NAME, EVENTS)
