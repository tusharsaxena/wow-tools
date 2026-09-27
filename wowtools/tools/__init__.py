"""Tools that ship with the suite. Add new tools to TOOLS (see docs/adding-a-tool.md)."""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    module: str

    def main(self) -> Callable[..., int]:
        """The tool's `main(argv, *, cfg=None, ...) -> int`, imported on demand."""
        return importlib.import_module(self.module).main


TOOLS: dict[str, Tool] = {tool.name: tool for tool in (
    Tool("wtf-cleaner", "WTF Cleaner",
         "Find and remove stale addon SavedVariables, with zip backups.",
         "wowtools.tools.wtf_cleaner.cli"),
)}
