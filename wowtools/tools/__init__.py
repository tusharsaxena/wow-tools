"""Tools that ship with the suite. Add new tools to TOOLS (see docs/adding-a-tool.md)."""
from __future__ import annotations

import importlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Tool:
    name: str         # also the tool's config file (config/<name>.cfg) and log folder (logs/<name>/)
    title: str
    description: str
    module: str       # module that defines FLOW, the tool's ToolFlow subclass
    section: str      # the tool's section in its config file

    def flow(self) -> type:
        """The tool's ToolFlow subclass, imported on demand."""
        return importlib.import_module(self.module).FLOW


TOOLS: dict[str, Tool] = {tool.name: tool for tool in (
    Tool("wtf-cleaner", "WTF Cleaner",
         "Find and remove stale addon SavedVariables, with zip backups.",
         "wowtools.tools.wtf_cleaner.app", "wtf_cleaner"),
    Tool("screenshots", "Screenshot Organizer",
         "File screenshots into year/month/day folders, per flavor.",
         "wowtools.tools.screenshots.app", "screenshots"),
)}
