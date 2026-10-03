"""Tools that ship with the suite. Add new tools to TOOLS (see docs/adding-a-tool.md)."""
from __future__ import annotations

import importlib
from dataclasses import dataclass

from wowtools.core.migrate import ToolRename


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
    Tool("screenshot-organizer", "Screenshot Organizer",
         "File screenshots into year/month/day folders, per flavor.",
         "wowtools.tools.screenshot_organizer.app", "screenshot_organizer"),
)}

# Tools that changed name. At start-up each tool's old config file, logs/<old>/ folder and
# <WoW folder>/wow-tools/<old>/ folder move to the new name (core/migrate.py). One line per rename.
RENAMED_TOOLS: tuple[ToolRename, ...] = (
    ToolRename("screenshots", "screenshot-organizer", "screenshots", "screenshot_organizer"),
)
