"""A synthetic World of Warcraft install for tests. Never touches a real install.

Layout built by build_wow_tree(root):

_retail_/Interface/AddOns: Auctionator, Details (Details_Mainline.toc only), DisabledAddon,
                           OldAddon, NoTocFolder (no .toc -> not an addon)
_retail_/WTF/Account/ACCT1/SavedVariables:
    Auctionator.lua, Auctionator.lua.bak, Auctionator.lua.pre-schema8-20260926-103400 (stray)
    Details.lua, "Details.lua - Copy.bak" (stray)
    Uninstalled.lua, Uninstalled.lua.bak        (addon not installed)
    DisabledAddon.lua                           (installed, disabled everywhere)
    OldAddon.lua, OldAddon.lua.bak              (200 days old)
    Blizzard_Foo.lua (protected), notes.txt (not an SV file)
_retail_/WTF/Account/ACCT1/config-cache.wtf
_retail_/WTF/Account/ACCT1/Realm1/CharA: AddOns.txt (Auctionator, Details, OldAddon enabled;
                                         DisabledAddon disabled), SV: Auctionator.lua, Uninstalled.lua
_retail_/WTF/Account/ACCT2/SavedVariables/Details.lua
_retail_/WTF/Account/ACCT2/Realm2/Chârb: AddOns.txt (Details/DisabledAddon/OldAddon disabled,
                                         one garbage line), SV: Details.lua
_classic_era_: Questie installed; ACCT1 account SV Questie.lua; Realm1/NoTxt (no AddOns.txt)
_anniversary_: WTF only, no Interface/AddOns (scanning it must abort)
_notaflavor: not a flavor folder
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from wowtools.core.config import Config

NOW = time.time()
DAY = 86400.0
FRESH = NOW - 1 * DAY
OLD = NOW - 200 * DAY


def _write(path: Path, text: str = "-- saved variables\n", mtime: float = FRESH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _addon(flavor: Path, name: str, toc: str | None = None) -> None:
    _write(flavor / "Interface" / "AddOns" / name / (toc or f"{name}.toc"), "## Interface: 110200\n")


def build_wow_tree(root: Path) -> Path:
    retail = root / "_retail_"
    for name in ("Auctionator", "DisabledAddon", "OldAddon"):
        _addon(retail, name)
    _addon(retail, "Details", "Details_Mainline.toc")
    _write(retail / "Interface" / "AddOns" / "NoTocFolder" / "readme.txt")

    acct1 = retail / "WTF" / "Account" / "ACCT1"
    sv = acct1 / "SavedVariables"
    for name in ("Auctionator.lua", "Auctionator.lua.bak", "Auctionator.lua.pre-schema8-20260926-103400",
                 "Details.lua", "Details.lua - Copy.bak", "Uninstalled.lua", "Uninstalled.lua.bak",
                 "DisabledAddon.lua", "Blizzard_Foo.lua", "notes.txt"):
        _write(sv / name)
    _write(sv / "OldAddon.lua", mtime=OLD)
    _write(sv / "OldAddon.lua.bak", mtime=OLD)
    _write(acct1 / "config-cache.wtf", "SET x 1\n")

    char_a = acct1 / "Realm1" / "CharA"
    _write(char_a / "AddOns.txt",
           "Auctionator: enabled\nDetails: enabled\nDisabledAddon: disabled\nOldAddon: enabled\n")
    _write(char_a / "SavedVariables" / "Auctionator.lua")
    _write(char_a / "SavedVariables" / "Uninstalled.lua")

    acct2 = retail / "WTF" / "Account" / "ACCT2"
    _write(acct2 / "SavedVariables" / "Details.lua")
    char_b = acct2 / "Realm2" / "Chârb"
    _write(char_b / "AddOns.txt",
           "Auctionator: enabled\nDetails: disabled\nDisabledAddon: disabled\nOldAddon: disabled\ngarbage line\n")
    _write(char_b / "SavedVariables" / "Details.lua")

    era = root / "_classic_era_"
    _addon(era, "Questie")
    _write(era / "WTF" / "Account" / "ACCT1" / "SavedVariables" / "Questie.lua")
    _write(era / "WTF" / "Account" / "ACCT1" / "Realm1" / "NoTxt" / "SavedVariables" / "Questie.lua")

    _write(root / "_anniversary_" / "WTF" / "Account" / "ACCT1" / "SavedVariables" / "Foo.lua")
    (root / "_notaflavor").mkdir(parents=True, exist_ok=True)
    return root


def make_config(directory: Path, wow_root: Path, **general: str) -> Config:
    """A saved config pointing at a fixture tree, with update checks off (no network in tests)."""
    cfg = Config(directory / "wow-tools.cfg")
    cfg.set("general", "wow_path", str(wow_root), log=False)
    cfg.set("general", "check_for_updates", "false", log=False)
    cfg.set("general", "last_flavor", "_retail_", log=False)
    for key, value in general.items():
        cfg.set("general", key, value, log=False)
    cfg.save()
    return cfg
