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
_retail_/WTF/Account/ACCT2/Realm2/Chârb: AddOns.txt (Auctionator, Details enabled; DisabledAddon, OldAddon
                                         disabled; one garbage line), SV: Details.lua
_classic_era_: Questie installed; ACCT1 account SV Questie.lua; Realm1/NoTxt (no AddOns.txt)
_anniversary_: WTF only, no Interface/AddOns (scanning it must abort)
_notaflavor: not a flavor folder

build_multi_account_tree(root) builds a separate retail install whose accounts enable different addons (see its
docstring): the per-account "not enabled" rule.
build_screenshot_tree(root) adds Screenshots folders (see its docstring); SHOT_BYTES maps each valid shot
name to its bytes.
build_interface_tree(root) adds known bytes to _retail_'s Interface and WTF and an empty _ptr_ flavor.
build_ace_tree(root) builds a separate install with AceDB SavedVariables (CRLF, written byte-exact; see its
docstring and the ACE_* texts); ace_lua(*lines) makes SavedVariables text the way WoW writes it.
build_sv_tree(root) builds a separate install for the Saved Variables Browser (see its docstring and the SVB_*
texts): two flavors, two accounts, account-wide and per-character files, nested tables, numeric/boolean keys,
Font/font/barFont keys, SVB_FONT in several files and flavors, escapes, floats, a nil array slot with -- [n]
comments, a Blizzard_* file, a .bak and a broken file.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
import unittest
from unittest import mock
from pathlib import Path

from textual.screen import ModalScreen
from textual.widgets._footer import FooterKey

from wowtools.core.config import Config
from wowtools.ui.branding import KeyFooter, footer_bindings
from wowtools.ui.tree_filter import FILTER_BUTTON_ID, FilterInput
from wowtools.ui.widgets import ActionButton, NavHint, button_keys, key_text, shown

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
           "Auctionator: enabled\nDetails: enabled\nDisabledAddon: disabled\nOldAddon: disabled\ngarbage line\n")
    _write(char_b / "SavedVariables" / "Details.lua")

    era = root / "_classic_era_"
    _addon(era, "Questie")
    _write(era / "WTF" / "Account" / "ACCT1" / "SavedVariables" / "Questie.lua")
    _write(era / "WTF" / "Account" / "ACCT1" / "Realm1" / "NoTxt" / "SavedVariables" / "Questie.lua")

    _write(root / "_anniversary_" / "WTF" / "Account" / "ACCT1" / "SavedVariables" / "Foo.lua")
    (root / "_notaflavor").mkdir(parents=True, exist_ok=True)
    return root


def build_multi_account_tree(root: Path) -> Path:
    """A retail install with Details, WeakAuras and Plater installed and three accounts:
    MAIN: Alpha enables Details and WeakAuras (Plater disabled); Gamma disables Details. SV: Details.lua,
          WeakAuras.lua, Plater.lua account-wide; Details.lua for Alpha and for Gamma.
    ALT:  Beta enables WeakAuras only. SV: Details.lua, WeakAuras.lua account-wide; Details.lua for Beta.
    BARE: no characters. SV: Plater.lua account-wide.
    Every file is fresh and canonical, so only the "not enabled" rule proposes anything."""
    retail = root / "_retail_"
    for name in ("Details", "WeakAuras", "Plater"):
        _addon(retail, name)
    accounts = retail / "WTF" / "Account"
    _write(accounts / "MAIN" / "Realm1" / "Alpha" / "AddOns.txt",
           "Details: enabled\nWeakAuras: enabled\nPlater: disabled\n")
    _write(accounts / "MAIN" / "Realm1" / "Gamma" / "AddOns.txt",
           "Details: disabled\nWeakAuras: enabled\nPlater: disabled\n")
    _write(accounts / "ALT" / "Realm1" / "Beta" / "AddOns.txt",
           "Details: disabled\nWeakAuras: enabled\nPlater: disabled\n")
    for path in ("MAIN/SavedVariables/Details.lua", "MAIN/SavedVariables/WeakAuras.lua",
                 "MAIN/SavedVariables/Plater.lua", "MAIN/Realm1/Alpha/SavedVariables/Details.lua",
                 "MAIN/Realm1/Gamma/SavedVariables/Details.lua", "ALT/SavedVariables/Details.lua",
                 "ALT/SavedVariables/WeakAuras.lua", "ALT/Realm1/Beta/SavedVariables/Details.lua",
                 "BARE/SavedVariables/Plater.lua"):
        _write(accounts / path)
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
    about 15x slower (every callback is timed and logged); the tests do not need it, so it is switched off.
    ConfirmScreen's Enter/Space guard (CONFIRM_GUARD) is off too, so a test can press Enter on a confirm at once;
    tests of the guard turn it back on with `confirm_guard(seconds)`."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        asyncio.get_running_loop().set_debug(False)
        from wowtools.ui import dialogs
        patcher = mock.patch.object(dialogs, "CONFIRM_GUARD", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def confirm_guard(self, seconds: float) -> None:
        from wowtools.ui import dialogs
        dialogs.CONFIRM_GUARD = seconds  # the asyncSetUp patcher puts the real value back


def submit_filter(screen, text: str) -> None:
    """Put `text` in a tree screen's filter box and submit it, as Enter there does (spec D40: typing alone never
    filters). Await settle() after it."""
    screen.filter_input().value = text
    screen.submit_filter()


async def settle(app, pilot, timeout: float = 30.0) -> None:
    """Wait until background workers are done and the screen has drawn what they produced. One pause after
    `wait_for_complete()` is not always enough on a slow machine (CI on Windows): a worker may not have started
    yet, or a list rebuild scheduled with `call_after_refresh` may still be pending. Past `timeout` it fails,
    naming what was still busy: a state that never settles (a footer left stale) must not pass as settled. The
    30 s bound is for a loaded CI runner: on windows / 3.13 the WTF Cleaner's result screen after a clean still had
    messages queued at 10 s (CI runs 37661658846 and 37733704942), while it settles in well under 1 s here."""
    deadline = time.monotonic() + timeout
    stale_footer = False
    while True:
        await app.workers.wait_for_complete()
        await pilot.pause()
        footer = _footers_stale(app)
        stale_footer = stale_footer or footer
        busy = {"workers": any(not worker.is_finished for worker in app.workers),
                "rebuild": getattr(app.screen, "_rebuild_pending", False), "footer": footer,
                "messages": _messages_pending(app)}
        if not any(busy.values()):
            if stale_footer:
                await pilot.pause()  # the footer just recomposed: let the screen draw it
            return
        if time.monotonic() > deadline:
            raise AssertionError(f"settle() timed out after {timeout}s on {type(app.screen).__name__}; still busy: "
                                 + ", ".join(name for name, on in busy.items() if on))


async def accept_disclaimer(app, pilot) -> None:
    """The USE AT YOUR OWN RISK warning (ui.disclaimer, L4) of the WTF Cleaner, Ace3 Profile Manager and Saved
    Variables Browser comes after the flavor (and account) pick: accept it when it is the screen shown (any other
    tool, or one accepted before in this app session: nothing to do)."""
    from wowtools.ui.disclaimer import ACCEPT, DisclaimerScreen
    if isinstance(app.screen, DisclaimerScreen):
        app.screen.choose(ACCEPT)
        await settle(app, pilot)


def stage_sv_edit(review) -> None:
    """Stage one value edit on a Saved Variables Browser review (what its Apply / Dry run needs): the first string
    value found in the scanned files (Retail's first), read here in the test's thread, gets " (edited)" added."""
    for file in sorted(review.scan.files(), key=lambda f: f.flavor.folder != "_retail_"):
        doc = review.document(file)
        nodes = list(doc.roots())
        while nodes:
            node = nodes.pop(0)
            if node.is_table:
                nodes.extend(doc.children(node))
            elif (node.is_scalar and isinstance(node.value.value, str)
                  and review.staging.set_value(doc, node, node.value.value + " (edited)").ok):
                review._refresh_labels()
                return
    raise AssertionError("no string value to stage an edit on")


def _messages_pending(app) -> bool:
    """True while the app or a widget of the top screen has messages waiting: a rebuild that expands a tree node
    posts NodeExpanded, and under load (16 shards on native Windows) the pause above could end before the screen
    handled it (#8)."""
    return bool(app.message_queue_size) or any(
        node.message_queue_size for node in app.screen.walk_children(with_self=True))


def _footers_stale(app) -> bool:
    """True while a KeyFooter the user sees has not composed yet, does not list its screen's footer_bindings or has
    keys not yet mounted and laid out: the top screen's, and under popups (ModalScreens) the screen beneath them.
    The footer recomposes through `call_after_refresh` after the bindings change; on native Windows (Python 3.14)
    that refresh can come after the pause in settle(), and a test read an empty footer (#8). A screen hidden under
    another full screen keeps a stale footer: not checked."""
    for screen in reversed(app.screen_stack):
        wanted = {binding.key for binding, _enabled, _tooltip in footer_bindings(screen)}
        for footer in screen.query(KeyFooter):
            keys = list(footer.query(FooterKey))
            if (not footer._bindings_ready or {key.key for key in keys} != wanted
                    or not all(key.is_mounted and key.region.width for key in keys)):
                return True
        if not isinstance(screen, ModalScreen):
            return False
    return False


async def footer_keys(screen, pilot, wanted: set[str], timeout: float = 10.0) -> set[str]:
    """The keys `screen`'s footer lists, once it lists every key in `wanted` (or the timeout passes). The footer
    recomposes through `call_after_refresh`, so right after `settle()` it may still be empty or stale."""
    deadline = time.monotonic() + timeout
    while True:
        keys = {key.key for key in screen.query(FooterKey)}
        if wanted <= keys or time.monotonic() > deadline:
            return keys
        await pilot.pause()


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


SVB_FONT = "Friz Quadrata TT"
SVB_ELVUI = ace_lua(
    'ElvDB = {', '["profiles"] = {', '["Default"] = {', '["general"] = {', f'["font"] = "{SVB_FONT}",',
    '["fontSize"] = 12,', '["scale"] = 0.6000000000000001,', '["autoRepair"] = true,', '},',
    '["unitframe"] = {', f'["Font"] = "{SVB_FONT}",', '["barFont"] = "Expressway",', '[1] = "first",',
    '[2] = 2.5,', '[true] = "yes",', '[false] = 0,', '},', '},', '},', '}',
    'ElvPrivateDB = {', '["install_complete"] = 13.52,', '}',
    'ElvVersion = nil')
SVB_DETAILS = ace_lua(
    '_detalhes_global = {', '["font_face"] = "Arial Narrow",', '["tooltip"] = {', f'["fontface"] = "{SVB_FONT}",',
    '["text"] = "a\\"b\\\\c\\n\\226\\128\\148",', '},', '["bars"] = {', '"one", -- [1]', 'nil, -- [2]',
    '"three", -- [3]', '},', '}',
    'DetailsVersion = 4')
SVB_PERCHAR = ace_lua('ElvCharacterDB = {', '["font"] = "Expressway",', '["nested"] = {', '["deeper"] = {',
                      f'["barFont"] = "{SVB_FONT}",', '["size"] = -3,', '},', '},', '}')
SVB_QUESTIE = ace_lua('QuestieConfig = {', '["global"] = {', f'["font"] = "{SVB_FONT}",', '["enabled"] = false,',
                      '},', '}')
SVB_QUESTIE_CHAR = ace_lua('QuestieConfigCharacter = {', '["journey"] = {', '{', '["Event"] = "Quest",', '}, -- [1]',
                           '},', '}')
SVB_BLIZZARD = ace_lua('Blizzard_Console_SavedVars = {', '["fontHeight"] = 14,', '}')
SVB_BARTENDER = ace_lua('Bartender4DB = {', '["font"] = "friz quadrata tt",', '}')
SVB_BROKEN = ace_lua('BrokenDB = {', '["font"] = "Friz')


def build_sv_tree(root: Path) -> Path:
    """A WoW install for the Saved Variables Browser (spec §7; texts are the SVB_* constants above, CRLF):

    _retail_/WTF/Account/ACCT1
      SavedVariables: ElvUI.lua (ElvDB nested profiles: font/Font/barFont/fontSize keys, a float, booleans,
      numeric keys [1]/[2], boolean keys [true]/[false]; ElvPrivateDB; top-level ElvVersion = nil),
      ElvUI.lua.bak (never listed), Details.lua (_detalhes_global: escapes \\" \\\\ \\n \\226\\128\\148, an
      array with a nil slot and -- [n] comments; DetailsVersion = 4), Blizzard_Console.lua, Broken.lua (unparsable)
      Realm1/Kaelys/SavedVariables/ElvUI.lua (per character, nested barFont)
    _retail_/WTF/Account/ACCT2: SavedVariables/Details.lua; Realm2/Chârb/SavedVariables/Bartender4.lua (font in
      lower case, only a case-insensitive match)
    _classic_era_/WTF/Account/ACCT1: SavedVariables/Questie.lua; Realm1/Kaelys/SavedVariables/Questie.lua (an
      array entry that is a table)
    SVB_FONT ("Friz Quadrata TT") is a value in ElvUI.lua (twice), Details.lua (both accounts), the per-character
    ElvUI.lua and Questie.lua.
    """
    retail = root / "_retail_"
    _addon(retail, "ElvUI")
    acct1 = retail / "WTF" / "Account" / "ACCT1"
    sv = acct1 / "SavedVariables"
    _write_lua(sv / "ElvUI.lua", SVB_ELVUI)
    _write_lua(sv / "ElvUI.lua.bak", SVB_ELVUI)
    _write_lua(sv / "Details.lua", SVB_DETAILS)
    _write_lua(sv / "Blizzard_Console.lua", SVB_BLIZZARD)
    _write_lua(sv / "Broken.lua", SVB_BROKEN)
    _write_lua(acct1 / "Realm1" / "Kaelys" / "SavedVariables" / "ElvUI.lua", SVB_PERCHAR)
    acct2 = retail / "WTF" / "Account" / "ACCT2"
    _write_lua(acct2 / "SavedVariables" / "Details.lua", SVB_DETAILS)
    _write_lua(acct2 / "Realm2" / "Chârb" / "SavedVariables" / "Bartender4.lua", SVB_BARTENDER)
    era = root / "_classic_era_"
    _addon(era, "Questie")
    era_acct = era / "WTF" / "Account" / "ACCT1"
    _write_lua(era_acct / "SavedVariables" / "Questie.lua", SVB_QUESTIE)
    _write_lua(era_acct / "Realm1" / "Kaelys" / "SavedVariables" / "Questie.lua", SVB_QUESTIE_CHAR)
    return root


# The action a button with no BUTTON_ACTIONS entry or choose(id) performs (handled in on_button_pressed). A button
# whose id is itself an action name (Cancel: "cancel") needs no entry.
SPECIAL_BUTTON_ACTIONS = {"yes": "answer(True)", "no": "answer(False)", "back": "escape", "update-no": "later",
                          "ok": "close"}


def assert_keys_on_buttons(test, screen) -> None:
    """Spec D17 on one screen: a button whose action has a key shows that key (on its own line, or after the label
    on a compact one), a key shown on a button does something there, and the screen's footer lists none of the keys
    its shown buttons carry, nor another key of the same action (Esc for No)."""
    bound: dict[str, set[str]] = {}  # action -> its keys
    for binding in screen._bindings.key_to_bindings.values():
        for b in binding:
            bound.setdefault(b.action, set()).add(b.key)
    buttons = list(screen.query(ActionButton))
    test.assertTrue(buttons, screen)
    for button in buttons:
        actions = {getattr(screen, "BUTTON_ACTIONS", {}).get(button.id), f"choose('{button.id}')",
                   SPECIAL_BUTTON_ACTIONS.get(button.id), (button.id or "").replace("-", "_")}
        keys = set().union(*(bound.get(a, set()) for a in actions if a))
        if keys:  # its action has a key: the button shows one of them
            test.assertIn(button.shortcut, keys, (screen, button.id))
        if button.id == FILTER_BUTTON_ID:  # the tree filter's button (D40): its key, Enter, is the filter box's
            box = button.parent.query_one(FilterInput)
            test.assertIn(button.shortcut, {b.key for b in box._bindings.key_to_bindings.get("enter", [])},
                          (screen, button.id))
        elif button.shortcut is not None:  # and a key shown on a button does something on this screen
            test.assertIn(button.shortcut, screen._bindings.key_to_bindings, (screen, button.id))
        if button.shortcut is not None:
            plain = button.label.plain
            test.assertTrue(plain.endswith(f"({key_text(button.shortcut)})"), plain)
    shortcuts = {key_text(b.shortcut) for b in buttons if b.shortcut and shown(b)}
    for hint in screen.query(NavHint):  # nor does a hint repeat one ("Esc back" beside "Back to review (Esc)")
        named = {item.split(" ")[0] for item in hint.hint.split(" · ")} | {
            key for item in hint.hint.split(" · ") for key in item.split(" ")[0].split("/")}
        test.assertFalse(named & shortcuts, (screen, hint.hint, named & shortcuts))
    footers = list(screen.query(KeyFooter))
    if not footers:
        return  # a popup: the footer under it is its screen's
    on_buttons = button_keys(screen)
    listed = {key.key for key in screen.query(FooterKey)}
    test.assertFalse(listed & on_buttons, (screen, listed & on_buttons))
    covered = {screen.active_bindings[k].binding.action for k in on_buttons if k in screen.active_bindings}
    test.assertFalse({key.action for key in screen.query(FooterKey)} & covered, screen)
    test.assertEqual(len(listed), len(footer_bindings(screen)))


@contextlib.contextmanager
def record_fsyncs(module=None):
    """Record ("fsync", size of the file) for every os.fsync and, when `module` is given, ("rename", size of the
    source) for every call of that module's rename_no_replace (F-012: a safety zip reaches the disk before it is
    moved into place). Yields the list of calls."""
    calls: list[tuple[str, int]] = []
    real_fsync = os.fsync

    def fsync(fd):
        calls.append(("fsync", os.fstat(fd).st_size))
        real_fsync(fd)

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch("os.fsync", side_effect=fsync))
        if module is not None:
            real_rename = module.rename_no_replace

            def rename(src, dst):
                calls.append(("rename", Path(src).stat().st_size))
                return real_rename(src, dst)

            stack.enter_context(mock.patch.object(module, "rename_no_replace", side_effect=rename))
        yield calls


class CpuTime:
    """What `cpu_seconds()` yields: `seconds` is set when the block ends."""

    seconds = 0.0


@contextlib.contextmanager
def cpu_seconds():
    """Measure the CPU time this process spends inside the block (time.process_time(): every thread of the
    process, never time spent waiting). A CPU-cost budget of in-process work (parsing, compiling,
    searching) asserts on this, not on wall time: `run_tests.py --all` runs the WSL and Windows suites at once on
    every CPU, and wall time under that load broke a 4 s budget the work itself meets. Wall time stays for tests
    that bound a wait (a worker, a subprocess, a timeout), which CPU time cannot see. Under WSL CPU time still grows
    while the Windows side holds a vCPU back, so a budget keeps a wide margin or asserts on how the cost grows
    (docs/testing.md, Timing races). Yields a CpuTime."""
    timer = CpuTime()
    started = time.process_time()
    try:
        yield timer
    finally:
        timer.seconds = time.process_time() - started
