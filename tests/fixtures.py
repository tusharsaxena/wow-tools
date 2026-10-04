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

build_screenshot_tree(root) adds Screenshots folders (see its docstring); SHOT_BYTES maps each valid shot
name to its bytes.
build_interface_tree(root) adds known bytes to _retail_'s Interface and WTF and an empty _ptr_ flavor.
build_ace_tree(root) builds a separate install with AceDB SavedVariables (CRLF, written byte-exact; see its
docstring and the ACE_* texts); ace_lua(*lines) makes SavedVariables text the way WoW writes it.
"""
from __future__ import annotations

import asyncio
import os
import time
import unittest
from pathlib import Path

from wowtools.core.config import Config

# Terminal sizes (docs/superpowers/specs/2026-10-04-ace-profiles-design.md, Addendum B): screens are designed for
# Windows Terminal's default window (BASE) and grow when it is maximized (LARGE); TINY only has to keep working.
BASE = (120, 30)
LARGE = (160, 45)
TINY = (80, 24)

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


def build_solo_tree(root: Path) -> Path:
    """A retail install whose only account, SOLO, has account-wide SavedVariables and no character folders.
    Details and WeakAuras are installed; Gone is not."""
    retail = root / "_retail_"
    for name in ("Details", "WeakAuras"):
        _addon(retail, name)
    sv = retail / "WTF" / "Account" / "SOLO" / "SavedVariables"
    for name in ("Details.lua", "WeakAuras.lua", "Gone.lua"):
        _write(sv / name)
    return root


class TuiTestCase(unittest.IsolatedAsyncioTestCase):
    """Base for Textual tests. IsolatedAsyncioTestCase runs its loop in asyncio debug mode, which makes Textual
    about 15x slower (every callback is timed and logged); the tests do not need it, so it is switched off."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        asyncio.get_running_loop().set_debug(False)


async def settle(app, pilot, timeout: float = 10.0) -> None:
    """Wait until background workers are done and the screen has drawn what they produced. One pause after
    `wait_for_complete()` is not always enough on a slow machine (CI on Windows): a worker may not have started
    yet, or a list rebuild scheduled with `call_after_refresh` may still be pending."""
    deadline = time.monotonic() + timeout
    while True:
        await app.workers.wait_for_complete()
        await pilot.pause()
        busy = (any(not worker.is_finished for worker in app.workers)
                or getattr(app.screen, "_rebuild_pending", False))
        if not busy or time.monotonic() > deadline:
            return


SHOT_BYTES = {
    "WoWScrnShot_073119_232713.jpg": b"shot-a",
    "WoWScrnShot_073119_232800.jpg": b"shot-b",
    "WoWScrnShot_080119_101010.PNG": b"shot-c",
    "WoWScrnShot_010224_000001.tga": b"shot-d",
    "WoWScrnShot_120520_111111.jpg": b"era-1",
    "WoWScrnShot_120520_111112.jpg": b"era-2",
}
OLD_SHOT = NOW - 30 * DAY


def _write_bytes(path: Path, data: bytes, mtime: float = OLD_SHOT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return path


def build_screenshot_tree(root: Path) -> Path:
    """Screenshots for the synthetic install (call after build_wow_tree):

    _retail_/Screenshots: 4 shots (2 on 2019-07-31, 1 on 2019-08-01 with .PNG, 1 on 2024-01-02 with .tga),
        WoWScrnShot_023119_120000.jpg (bad date), notes.txt, and 2025/01/02/WoWScrnShot_010225_090000.jpg
        (already filed in place; never rescanned)
    _classic_era_/Screenshots: 2 shots on 2020-12-05
    _anniversary_: no Screenshots folder
    """
    retail = root / "_retail_" / "Screenshots"
    era = root / "_classic_era_" / "Screenshots"
    for name, data in SHOT_BYTES.items():
        _write_bytes((era if data.startswith(b"era") else retail) / name, data)
    _write_bytes(retail / "WoWScrnShot_023119_120000.jpg", b"bad-date")
    _write_bytes(retail / "notes.txt", b"notes")
    _write_bytes(retail / "2025" / "01" / "02" / "WoWScrnShot_010225_090000.jpg", b"filed")
    return root


def build_interface_tree(root: Path) -> Path:
    """Interface Backup extras (call after build_wow_tree): known bytes in _retail_'s Interface and WTF, and an
    empty _ptr_ flavor (neither part). _anniversary_ already has WTF only."""
    retail = root / "_retail_"
    _write_bytes(retail / "Interface" / "AddOns" / "Auctionator" / "Auctionator.lua", b"auc")
    _write_bytes(retail / "Interface" / "AddOns" / "Details" / "core.lua", b"det")
    _write_bytes(retail / "WTF" / "Config.wtf", b"SET a 1\n")
    (root / "_ptr_").mkdir(parents=True, exist_ok=True)
    return root


def ace_lua(*lines: str) -> str:
    """SavedVariables text the way WoW writes it: a leading blank line, CRLF, no indentation."""
    return "\r\n" + "\r\n".join(lines) + "\r\n"


def _write_lua(path: Path, text: str, mtime: float = FRESH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    os.utime(path, (mtime, mtime))
    return path


ACE_KICKCD = ace_lua(
    'KickCDDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Default",', '["Mierin - Khaz Modan"] = "Default",',
    '["Gone - Realm1"] = "Default",', '},', '["profiles"] = {', '["Default"] = {', '["scale"] = 0.6000000000000001,',
    '["text"] = "a\\"b\\\\c\\n\\000",', '[114052] = true,', '},', '["Backup"] = {', '},', '},',
    '["global"] = {', '["schemaVersion"] = 3,', '},', '}',
    'KickCDPerfDB = {', '["runs"] = 3,', '}')
ACE_HANDYNOTES = ace_lua(
    'HandyNotesDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Kaelys - Realm1",',
    '["Mierin - Khaz Modan"] = "Mierin - Khaz Modan",', '},', '["profiles"] = {',
    '["Kaelys - Realm1"] = {', '["icon_scale"] = 1.5,', '},', '["Mierin - Khaz Modan"] = {', '},',
    '["Unused - Realm1"] = {', '["icon_scale"] = 2,', '},', '},', '}',
    'HandyNotes_MapNotesDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Default",', '},',
    '["profiles"] = {', '["Default"] = {', '["notes"] = {', '"TOP",', 'nil,', '"TOP",', '},', '},', '},', '}')
ACE_ELVUI = ace_lua(
    'ElvDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Default",', '["Mierin - Khaz Modan"] = "Healer",', '},',
    '["profiles"] = {', '["Default"] = {', '["x"] = 1,', '},', '["Healer"] = {', '["x"] = 2,', '},', '},',
    '["namespaces"] = {', '["Bags"] = {', '["profiles"] = {', '["Default"] = {', '["b"] = 1,', '},',
    '["Healer"] = {', '["b"] = 2,', '},', '},', '},', '["LibDualSpec-1.0"] = {', '["char"] = {',
    '["Kaelys - Realm1"] = {', '["enabled"] = true,', '[1] = "Default",', '[2] = "Healer",', '},', '},', '},', '},',
    '}',
    'ElvPrivateDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Kaelys - Realm1",', '},',
    '["profiles"] = {', '["Kaelys - Realm1"] = {', '["install"] = true,', '},', '},', '}')
ACE_STOCK = ace_lua('StockDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Gone",', '},', '["global"] = {',
                    '},', '}')
ACE_MEMENTO = ace_lua('Memento = {', '["profileKeys"] = {', '["Player-3725-0A"] = {', '},', '},', '}')
ACE_BROKEN = ace_lua('BrokenDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Default",')
ACE_PERCHAR = ace_lua('PerCharDB = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Default",', '},',
                      '["profiles"] = {', '["Default"] = {', '},', '},', '}')
ACE_ACCT2 = ace_lua('KickCDDB = {', '["profileKeys"] = {', '["Chârb - Realm2"] = "Default",', '},',
                    '["profiles"] = {', '["Default"] = {', '},', '},', '}')
ACE_QUESTIE = ace_lua('QuestieConfig = {', '["profileKeys"] = {', '["Kaelys - Realm1"] = "Default",', '},',
                      '["profiles"] = {', '["Default"] = {', '},', '},', '}')


def build_ace_tree(root: Path) -> Path:
    """A WoW install with AceDB SavedVariables (see ACE_* above):

    _retail_/WTF/Account/ACCT1: characters Realm1/Kaelys and "Khaz Modan"/Mierin
      SavedVariables: KickCD.lua (KickCDDB, Default shared, leftover "Gone - Realm1", unused Backup; KickCDPerfDB
      plain), KickCD.lua.bak (ignored), HandyNotes.lua (char-keyed HandyNotesDB with an unused profile, plus
      HandyNotes_MapNotesDB), ElvUI.lua (ElvDB with namespace Bags and LibDualSpec; ElvPrivateDB), Stock.lua
      (StockDB: missing profile "Gone"), Memento.lua (look-alike), Broken.lua (unparsable), Plain.lua (no AceDB),
      Blizzard_AceThing.lua (skipped by name)
      Realm1/Kaelys/SavedVariables/PerChar.lua (per-character PerCharDB)
    _retail_/WTF/Account/ACCT2: Realm2/Chârb; SavedVariables/KickCD.lua
    _classic_era_/WTF/Account/ACCT1: Realm1/Kaelys; SavedVariables/Questie.lua (QuestieConfig)
    """
    retail = root / "_retail_"
    _addon(retail, "KickCD")
    acct1 = retail / "WTF" / "Account" / "ACCT1"
    sv = acct1 / "SavedVariables"
    _write_lua(sv / "KickCD.lua", ACE_KICKCD)
    _write_lua(sv / "KickCD.lua.bak", ACE_KICKCD)
    _write_lua(sv / "HandyNotes.lua", ACE_HANDYNOTES)
    _write_lua(sv / "ElvUI.lua", ACE_ELVUI)
    _write_lua(sv / "Stock.lua", ACE_STOCK)
    _write_lua(sv / "Memento.lua", ACE_MEMENTO)
    _write_lua(sv / "Broken.lua", ACE_BROKEN)
    _write_lua(sv / "Plain.lua", ace_lua('PlainDB = {', '["x"] = 1,', '}'))
    _write_lua(sv / "Blizzard_AceThing.lua", ACE_PERCHAR)
    _write_lua(acct1 / "Realm1" / "Kaelys" / "SavedVariables" / "PerChar.lua", ACE_PERCHAR)
    (acct1 / "Khaz Modan" / "Mierin").mkdir(parents=True, exist_ok=True)
    acct2 = retail / "WTF" / "Account" / "ACCT2"
    _write_lua(acct2 / "SavedVariables" / "KickCD.lua", ACE_ACCT2)
    (acct2 / "Realm2" / "Chârb").mkdir(parents=True, exist_ok=True)
    era = root / "_classic_era_"
    _addon(era, "Questie")
    _write_lua(era / "WTF" / "Account" / "ACCT1" / "SavedVariables" / "Questie.lua", ACE_QUESTIE)
    (era / "WTF" / "Account" / "ACCT1" / "Realm1" / "Kaelys").mkdir(parents=True, exist_ok=True)
    return root
