"""The Config Editor's files and CVar rows (config tools spec CE3, CE4, X8). UI-free.

A ConfigTarget is one CVar file as the scan read it: WTF/Config.wtf (machine), an account's config-cache.wtf or a
real character's (X3). A Row is one CVar of a target as the list shows it: its value there (as staged), the KB's
default, whether it differs from the default and whether the file's level matches the KB scope (CE5 warns).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from wowtools.core.client_apply import CONFIG_WTF
from wowtools.core.cvarfile import CvarFile
from wowtools.core.install import Account, Character, Flavor
from wowtools.core.kb import CATEGORY_GROUPS, CvarInfo, cvar_category

__all__ = ["CATEGORIES", "CONFIG_CACHE", "CONFIG_WTF", "FILE_NAMES", "ConfigTarget", "Level", "Row", "category_of"]

CONFIG_CACHE = "config-cache.wtf"
FILE_NAMES = frozenset({CONFIG_WTF, CONFIG_CACHE})  # the only files the tool reads or writes (X4)
CATEGORIES = CATEGORY_GROUPS  # the category filter's groups (X8), in order
Level = Literal["machine", "account", "character"]


@dataclass(frozen=True)
class ConfigTarget:
    """One CVar file. `data` is its bytes and `sha256` their SHA-256; both None when there is no file (a run that
    sets a CVar there creates it) or it could not be read (`problem` says why, and the target is read-only).
    `parsed` is None exactly when `data` is."""
    flavor: Flavor
    level: Level
    account: Account | None
    character: Character | None
    path: Path
    data: bytes | None
    parsed: CvarFile | None
    sha256: str | None
    problem: str | None = None

    @property
    def exists(self) -> bool:
        return self.data is not None

    @property
    def read_only(self) -> bool:
        return self.problem is not None

    @property
    def file_name(self) -> str:
        return self.path.name

    @property
    def label(self) -> str:
        """`Config.wtf`, `MAIN` (the account's config) or `MAIN/Realm1/Aellâ`."""
        if self.level == "machine" or self.account is None:
            return CONFIG_WTF
        if self.character is None:
            return self.account.name
        return f"{self.account.name}/{self.character.label}"


def category_of(info: CvarInfo | None, name: str) -> str:
    """The X8 group of a CVar: the KB's (its curated group, else the rules of core.kb.category_group), or, for a CVar
    the flavor's data doesn't know, the curated group of the name (the shipped list, CF4) or the name rules."""
    if info is not None and info.category in CATEGORIES:
        return info.category
    return cvar_category(name, "")


@dataclass(frozen=True)
class Row:
    """One CVar of a target. `value` None: not set in the file (as staged), so the client uses its default.
    `changed` None: set, but the KB has no default to compare with. `staged`: a pending change touches it."""
    name: str
    value: str | None
    default: str | None
    changed: bool | None
    info: CvarInfo | None
    scope_mismatch: bool
    staged: bool = False

    @property
    def category(self) -> str:
        return category_of(self.info, self.name)

    @property
    def known(self) -> bool:
        return self.info is not None
