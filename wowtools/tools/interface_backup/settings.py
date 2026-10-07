"""Interface Backup's own settings: the [interface_backup] section of config/interface-backup.cfg, plus where
backups go (journals: journal.resolve_journal_dir)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wowtools.core.config import Config
from wowtools.core.journal import tool_root
from wowtools.tools.interface_backup.events import TOOL_NAME

SECTION = "interface_backup"


@dataclass
class BackupSettings:
    backup_dir: Path | None = None  # None (stored as empty) means <WoW folder>/wow-tools
    last_flavor_choice: str = ""  # "" means all flavors, else a flavor folder such as _retail_
    # Backups (0 = never delete) and restore journals to keep are global: Config.keep_backups / keep_journals.


def load_settings(cfg: Config) -> BackupSettings:
    return BackupSettings(cfg.get_path(SECTION, "backup_dir"), (cfg.get(SECTION, "last_flavor_choice") or "").strip())


def save_settings(cfg: Config, settings: BackupSettings, *, source: str = "settings") -> None:
    cfg.set_path(SECTION, "backup_dir", settings.backup_dir, source=source)
    cfg.remove_retired(SECTION, source=source)
    cfg.set(SECTION, "last_flavor_choice", settings.last_flavor_choice, source=source)
    cfg.save()


def resolve_backup_root(settings: BackupSettings, wow_path: Path | None) -> Path | None:
    """Where the zips go: <backup folder>/interface-backup, the backup folder defaulting to <WoW folder>/wow-tools.
    None when there is neither a backup folder nor a WoW folder."""
    return tool_root(settings.backup_dir, wow_path, TOOL_NAME)


