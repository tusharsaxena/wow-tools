"""Interface Backup's own settings: the [interface_backup] section of config/interface-backup.cfg, plus where
backups and journals go."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wowtools.core.config import Config
from wowtools.core.install import WowInstall, validate_output_dir
from wowtools.core.journal import TOOLS_SUBDIR, journal_dir
from wowtools.tools.interface_backup.events import TOOL_NAME

SECTION = "interface_backup"
DEFAULT_KEEP_BACKUPS = 10
DEFAULT_KEEP_JOURNALS = 10


@dataclass
class BackupSettings:
    backup_dir: Path | None = None  # None (stored as empty) means <WoW folder>/wow-tools
    keep_backups: int = DEFAULT_KEEP_BACKUPS  # per flavor; 0 = never delete
    keep_journals: int = DEFAULT_KEEP_JOURNALS  # restore journals (each names its safety backup); at least 1
    last_flavor_choice: str = ""  # "" means all flavors, else a flavor folder such as _retail_


def load_settings(cfg: Config) -> BackupSettings:
    """Read the section. A negative or unreadable keep_backups, or a keep_journals below 1, falls back to 10."""
    keep = cfg.get_int(SECTION, "keep_backups", DEFAULT_KEEP_BACKUPS)
    journals = cfg.get_int(SECTION, "keep_journals", DEFAULT_KEEP_JOURNALS)
    return BackupSettings(cfg.get_path(SECTION, "backup_dir"),
                          keep if keep >= 0 else DEFAULT_KEEP_BACKUPS,
                          journals if journals >= 1 else DEFAULT_KEEP_JOURNALS,
                          (cfg.get(SECTION, "last_flavor_choice") or "").strip())


def save_settings(cfg: Config, settings: BackupSettings, *, source: str = "settings") -> None:
    cfg.set_path(SECTION, "backup_dir", settings.backup_dir, source=source)
    cfg.set(SECTION, "keep_backups", settings.keep_backups, source=source)
    cfg.set(SECTION, "keep_journals", settings.keep_journals, source=source)
    cfg.set(SECTION, "last_flavor_choice", settings.last_flavor_choice, source=source)
    cfg.save()


def resolve_backup_root(settings: BackupSettings, wow_path: Path | None) -> Path | None:
    """Where the zips go: <backup folder>/interface-backup, the backup folder defaulting to <WoW folder>/wow-tools.
    None when there is neither a backup folder nor a WoW folder."""
    if settings.backup_dir is not None:
        base = settings.backup_dir
    elif wow_path is not None:
        base = wow_path / TOOLS_SUBDIR
    else:
        return None
    return base / TOOL_NAME


def resolve_journal_dir(wow_path: Path | None) -> Path | None:
    """<WoW folder>/wow-tools/interface-backup/journal: always under the WoW folder, whatever the backup folder."""
    return journal_dir(wow_path, TOOL_NAME)


def validate_backup_dir(path: Path | None, install: WowInstall) -> str | None:
    """Why a backup folder is not allowed, or None if it is fine (None itself means the default)."""
    return validate_output_dir(path, install, what="backup folder", example="D:\\WoW backups")
