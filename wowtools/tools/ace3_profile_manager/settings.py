"""The Ace3 Profile Manager's own settings: the [ace3_profile_manager] section of config/ace3-profile-manager.cfg
(spec §11)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.blacklist import Pair, format_blacklist, parse_blacklist
from wowtools.core.config import Config
from wowtools.core.journal import tool_root
from wowtools.core.migrate import merge_folder_logged
from wowtools.tools.ace3_profile_manager.events import TOOL_NAME

SECTION = "ace3_profile_manager"
ROOT_NAME = TOOL_NAME
OLD_ROOT_NAME = "ace-profiles"  # the tool's name before the rename (RENAMED_TOOLS)


@dataclass
class ProfileSettings:
    # None: <WoW folder>/wow-tools. The tool's files go to <backup_dir>/ace3-profile-manager.
    backup_dir: Path | None = None
    # (flavor folder, addon) pairs; the addon is the SavedVariables file name without .lua; flavor "*" = every flavor
    blacklist: list[Pair] = field(default_factory=list)
    last_flavor_choice: str | None = None  # "" = All flavors, else a flavor folder; None = never chosen
    last_account: str | None = None  # None (stored as empty) = all accounts
    # Snapshots and journals to keep are global: Config.keep_backups / keep_journals ([general]).


def load_settings(cfg: Config) -> ProfileSettings:
    choice = cfg.get(SECTION, "last_flavor_choice")
    return ProfileSettings(cfg.get_path(SECTION, "backup_dir"),
                           parse_blacklist(cfg.get(SECTION, "blacklist") or ""),
                           None if choice is None else choice.strip(),
                           (cfg.get(SECTION, "last_account") or "").strip() or None)


def save_settings(cfg: Config, settings: ProfileSettings, *, source: str = "settings") -> None:
    cfg.set_path(SECTION, "backup_dir", settings.backup_dir, source=source)
    cfg.remove_retired(SECTION, source=source)
    cfg.set(SECTION, "blacklist", format_blacklist(settings.blacklist), source=source)
    cfg.set(SECTION, "last_account", settings.last_account or "", source=source)
    if settings.last_flavor_choice is not None:
        cfg.set(SECTION, "last_flavor_choice", settings.last_flavor_choice, source=source)
    cfg.save()


def resolve_root(settings: ProfileSettings, wow_path: Path | None) -> Path | None:
    """Where snapshots/, edited/ and the crash marker live."""
    return tool_root(settings.backup_dir, wow_path, ROOT_NAME)


def migrate_backup_root(settings: ProfileSettings) -> None:
    """Move <backup_dir>/ace-profiles, the tool's folder under its old name, to <backup_dir>/ace3-profile-manager.
    core/migrate.py moves <WoW>/wow-tools/<old>/ at start-up, but not a folder inside one the user chose. Never
    raises; nothing is overwritten."""
    if settings.backup_dir is not None:
        merge_folder_logged(settings.backup_dir / OLD_ROOT_NAME, settings.backup_dir / ROOT_NAME)


