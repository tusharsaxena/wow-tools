"""The Macro Editor's own settings: the [macro_editor] section of config/macro-editor.cfg."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wowtools.core.config import Config
from wowtools.core.journal import tool_root
from wowtools.tools.macro_editor.events import TOOL_NAME

SECTION = "macro_editor"


@dataclass
class MacroSettings:
    # None: <WoW folder>/wow-tools. The tool's files go to <backup_dir>/macro-editor.
    backup_dir: Path | None = None
    last_flavor_choice: str | None = None  # "" = All flavors, else a flavor folder; None = never chosen
    # Snapshots and journals to keep are global: Config.keep_backups / keep_journals ([general]).


def load_settings(cfg: Config) -> MacroSettings:
    choice = cfg.get(SECTION, "last_flavor_choice")
    return MacroSettings(cfg.get_path(SECTION, "backup_dir"), None if choice is None else choice.strip())


def save_settings(cfg: Config, settings: MacroSettings, *, source: str = "settings") -> None:
    cfg.set_path(SECTION, "backup_dir", settings.backup_dir, source=source)
    if settings.last_flavor_choice is not None:
        cfg.set(SECTION, "last_flavor_choice", settings.last_flavor_choice, source=source)
    cfg.save()


def resolve_root(settings: MacroSettings, wow_path: Path | None) -> Path | None:
    """Where snapshots/, edited/ and the crash marker live."""
    return tool_root(settings.backup_dir, wow_path, TOOL_NAME)
