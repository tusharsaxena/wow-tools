"""The Config Editor's own settings: the [config_editor] section of config/config-editor.cfg."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wowtools.core.config import Config
from wowtools.core.journal import tool_root
from wowtools.tools.config_editor.events import TOOL_NAME

SECTION = "config_editor"


@dataclass
class ConfigEditorSettings:
    # None: <WoW folder>/wow-tools. The tool's files go to <backup_dir>/config-editor.
    backup_dir: Path | None = None
    last_flavor_choice: str | None = None  # "" = All flavors, else a flavor folder; None = never chosen
    # Snapshots and journals to keep are global: Config.keep_backups / keep_journals ([general]).


def load_settings(cfg: Config) -> ConfigEditorSettings:
    choice = cfg.get(SECTION, "last_flavor_choice")
    return ConfigEditorSettings(cfg.get_path(SECTION, "backup_dir"), None if choice is None else choice.strip())


def save_settings(cfg: Config, settings: ConfigEditorSettings, *, source: str = "settings") -> None:
    cfg.set_path(SECTION, "backup_dir", settings.backup_dir, source=source)
    if settings.last_flavor_choice is not None:
        cfg.set(SECTION, "last_flavor_choice", settings.last_flavor_choice, source=source)
    cfg.save()


def resolve_root(settings: ConfigEditorSettings, wow_path: Path | None) -> Path | None:
    """Where snapshots/, edited/ and the crash marker live."""
    return tool_root(settings.backup_dir, wow_path, TOOL_NAME)
