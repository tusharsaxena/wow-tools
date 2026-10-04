"""The Ace3 Profile Manager's own settings: the [ace_profiles] section of config/ace-profiles.cfg (spec §11)."""
from __future__ import annotations

import re
from collections.abc import Iterable
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
WILDCARD = "*"  # the flavor of a bare (legacy) blacklist name: every flavor
Pair = tuple[str, str]  # (flavor folder, addon)


@dataclass
class ProfileSettings:
    backup_dir: Path | None = None  # None: <WoW folder>/wow-tools; the tool's files go to <backup_dir>/ace-profiles
    # (flavor folder, addon) pairs; the addon is the SavedVariables file name without .lua; flavor "*" = every flavor
    blacklist: list[Pair] = field(default_factory=list)
    last_flavor_choice: str | None = None  # "" = All flavors, else a flavor folder; None = never chosen
    last_account: str | None = None  # None (stored as empty) = all accounts
    # Snapshots and journals to keep are global: Config.keep_backups / keep_journals ([general]).


def _pair_order(pair: Pair) -> tuple[str, str]:
    return pair[1].casefold(), pair[0].casefold()


def unique_pairs(pairs: Iterable[Pair]) -> list[Pair]:
    """Duplicates (ignoring case) keep the first spelling; sorted by addon, then flavor, ignoring case."""
    seen: dict[tuple[str, str], Pair] = {}
    for flavor, addon in pairs:
        seen.setdefault((flavor.casefold(), addon.casefold()), (flavor, addon))
    return sorted(seen.values(), key=_pair_order)


def parse_blacklist(text: str) -> list[Pair]:
    """`flavor:addon` entries separated by commas or new lines (`_retail_:ElvUI, Questie`). A bare name (the first
    build's form) becomes ("*", name): every flavor. Blanks dropped, duplicates (ignoring case) keep the first
    spelling."""
    pairs: list[Pair] = []
    for part in _SPLIT.split(text or ""):
        flavor, sep, addon = part.partition(":")
        flavor, addon = (flavor.strip(), addon.strip()) if sep else (WILDCARD, flavor.strip())
        if addon and flavor:
            pairs.append((flavor, addon))
    return unique_pairs(pairs)


def format_blacklist(pairs: Iterable[Pair]) -> str:
    """`flavor:addon, ...`, sorted; a wildcard pair stays a bare name."""
    return ", ".join(addon if flavor == WILDCARD else f"{flavor}:{addon}" for flavor, addon in unique_pairs(pairs))


def is_blacklisted(pairs: Iterable[Pair], flavor: str, addon: str) -> bool:
    """(flavor folder, addon) is on the blacklist, ignoring case; "*" matches every flavor."""
    wanted_flavor, wanted_addon = flavor.casefold(), addon.casefold()
    return any(name.casefold() == wanted_addon and (where == WILDCARD or where.casefold() == wanted_flavor)
               for where, name in pairs)


def toggle_pair(pairs: Iterable[Pair], flavor: str, addon: str, folders: Iterable[str]) -> tuple[list[Pair], bool]:
    """Blacklist (flavor, addon), or take it off when it is on. Taking it off drops its pair and turns a wildcard
    for that addon into explicit pairs for the other flavor folders in `folders`, so they stay blacklisted.
    Returns the new list and whether the pair is now blacklisted."""
    pairs = list(pairs)
    if not is_blacklisted(pairs, flavor, addon):
        return unique_pairs([*pairs, (flavor, addon)]), True
    name, here = addon.casefold(), flavor.casefold()
    kept: list[Pair] = []
    for where, other in pairs:
        if other.casefold() != name:
            kept.append((where, other))
        elif where == WILDCARD:
            kept += [(folder, other) for folder in folders if folder.casefold() != here]
        elif where.casefold() != here:
            kept.append((where, other))
    return unique_pairs(kept), False


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
