"""Events emitted by the Config Copier (config tools spec CC1-CC8). Levels are fixed here; see docs/events.md."""
from __future__ import annotations

from wowtools.core.events import EventSpec, register_events
from wowtools.core.sv_events import SvTool, client_events

TOOL_NAME = "config-copier"
SV_TOOL = SvTool(TOOL_NAME, "copier")  # on the client-file write pipeline (core/client_apply.py)

EVENTS: dict[str, EventSpec] = {
    "copier.started": EventSpec("info", "The Config Copier opened its review on a source character (flavors, "
                                        "source)."),
    "copier.planned": EventSpec("info", "A copy was planned from a source character: source, targets, files and "
                                        "how many (target, file) pairs are new, replaced, unchanged, have no source "
                                        "file or could not be read (counts)."),
    "copier.file_unreadable": EventSpec("warning", "A source or target client file could not be read while planning "
                                                   "a copy, so its pairs are shown as unreadable and never copied "
                                                   "(path, reason)."),
    **client_events(SV_TOOL.prefix),
}

register_events(TOOL_NAME, EVENTS)
