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

    def help(self) -> str:
        """The tool's help screen text (Markdown, spec D18): HELP in the help module of the tool's package."""
        return importlib.import_module(self.module.rpartition(".")[0] + ".help").HELP


TOOLS: dict[str, Tool] = {tool.name: tool for tool in (
    Tool("wtf-cleaner", "WTF Cleaner",
         "Find and remove stale addon SavedVariables, with zip backups.",
         "wowtools.tools.wtf_cleaner.app", "wtf_cleaner"),
    Tool("screenshot-organizer", "Screenshot Organizer",
         "File screenshots into year/month/day folders, per flavor.",
         "wowtools.tools.screenshot_organizer.app", "screenshot_organizer"),
    Tool("interface-backup", "Interface Backup",
         "Zip a flavor's Interface and WTF folders, and restore them.",
         "wowtools.tools.interface_backup.app", "interface_backup"),
    Tool("ace3-profile-manager", "Ace3 Profile Manager",
         "See and change which Ace3 profile each character uses.",
         "wowtools.tools.ace3_profile_manager.app", "ace3_profile_manager"),
    Tool("sv-browser", "Saved Variables Browser",
         "Browse and edit every SavedVariables file, with bulk find and replace.",
         "wowtools.tools.sv_browser.app", "sv_browser"),
)}

# Tools that changed name. At start-up each tool's old config file, logs/<old>/ folder and
# <WoW folder>/wow-tools/<old>/ folder move to the new name (core/migrate.py). One line per rename. Nothing else
# moves: a <TOOL_NAME> folder inside a folder the user chose (Interface Backup's <backup_dir>/interface-backup) stays
# under the old name, so renaming such a tool needs that handled too (see docs/adding-a-tool.md, step 6).
# Empty while no released tool has changed name.
RENAMED_TOOLS: tuple[ToolRename, ...] = ()
