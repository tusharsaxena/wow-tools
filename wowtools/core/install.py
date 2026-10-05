"""Model of a World of Warcraft install: flavors, accounts, realms and characters."""
from __future__ import annotations

import os
import re
import string
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from wowtools.core.paths import is_wsl

ErrorHandler = Callable[[Path, OSError], None]
ACCOUNT_WIDE = "account-wide"

FLAVOR_NAMES = {
    "_retail_": "Retail",
    "_classic_": "Classic",
    "_classic_era_": "Classic Era",
    "_anniversary_": "Anniversary",
    "_ptr_": "Retail PTR",
    "_xptr_": "Retail Experimental PTR",
    "_beta_": "Retail Beta",
    "_classic_ptr_": "Classic PTR",
    "_classic_beta_": "Classic Beta",
    "_classic_era_ptr_": "Classic Era PTR",
}
_FLAVOR_DIR = re.compile(r"^_[a-z0-9_]+_$")

COMMON_SUBPATHS = (
    "Program Files (x86)/World of Warcraft",
    "Program Files/World of Warcraft",
    "Program Files (x86)/Blizzard/World of Warcraft",
    "World of Warcraft",
    "Games/World of Warcraft",
    "Games/Blizzard/World of Warcraft",
    "Blizzard/World of Warcraft",
)


def _subdirs(path: Path, on_error: ErrorHandler | None = None) -> list[Path]:
    if not path.is_dir():
        return []
    try:
        children = [p for p in path.iterdir() if p.is_dir()]
    except OSError as exc:
        if on_error is not None:
            on_error(path, exc)
        return []
    return sorted(children, key=lambda p: p.name.casefold())


@dataclass(frozen=True)
class Character:
    account: str
    realm: str
    name: str
    path: Path

    @property
    def saved_variables_dir(self) -> Path:
        return self.path / "SavedVariables"

    @property
    def addons_txt(self) -> Path:
        return self.path / "AddOns.txt"

    @property
    def label(self) -> str:
        return f"{self.realm}/{self.name}"


@dataclass(frozen=True)
class Account:
    name: str
    path: Path

    @property
    def saved_variables_dir(self) -> Path:
        return self.path / "SavedVariables"

    def characters(self, on_error: ErrorHandler | None = None) -> list[Character]:
        result = []
        for realm in _subdirs(self.path, on_error):
            if realm.name == "SavedVariables":
                continue
            for char in _subdirs(realm, on_error):
                result.append(Character(self.name, realm.name, char.name, char))
        return result


@dataclass(frozen=True)
class Flavor:
    folder: str
    path: Path

    @property
    def display_name(self) -> str:
        return FLAVOR_NAMES.get(self.folder) or self.folder.strip("_").replace("_", " ").title()

    @property
    def short_name(self) -> str:
        return self.folder.strip("_")

    @property
    def addons_dir(self) -> Path:
        return self.path / "Interface" / "AddOns"

    @property
    def wtf_dir(self) -> Path:
        return self.path / "WTF"

    @property
    def account_dir(self) -> Path:
        return self.wtf_dir / "Account"

    def accounts(self, on_error: ErrorHandler | None = None) -> list[Account]:
        return [Account(p.name, p) for p in _subdirs(self.account_dir, on_error)]


class WowInstall:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def flavors(self) -> list[Flavor]:
        """Every _name_ folder in the WoW folder (_retail_, _classic_beta_, ...), whatever it holds yet."""
        return [Flavor(p.name, p) for p in _subdirs(self.root) if _FLAVOR_DIR.match(p.name)]

    def is_valid(self) -> bool:
        return self.root.is_dir() and bool(self.flavors())

    def flavor(self, name: str) -> Flavor | None:
        wanted = name.strip().strip("_").casefold()
        for flavor in self.flavors():
            if flavor.short_name.casefold() == wanted:
                return flavor
        return None


def drive_roots() -> list[Path]:
    if os.name == "nt":
        return [Path(f"{d}:/") for d in string.ascii_uppercase if Path(f"{d}:/").exists()]
    if is_wsl():
        return [Path(f"/mnt/{d}") for d in string.ascii_lowercase if Path(f"/mnt/{d}").is_dir()]
    home = Path.home()
    return [home / ".wine" / "drive_c", home / "Games", home]


def detect_installs(roots: list[Path] | None = None) -> list[Path]:
    """Look for WoW in the usual places on every drive. Returns native paths."""
    found: list[Path] = []
    for root in drive_roots() if roots is None else roots:
        for sub in COMMON_SUBPATHS:
            candidate = root / sub
            if candidate not in found and WowInstall(candidate).is_valid():
                found.append(candidate)
    return found


# Folders inside a game version folder that no tool may write its own output into: the cleaner backs up the whole
# WTF folder (backups inside it would grow every snapshot), WoW owns Interface, and Screenshots is the organizer's
# source.
PROTECTED_FLAVOR_DIRS = ("WTF", "Interface", "Screenshots")


def _key(path: Path) -> str:
    """A comparable form of a path: absolute, symlinks resolved, case folded (Windows folders ignore case)."""
    return str(path.resolve()).casefold()


def _is_within(key: str, parent: str) -> bool:
    sep = "\\" if "\\" in parent else "/"
    return key == parent or key.startswith(parent.rstrip("/\\") + sep)


def validate_output_dir(path: Path | None, install: WowInstall, *, what: str = "folder",
                        example: str = "D:\\WoW backups") -> str | None:
    """Why a folder a tool writes into (a backup folder, a screenshot archive) is not allowed, or None if it is
    fine. None itself is fine: it means the tool's default. Refused: a relative path (it would depend on the folder
    the app was started from), the WoW folder itself, and anything inside a game version's WTF, Interface or
    Screenshots folder. Checked when the setting is saved and again before the folder is used."""
    if path is None:
        return None
    if not path.is_absolute():  # e.g. "backups", "~/x", "D:x", or a UNC path under WSL
        return f"Use a full path for the {what}, e.g. {example}."
    key = _key(path)
    if key == _key(install.root):
        return f"The {what} cannot be the WoW folder itself."
    for flavor in install.flavors():
        for sub in PROTECTED_FLAVOR_DIRS:
            if _is_within(key, _key(flavor.path / sub)):
                return f"The {what} cannot be inside {flavor.folder}\\{sub}."
    return None
