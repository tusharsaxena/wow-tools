"""The Ace3 Profile Manager's own settings: the [ace_profiles] section of config/ace-profiles.cfg (spec §11)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core import journal as core_journal
from wowtools.core.config import Config
from wowtools.core.install import WowInstall, validate_output_dir
from wowtools.core.journal import TOOLS_SUBDIR
from wowtools.tools.ace_profiles.events import TOOL_NAME

SECTION = "ace_profiles"
ROOT_NAME = TOOL_NAME
_SPLIT = re.compile(r"[,\r\n]+")


@dataclass
class ProfileSettings:
    backup_dir: Path | None = None  # None: <WoW folder>/wow-tools; the tool's files go to <backup_dir>/ace-profiles
    blacklist: list[str] = field(default_factory=list)  # addon names (SavedVariables file name without .lua)
    last_flavor_choice: str | None = None  # "" = All flavors, else a flavor folder; None = never chosen
    last_account: str | None = None  # None (stored as empty) = all accounts
    # Snapshots and journals to keep are global: Config.keep_backups / keep_journals ([general]).


def parse_blacklist(text: str) -> list[str]:
    """Names separated by commas or new lines; blanks dropped; duplicates (ignoring case) keep the first spelling;
    sorted ignoring case."""
    seen: dict[str, str] = {}
    for part in _SPLIT.split(text or ""):
        name = part.strip()
        if name and name.casefold() not in seen:
            seen[name.casefold()] = name
    return sorted(seen.values(), key=str.casefold)


def format_blacklist(names: list[str]) -> str:
    return ", ".join(names)


def is_blacklisted(names: list[str], addon: str) -> bool:
    wanted = addon.casefold()
    return any(name.casefold() == wanted for name in names)


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
    if settings.backup_dir is not None:
        return settings.backup_dir / ROOT_NAME
    return wow_path / TOOLS_SUBDIR / ROOT_NAME if wow_path is not None else None


def resolve_journal_dir(wow_path: Path | None) -> Path | None:
    return core_journal.journal_dir(wow_path, TOOL_NAME)


def validate_backup_dir(path: Path | None, install: WowInstall) -> str | None:
    """None when fine (empty means the default); else the reason, as Interface Backup does."""
    if path is None:
        return None
    return validate_output_dir(path, install, what="backup folder", example="D:\\WoW backups")
