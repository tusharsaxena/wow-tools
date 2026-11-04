"""The Macro Editor's macro set: one macros-cache.txt, the account's or a character's (config tools spec ME2, ME3,
ME14). UI-free."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from wowtools.core.install import Account, Character, Flavor
from wowtools.core.kb import limits_known, macro_limits
from wowtools.core.macrofile import MacroFile

__all__ = ["MACRO_FILE", "MacroSet"]

MACRO_FILE = "macros-cache.txt"  # the only file the tool reads or writes (X4)


@dataclass(frozen=True)
class MacroSet:
    """One macros-cache.txt as the scan read it. `character` None is the account's macros. `data` is the file's
    bytes (b"" when there is no file) and `sha256` their SHA-256, None when there is no file (a run creates it). A
    set whose file is in a layout the reader does not know, or could not be read, is read-only: `parsed.problem`
    says why (Review Focus 1)."""
    flavor: Flavor
    account: Account
    character: Character | None
    path: Path
    parsed: MacroFile
    data: bytes
    sha256: str | None

    @property
    def scope(self) -> Literal["account", "character"]:
        return "account" if self.character is None else "character"

    @property
    def limit(self) -> int:
        """Macro slots in this set for its flavor (ME3, core.kb.macro_limits)."""
        account, character = macro_limits(self.flavor.folder)
        return account if self.character is None else character

    @property
    def limit_known(self) -> bool:
        """False when the KB has no sourced limits for this flavor and `limit` is Retail's (ME3): the tree marks the
        slots unconfirmed."""
        return limits_known(self.flavor.folder)

    @property
    def read_only(self) -> bool:
        return not self.parsed.known_layout

    @property
    def label(self) -> str:
        """`MAIN/Account macros` or `MAIN/Realm1/Aellâ`."""
        if self.character is None:
            return f"{self.account.name}/Account macros"
        return f"{self.account.name}/{self.character.label}"
