#!/usr/bin/env python3
"""Retake every screenshot in docs/assets/screenshots/ from a made-up WoW folder, the same way each time.

Run it before a release, after any change a screenshot shows:

    python3 scripts/take_screenshots.py                      # every screenshot
    python3 scripts/take_screenshots.py --only config-copier # one tool's (or: --only config-copier/diff.png)
    python3 scripts/take_screenshots.py --list               # what it takes

It builds an invented WoW install in a temp folder (accounts, realms, characters, addons, SavedVariables,
screenshots, macros and CVar files; nothing personal and nothing from a real install), points a temp config at it
and drives the real app (`WowToolsApp`) through each tool with Textual's test pilot, the way the tests do. It never
reads or writes your WoW folder, `config/` or `logs/`, and never touches the network (no update check, no WoW
process check). Each screen is exported as SVG and turned into a PNG by headless Chrome at 1920x1032: a maximized
terminal on a 1920x1080 screen, as the earlier hand-taken screenshots were.

The terminal is 238x64 cells by default (`--size`): Windows Terminal maximized on a 1080p screen, with its tab bar
and Windows' taskbar, holds about that many cells, and 238 x 12.2 by 64 x 24.4 (Rich's SVG cell) has the shape of
1920x1032, so the picture fills the PNG with no border. The font is a local monospace one (`--font`).

Each screenshot is a SHOTS row: its file under docs/assets/screenshots/, the flow that takes it and a caption. A
flow takes the screenshots of one walk through a tool (review, confirm, progress, result ...) and saves only the
ones asked for. To add one, add a row and a `capture(...)` call in its flow (or a new flow). A progress window is
caught mid-run by holding the worker on its report (`hold_progress`).

Each tool also gets a showcase, `<tool>/showcase.png`, the image the README shows for it: a SHOWCASES row names a
full screen for the top and the popups and panels cut out below it, each with a caption. A flow saves those
screens as parts (`part(name, widget)`, the widget being the region a cut-out shows); the showcase is laid out as
an HTML page (one scale for every cut-out, packed into rows) and drawn by headless Chrome at 1920 wide.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wowtools.core.bootstrap import add_vendor_path  # noqa: E402

add_vendor_path()

from rich.console import Console  # noqa: E402

from wowtools.core.config import Config  # noqa: E402
from wowtools.ui.theme import BACKGROUND, FOREGROUND, TITLE_GOLD  # noqa: E402

OUT_DIR = ROOT / "docs" / "assets" / "screenshots"
DEFAULT_SIZE = (238, 64)
PNG_SIZE = (1920, 1032)
DEFAULT_FONT = "DejaVu Sans Mono"
MISSING_GLYPHS = {"⭘": "○"}  # glyphs no common monospace font has (the header's icon): a look-alike it has

# --------------------------------------------------------------------------------------------------------------
# The made-up WoW folder
# --------------------------------------------------------------------------------------------------------------
NOW = time.time()
DAY = 86400.0
RNG = random.Random(20261107)  # the same files (and sizes) every run

RETAIL_ADDONS = ("Details", "WeakAuras", "Plater", "BigWigs", "Bartender4", "ElvUI", "HandyNotes", "Auctionator",
                 "TomTom", "OmniCC", "BugSack", "!BugGrabber", "Leatrix_Plus", "Rarity", "SimulationCraft", "Pawn",
                 "MythicDungeonTools", "RaiderIO", "Baganator", "Masque")
CLASSIC_ADDONS = ("Questie", "Details", "WeakAuras", "Bartender4", "Auctionator", "LeatrixPlus", "Atlas")
GONE_ADDONS = ("Skada", "Recount", "Grid2", "Bagnon", "AdiBags", "Postal", "Altoholic", "Mapster", "SexyMap",
               "Prat-3.0", "Quartz", "Gladius", "Hekili", "Clique", "Dominos", "TitanPanel", "XPerl", "HealBot",
               "VuhDo", "Overachiever", "Decursive", "TellMeWhen", "AtlasLoot", "Outfitter", "GatherMate2",
               "ArkInventory", "TradeSkillMaster", "Omen", "NeedToKnow", "Bazooka", "ChocolateBar", "KuiNameplates",
               "TidyPlates", "ShadowedUnitFrames", "PitBull4", "MikScrollingBattleText", "SavedInstances",
               "Broker_Everything", "CanIMogIt", "AllTheThings", "DejaCharacterStats", "WIM")
REALMS = ("Stormreach", "Highmoor")
ACCOUNT, ALT_ACCOUNT = "71839204#1", "71839204#2"
# (account, realm, character): Retail's characters
RETAIL_CHARACTERS = ((ACCOUNT, "Stormreach", "Ellandra"), (ACCOUNT, "Stormreach", "Thrungar"),
                     (ACCOUNT, "Stormreach", "Vexis"), (ACCOUNT, "Highmoor", "Mirelle"),
                     (ALT_ACCOUNT, "Stormreach", "Korgath"), (ALT_ACCOUNT, "Highmoor", "Sylphie"))
CLASSIC_CHARACTERS = ((ACCOUNT, "Ironhold", "Bramblewick"), (ACCOUNT, "Ironhold", "Ostara"))
ERA_CHARACTERS = ((ACCOUNT, "Greymane Keep", "Grimsby"),)


def _write(path: Path, data: bytes | str, age_days: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    stamp = NOW - age_days * DAY
    os.utime(path, (stamp, stamp))
    return path


def lua(*lines: str) -> str:
    """SavedVariables text the way WoW writes it: a leading blank line, CRLF, no indentation."""
    return "\r\n" + "\r\n".join(lines) + "\r\n"


def filler_lua(name: str, size: int) -> str:
    """A plausible SavedVariables file of about `size` bytes."""
    lines = [f"{name}DB = {{", '["global"] = {']
    i = 0
    while sum(len(line) + 2 for line in lines) < size:
        lines.append(f'["setting{i}"] = {RNG.choice(["true", "false", str(RNG.randint(1, 900)), chr(34) + "x" + chr(34)])},')
        i += 1
    lines += ["},", "}"]
    return lua(*lines)


def macros(*entries: tuple[str, str, str]) -> bytes:
    """A macros-cache.txt as Retail writes it: (name, icon, body) per macro, CRLF."""
    out = []
    for number, (name, icon, body) in enumerate(entries, 1):
        out += [f'VER 3 {number:016X} "{name}" "{icon}"', *body.split("\n"), "END"]
    return ("\r\n".join(out) + "\r\n").encode("utf-8")


def cvars(*pairs: tuple[str, str]) -> bytes:
    return b"".join(f'SET {name} "{value}"\r\n'.encode() for name, value in pairs)


def ace_db(var: str, keys: dict[str, str], profiles: dict[str, list[str]]) -> str:
    """An AceDB SavedVariables table: profileKeys (character -> profile) and profiles (name -> setting lines)."""
    lines = [f"{var} = {{", '["profileKeys"] = {']
    lines += [f'["{char}"] = "{profile}",' for char, profile in keys.items()]
    lines += ["},", '["profiles"] = {']
    for name, settings in profiles.items():
        lines += [f'["{name}"] = {{', *settings, "},"]
    lines += ["},", "}"]
    return lua(*lines)


ELLANDRA_MACROS = macros(
    ("Heal Focus", "135907", "#showtooltip Flash Heal\n/cast [@mouseover,help,nodead][@focus,help][] Flash Heal"),
    ("Shield", "135940", "#showtooltip\n/cast [@mouseover,help] Power Word: Shield; Power Word: Shield"),
    ("Dispel", "135894", "/cast [@mouseover,help,nodead] Purify; [harm] Dispel Magic"),
    ("Mount", "132261", "/cast [flyable,nocombat] Grand Expedition Yak; [swimming] Sea Turtle; Swift Spectral Tiger"),
    ("Trinket", "134400", "#showtooltip 13\n/use 13\n/cast Power Infusion"),
    ("Focus Kick", "136243", "/focus [@mouseover,harm,nodead]\n/cast [@focus,harm] Silence"))
THRUNGAR_MACROS = macros(
    ("Charge", "132337", "#showtooltip\n/cast [@mouseover,harm][] Charge"),
    ("Mount", "132261", "/cast Swift Spectral Tiger"))
ELLANDRA_ADDONS = "".join(f"{name}: {'disabled' if name in ('Rarity', 'SimulationCraft') else 'enabled'}\r\n"
                          for name in RETAIL_ADDONS)
ELLANDRA_CONFIG = cvars(("nameplateShowFriends", "1"), ("cameraDistanceMaxZoomFactor", "2.6"),
                        ("assistedCombatHighlight", "1"), ("floatingCombatTextCombatDamage", "1"),
                        ("hardTrackedQuests", "78631"), ("nameplateMaxDistance", "41"),
                        ("autoLootDefault", "1"), ("showTargetOfTarget", "1"))
CHAT = (b"VERSION 5\r\n\r\nWINDOW 1\r\nNAME General\r\nSIZE 0\r\nCOLOR 0 0 0 40\r\nLOCKED 1\r\nEND\r\n\r\n"
        b"WINDOW 2\r\nNAME Combat Log\r\nSIZE 0\r\nEND\r\n\r\nWINDOW 3\r\nNAME Guild\r\nSIZE 0\r\nEND\r\n")
LAYOUT = b"LAYOUT 3\r\nEditModeLayout Healer\r\n"
FONT = "Friz Quadrata TT"


def build_world(root: Path) -> Path:
    """The made-up WoW folder every flow works on (see the module docstring)."""
    retail, classic, era = root / "_retail_", root / "_classic_", root / "_classic_era_"
    for flavor, names in ((retail, RETAIL_ADDONS), (classic, CLASSIC_ADDONS), (era, CLASSIC_ADDONS)):
        for name in names:
            folder = flavor / "Interface" / "AddOns" / name
            _write(folder / f"{name}.toc", f"## Interface: 120001\n## Title: {name}\n{name}.lua\n", 20)
            _write(folder / f"{name}.lua", "-- " + "x" * RNG.randint(2_000, 400_000), 20)
            for extra in range(RNG.randint(0, 6)):
                _write(folder / "modules" / f"module{extra}.lua", "-- " + "y" * RNG.randint(500, 80_000), 20)
    _write(retail / "WTF" / "Config.wtf", cvars(("gxMaximize", "1"), ("Sound_MasterVolume", "0.4"),
                                                ("graphicsQuality", "7"), ("portal", "EU"), ("textLocale", "enUS"),
                                                ("audioLocale", "enUS"), ("Gamma", "1.05"), ("MSAAQuality", "2")))
    _build_retail_accounts(retail)
    _build_classic(classic, era)
    _build_screenshots(root)
    return root


def _build_retail_accounts(retail: Path) -> None:
    accounts = retail / "WTF" / "Account"
    main = accounts / ACCOUNT
    sv = main / "SavedVariables"
    for name in RETAIL_ADDONS:
        if name in ("ElvUI", "HandyNotes", "Bartender4", "Details", "WeakAuras", "Plater", "BigWigs", "OmniCC"):
            continue  # written below with real content
        _write(sv / f"{name}.lua", filler_lua(name.strip("!"), RNG.randint(300, 60_000)), RNG.randint(0, 40))
    for name in GONE_ADDONS:
        age = RNG.choice((RNG.randint(5, 80), RNG.randint(100, 400)))
        _write(sv / f"{name}.lua", filler_lua(name, RNG.randint(200, 90_000)), age)
        if RNG.random() < 0.7:
            _write(sv / f"{name}.lua.bak", filler_lua(name, RNG.randint(200, 90_000)), age)
    _write(sv / "Rarity.lua", filler_lua("Rarity", 40_000), 3)
    _write(sv / "Details.lua - Copy.bak", filler_lua("Details", 120_000), 9)
    _write(sv / "WeakAuras.lua.pre-schema81-20260412-221500", filler_lua("WeakAuras", 300_000), 30)
    _write(sv / "Grid.lua.bak", filler_lua("Grid", 4_000), 220)  # a backup whose .lua is gone
    _write(sv / "Blizzard_Console.lua", lua("Blizzard_Console_SavedVars = {", '["fontHeight"] = 14,', "}"), 1)
    characters = [c for c in RETAIL_CHARACTERS]
    keys = {f"{char} - {realm}": "Default" for _account, realm, char in characters if _account == ACCOUNT}
    keys["Oldmain - Stormreach"] = "Default"  # a character deleted long ago: a leftover
    healer = {k: ("Healer" if k.startswith(("Ellandra", "Mirelle")) else "Default") for k in keys}
    _write(sv / "ElvUI.lua", ace_db("ElvDB", healer, {
        "Default": ['["general"] = {', f'["font"] = "{FONT}",', '["fontSize"] = 12,', '["autoRepair"] = true,', "},",
                    '["unitframe"] = {', f'["font"] = "{FONT}",', '["fontSize"] = 13,', "},"],
        "Healer": ['["general"] = {', f'["font"] = "{FONT}",', '["fontSize"] = 12,', "},",
                   '["unitframe"] = {', '["font"] = "Expressway",', '["smoothbars"] = true,', "},"],
        "Minimal": ['["general"] = {', '["fontSize"] = 11,', "},"]}) + lua(
        "ElvPrivateDB = {", '["install_complete"] = 13.82,', "}"), 1)
    _write(sv / "Bartender4.lua", ace_db("Bartender4DB", keys, {
        "Default": ['["font"] = "Friz Quadrata TT",', '["fontSize"] = 11,'],
        "Old setup": ['["fontSize"] = 9,']}), 2)
    _write(sv / "HandyNotes.lua", ace_db("HandyNotesDB", {k: k for k in keys}, {
        k: ['["icon_scale"] = 1.2,', '["icon_alpha"] = 0.9,'] for k in keys}), 2)
    _write(sv / "Details.lua", lua("_detalhes_global = {", '["font_face"] = "Accidental Presidency",',
                                   '["tooltip"] = {', f'["fontface"] = "{FONT}",', '["fontsize"] = 11,', "},",
                                   '["segments_amount"] = 25,', "}"), 0)
    _write(sv / "WeakAuras.lua", lua("WeakAurasSaved = {", '["displays"] = {', '["Healer cooldowns"] = {',
                                     f'["font"] = "{FONT}",', '["fontSize"] = 14,', "},",
                                     '["Raid buffs"] = {', '["font"] = "Expressway",', "},", "},", "}"), 0)
    _write(sv / "Plater.lua", ace_db("PlaterDB", keys, {"Default": [f'["castbar_font"] = "{FONT}",',
                                                                      '["health_width"] = 120,']}), 4)
    _write(sv / "BigWigs.lua", ace_db("BigWigs3DB", keys, {"Default": [f'["fontName"] = "{FONT}",'],
                                                             "Raid": ['["fontName"] = "Expressway",']}), 6)
    _write(sv / "OmniCC.lua", ace_db("OmniCCDB", keys, {"Default": ['["fontFace"] = "Expressway",']}), 12)
    _write(sv / "TomTom.lua", ace_db("TomTomDB", {k: ("Arrow only" if k.startswith("Vexis") else "Default")
                                                  for k in keys},
                                     {"Default": ['["arrow"] = {', '["enable"] = true,', "},"],
                                      "Arrow only": ['["arrow"] = {', '["enable"] = true,', "},",
                                                     '["minimap"] = {', '["enable"] = false,', "},"]}), 9)
    _write(sv / "Masque.lua", ace_db("MasqueDB", keys, {"Default": ['["Groups"] = {', "},"]}), 15)
    _write(main / "macros-cache.txt", macros(("Hearth", "134414", "/use Hearthstone"),
                                              ("Pet", "132599", "/randomfavoritepet")), 3)
    _write(main / "config-cache.wtf", cvars(("autoLootDefault", "1"), ("nameplateShowAll", "1"),
                                            ("cameraSmoothStyle", "0"), ("showTutorials", "0")), 3)
    _write(main / "bindings-cache.wtf", b"BINDINGMODE 0\r\nbind ALT-CTRL-F TOGGLEFPS\r\n", 3)
    alt_sv = accounts / ALT_ACCOUNT / "SavedVariables"
    alt_keys = {f"{char} - {realm}": "Default" for account, realm, char in characters if account == ALT_ACCOUNT}
    _write(alt_sv / "ElvUI.lua", ace_db("ElvDB", alt_keys, {"Default": [f'["font"] = "{FONT}",']}), 2)
    _write(alt_sv / "Details.lua", lua("_detalhes_global = {", f'["font_face"] = "{FONT}",', "}"), 2)
    for name in GONE_ADDONS[:12]:
        _write(alt_sv / f"{name}.lua", filler_lua(name, RNG.randint(200, 30_000)), RNG.randint(5, 300))
    _write(accounts / ALT_ACCOUNT / "config-cache.wtf", cvars(("autoLootDefault", "0")), 6)
    for account, realm, char in characters:
        folder = accounts / account / realm / char
        enabled = [n for n in RETAIL_ADDONS if char == "Ellandra" or RNG.random() < 0.8]
        _write(folder / "AddOns.txt", "".join(
            f"{n}: {'enabled' if n in enabled and n not in ('Rarity', 'SimulationCraft') else 'disabled'}\r\n"
            for n in RETAIL_ADDONS), 1)
        _write(folder / "SavedVariables" / "Details.lua", lua("_detalhes_database = {", '["tabela_historico"] = {',
                                                              "},", "}"), 0)
        _write(folder / "SavedVariables" / "ElvUI.lua", lua("ElvCharacterDB = {", f'["font"] = "{FONT}",',
                                                            '["nested"] = {', '["barFont"] = "Expressway",', "},",
                                                            "}"), 1)
        for name in GONE_ADDONS[3:9]:
            if RNG.random() < 0.5:
                _write(folder / "SavedVariables" / f"{name}.lua", filler_lua(name, RNG.randint(100, 9000)),
                       RNG.randint(10, 300))
        _write(folder / "layout-local.txt", LAYOUT, 2)
    ellandra = accounts / ACCOUNT / "Stormreach" / "Ellandra"
    _write(ellandra / "macros-cache.txt", ELLANDRA_MACROS, 1)
    _write(ellandra / "AddOns.txt", ELLANDRA_ADDONS, 1)
    _write(ellandra / "chat-cache.txt", CHAT, 1)
    _write(ellandra / "config-cache.wtf", ELLANDRA_CONFIG, 1)
    thrungar = accounts / ACCOUNT / "Stormreach" / "Thrungar"
    _write(thrungar / "macros-cache.txt", THRUNGAR_MACROS, 4)
    _write(thrungar / "config-cache.wtf", cvars(("hardTrackedQuests", "80022"), ("nameplateShowFriends", "0"),
                                                ("enableMultiActionBars", "15"), ("autoLootDefault", "1")), 4)
    _write(thrungar / "chat-cache.txt", CHAT.replace(b"Guild", b"Trade"), 4)
    vexis = accounts / ACCOUNT / "Stormreach" / "Vexis"
    _write(vexis / "macros-cache.txt", macros(("Polymorph", "136071", "/cast [@focus,harm] Polymorph"),
                                               ("Blink", "135736", "/cast Blink")), 5)
    _write(vexis / "config-cache.wtf", cvars(("cameraDistanceMaxZoomFactor", "1.9"), ("showTargetOfTarget", "0")), 5)
    mirelle = accounts / ACCOUNT / "Highmoor" / "Mirelle"
    _write(mirelle / "chat-cache.txt", CHAT, 7)
    korgath = accounts / ALT_ACCOUNT / "Stormreach" / "Korgath"
    _write(korgath / "macros-cache.txt", macros(("Misdirect", "132180", "/cast [@focus,help][@pet] Misdirection"),
                                                 ("Pet Attack", "132152", "/petattack [@mouseover,harm][]")), 8)
    _write(korgath / "config-cache.wtf", cvars(("nameplateShowEnemies", "1"), ("autoLootDefault", "1")), 8)


def _build_classic(classic: Path, era: Path) -> None:
    for flavor, characters in ((classic, CLASSIC_CHARACTERS), (era, ERA_CHARACTERS)):
        wtf = flavor / "WTF"
        _write(wtf / "Config.wtf", cvars(("gxMaximize", "1"), ("portal", "EU")), 10)
        sv = wtf / "Account" / ACCOUNT / "SavedVariables"
        keys = {f"{char} - {realm}": "Default" for _a, realm, char in characters}
        _write(sv / "Questie.lua", ace_db("QuestieConfig", keys, {"Default": [f'["font"] = "{FONT}",',
                                                                              '["enabled"] = true,']}), 3)
        _write(sv / "Details.lua", lua("_detalhes_global = {", f'["font_face"] = "{FONT}",', "}"), 3)
        for name in GONE_ADDONS[20:26]:
            _write(sv / f"{name}.lua", filler_lua(name, RNG.randint(200, 20_000)), RNG.randint(5, 300))
        for _a, realm, char in characters:
            folder = wtf / "Account" / ACCOUNT / realm / char
            _write(folder / "AddOns.txt", "".join(f"{n}: enabled\r\n" for n in CLASSIC_ADDONS), 3)
            _write(folder / "macros-cache.txt", macros(("Mount", "132261", "/cast Swift Brown Steed"),
                                                        ("Bandage", "133690", "/use [@player] Heavy Runecloth Bandage")),
                   3)
            _write(folder / "config-cache.wtf", cvars(("autoLootDefault", "1"), ("nameplateShowEnemies", "1")), 3)
            _write(folder / "SavedVariables" / "Questie.lua", lua("QuestieConfigCharacter = {", '["journey"] = {',
                                                                  "},", "}"), 3)


def _build_screenshots(root: Path) -> None:
    """Retail and Classic screenshots over two years, a renamed one and a note (skipped)."""
    for flavor, count in (("_retail_", 46), ("_classic_", 12)):
        folder = root / flavor / "Screenshots"
        for _ in range(count):
            stamp = time.localtime(NOW - RNG.uniform(3, 700) * DAY)
            name = time.strftime("WoWScrnShot_%m%d%y_%H%M%S.jpg", stamp)
            _write(folder / name, os.urandom(RNG.randint(300_000, 2_400_000)), 3)
    _write(root / "_retail_" / "Screenshots" / "best raid night.jpg", os.urandom(500_000), 3)
    shots = sorted((root / "_retail_" / "Screenshots").glob("WoWScrnShot_*"))
    for index, shot in enumerate(shots[:3]):  # two already in the picture folder, one there with other bytes
        _write(root.parent / "filed" / shot.name, shot.read_bytes() if index else os.urandom(1000), 3)
    _write(root / "_retail_" / "Screenshots" / "notes.txt", "Mythic+ routes", 3)


# --------------------------------------------------------------------------------------------------------------
# Rendering: a screen to SVG to PNG
# --------------------------------------------------------------------------------------------------------------
SVG_FORMAT = """\
<svg class="rich-terminal" viewBox="0 0 {terminal_width} {terminal_height}" xmlns="http://www.w3.org/2000/svg">
    <style>
    .{unique_id}-matrix {{
        font-family: __FONT__, monospace;
        font-size: 21px; /* DejaVu Sans Mono's ascent + descent (1.164 em) fill the 24.4 px row: borders join */
        line-height: {line_height}px;
        font-variant-east-asian: full-width;
    }}
    {styles}
    </style>
    <defs>
    <clipPath id="{unique_id}-clip-terminal">
      <rect x="0" y="0" width="{terminal_width}" height="{terminal_height}" />
    </clipPath>
    {lines}
    </defs>
    <rect x="0" y="0" width="{terminal_width}" height="{terminal_height}" fill="__BACKGROUND__"/>
    <g clip-path="url(#{unique_id}-clip-terminal)">
    {backgrounds}
    <g class="{unique_id}-matrix">
    {matrix}
    </g>
    </g>
</svg>
"""


def screen_svg(app, font: str) -> str:
    """The app's screen (popups and the screens under them included) as an SVG with no window frame: what
    `App.export_screenshot` draws, without Rich's title bar and margins."""
    width, height = app.size
    console = Console(width=width, height=height, file=io.StringIO(), force_terminal=True, color_system="truecolor",
                      record=True, legacy_windows=False, safe_box=False)
    console.print(app.screen._compositor.render_update(full=True, screen_stack=app._background_screens))
    code_format = SVG_FORMAT.replace("__FONT__", f'"{font}"').replace("__BACKGROUND__", BACKGROUND)
    svg = console.export_svg(title="", code_format=code_format)
    for glyph, stand_in in MISSING_GLYPHS.items():
        svg = svg.replace(glyph, stand_in)
    return svg


def find_chrome(given: str | None) -> str:
    candidates = [given] if given else ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                                        "chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                                        "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"]
    for candidate in candidates:
        found = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if found:
            return found
    raise SystemExit("No Chrome or Chromium found: pass --chrome PATH")


def svg_to_png(svg_path: Path, png_path: Path, chrome: str) -> None:
    """Draw the SVG to fill a 1920x1032 page (the theme's background around it if its shape differs) and save it."""
    page = svg_path.with_suffix(".html")
    svg = svg_path.read_text(encoding="utf-8").replace("<svg ", f'<svg width="{PNG_SIZE[0]}" height="{PNG_SIZE[1]}" ', 1)
    page.write_text(f"<!DOCTYPE html><html><body style='margin:0;background:{BACKGROUND};overflow:hidden'>{svg}"
                    "</body></html>", encoding="utf-8")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        "--force-device-scale-factor=1", f"--user-data-dir={profile}",
                        f"--window-size={PNG_SIZE[0]},{PNG_SIZE[1]}", f"--screenshot={png_path}", page.as_uri()],
                       check=True, capture_output=True, timeout=120)
    page.unlink()


# --------------------------------------------------------------------------------------------------------------
# Driving the app
# --------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Part:
    """One screen a showcase uses: its PNG and, for a cut-out, the cells it crops to (x, y, width, height)."""
    png: Path
    region: tuple[int, int, int, int] | None
    cells: tuple[int, int]  # the terminal's size in cells when it was taken


@dataclass
class Options:
    size: tuple[int, int]
    out: Path
    keep_svg: bool
    font: str
    chrome: str
    wanted: set[str]  # the SHOTS files to save
    parts: Path = Path()  # where the showcases' parts go (a temp folder)
    parts_wanted: set[str] = field(default_factory=set)  # the parts the wanted showcases use
    parts_taken: dict[str, Part] = field(default_factory=dict)


class Session:
    """One walk through the app on a fresh made-up WoW folder: the app, its pilot and `capture`."""

    def __init__(self, options: Options, tmp: Path) -> None:
        self.options = options
        self.tmp = tmp
        self.root = build_world(tmp / "World of Warcraft")
        self.config_dir = tmp / "config"
        self.dest_dir = tmp / "Pictures" / "World of Warcraft"
        self.cfg = self._config()
        self._seed_picture_folder()
        self.app: Any = None
        self.pilot: Any = None
        self.taken: list[str] = []

    def _config(self) -> Config:
        cfg = Config(self.config_dir / "wow-tools.cfg")
        for key, value in (("wow_path", str(self.root)), ("check_for_updates", "false"),
                           ("last_flavor", "_retail_"), ("parallelism", "2")):
            cfg.set("general", key, value, log=False)
        cfg.save()
        from wowtools.tools import TOOLS
        for name, tool in TOOLS.items():  # every tool set up already: no first-run settings screen
            tool_cfg = Config(self.config_dir / f"{name}.cfg")
            if tool.section == "screenshot_organizer":
                tool_cfg.set(tool.section, "dest_dir", str(self.dest_dir), log=False)
            else:  # empty: each tool's default, under <WoW>/wow-tools/
                tool_cfg.set(tool.section, "backup_dir", "", log=False)
            tool_cfg.save()
        return cfg

    def _seed_picture_folder(self) -> None:
        """Move build_world's `filed` shots to where the Screenshot Organizer would have put them."""
        from wowtools.tools.screenshot_organizer.naming import day_parts, parse_shot_name
        for shot in sorted((self.tmp / "filed").glob("*")):
            target = self.dest_dir / "_retail_" / Path(*day_parts(parse_shot_name(shot.name)))
            target.mkdir(parents=True, exist_ok=True)
            shot.rename(target / shot.name)

    def make_app(self):
        from wowtools.tools import TOOLS
        from wowtools.ui.suite_app import WowToolsApp
        quiet: dict[str, Any] = {"wow_check": list}
        options = {name: dict(quiet) for name in TOOLS if name != "screenshot-organizer"}
        options["wtf-cleaner"]["locker_check"] = list
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options=options)

    async def settle(self) -> None:
        from tests.fixtures import settle
        await settle(self.app, self.pilot, timeout=60)
        await self.pilot.pause(0.3)  # timers (progress, toasts) and the footer draw once more

    async def press(self, *keys: str) -> None:
        for key in keys:
            await self.pilot.press(key)
            await self.settle()

    async def capture(self, name: str) -> None:
        """Save the screen as `name` (a SHOTS file) if it was asked for."""
        if name not in self.options.wanted:
            return
        await self.pilot.pause(0.2)
        svg = self.options.out / name.replace(".png", ".svg")
        svg.parent.mkdir(parents=True, exist_ok=True)
        svg.write_text(swap_paths(screen_svg(self.app, self.options.font), self.tmp), encoding="utf-8")
        svg_to_png(svg, self.options.out / name, self.options.chrome)
        if not self.options.keep_svg:
            svg.unlink()
        self.taken.append(name)
        print(f"  {name}")

    async def part(self, name: str, widget: Any = None) -> None:
        """Save the screen as showcase part `name` if a wanted showcase uses it; `widget` (a popup's dialog, a
        panel) is the region its cut-out shows, None for the whole screen."""
        if name not in self.options.parts_wanted:
            return
        await self.pilot.pause(0.2)
        png = self.options.parts / f"{name.replace('/', '--')}.png"
        svg = png.with_suffix(".svg")
        svg.write_text(swap_paths(screen_svg(self.app, self.options.font), self.tmp), encoding="utf-8")
        svg_to_png(svg, png, self.options.chrome)
        svg.unlink()
        region = None if widget is None else tuple(widget.region if hasattr(widget, "region") else widget)
        self.options.parts_taken[name] = Part(png, region, tuple(self.app.size))
        print(f"  ({name})")

    async def open_tool(self, name: str) -> None:
        await self.pilot.pause()
        self.app.disclaimers_accepted.update(t.section for t in _tools().values())
        self.app.open_tool(name)
        await self.settle()

    async def pick_flavor(self, folder: str | None) -> None:
        """On the flavor picker: one game version (its folder) or All flavors (None)."""
        from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
        picker = self.app.screen
        assert isinstance(picker, FlavorScreen), type(picker).__name__
        picker.dismiss(ALL_FLAVORS if folder is None else next(f for f in picker.flavors if f.folder == folder))
        await self.settle()

    async def pick_all_accounts(self) -> None:
        from wowtools.ui.account_screen import AccountScreen
        if isinstance(self.app.screen, AccountScreen):
            await self.press("enter")


def _tools():
    from wowtools.tools import TOOLS
    return TOOLS


# The temp tree is made in WORK_DIR, a fixed folder whose path, on Linux and WSL, is as long as SHOWN_ROOT: every
# path the app shows reads as a Windows one (D:\Games\World of Warcraft\...), whether it went through to_stored
# (patched, so the layout is measured on the shown text) or str() (swapped in the SVG, cell for cell).
WORK_DIR = Path(tempfile.gettempdir()) / "wsh"
SHOWN_ROOT = "D:\\Games"


def shown_root(work: Path) -> str:
    """What the work folder is shown as: SHOWN_ROOT when the two are the same length (so swapping one for the
    other moves no cell), else the folder itself."""
    return SHOWN_ROOT if len(str(work)) == len(SHOWN_ROOT) else str(work)


def show_path(text: str, work: Path) -> str:
    if text == str(work) or text.startswith(str(work) + os.sep):
        return shown_root(work) + text[len(str(work)):].replace(os.sep, "\\")
    return text


def swap_paths(svg: str, work: Path) -> str:
    """Paths the app drew with str() (not to_stored): the work folder and the rest of that text run, its slashes
    turned to backslashes."""
    if shown_root(work) == str(work):
        return svg
    pattern = re.compile(re.escape(str(work)) + r"((?:[^<&]|&#160;)*)")
    return pattern.sub(lambda m: shown_root(work) + m.group(1).replace("/", "\\"), svg)


@contextmanager
def shown_paths(work: Path) -> Iterator[None]:
    """Patch `core.paths.to_stored` (show and store the work folder as shown_root) and `to_native` (the way back,
    so a stored path still opens: a journal's or a backup's) in every module that imported them."""
    import importlib
    import pkgutil

    import wowtools
    from wowtools.core import paths
    for module in pkgutil.walk_packages(wowtools.__path__, "wowtools."):
        importlib.import_module(module.name)
    real_stored, real_native = paths.to_stored, paths.to_native
    shown = shown_root(work)

    def to_stored(value, *, wsl=None):
        text = show_path(str(value), work)
        return text if text != str(value) else real_stored(value, wsl=wsl)

    def to_native(value, *, wsl=None):
        text = value.strip()
        if shown != str(work) and (text == shown or text.startswith(shown + "\\")):
            return Path(str(work) + text[len(shown):].replace("\\", os.sep))
        return real_native(value, wsl=wsl)

    swaps = {id(real_stored): to_stored, id(real_native): to_native}
    patched = [(m, name, value) for m in list(sys.modules.values())
               if getattr(m, "__name__", "").startswith("wowtools")
               for name, value in vars(m).items() if id(value) in swaps and value in (real_stored, real_native)]
    for module, name, value in patched:
        setattr(module, name, swaps[id(value)])
    try:
        yield
    finally:
        for module, name, value in patched:
            setattr(module, name, value)


@contextmanager
def hold_progress(when: Callable[[str, int, int], bool]) -> Iterator[tuple[threading.Event, threading.Event]]:
    """Hold the run's worker the first time it reports a stage `when(stage, current, total)` accepts, so the
    progress window can be captured mid-run: yields (reached, release). The worker reports from its own thread, so
    waiting there never blocks the UI."""
    from wowtools.ui import dialogs
    reached, release = threading.Event(), threading.Event()
    real_report, real_unit = dialogs.ProgressScreen.report, dialogs.ProgressScreen.report_unit

    def gate(stage: str, current: int, total: int) -> None:
        if not reached.is_set() and when(stage, current, total):
            reached.set()
            release.wait(60)

    def report(self, stage, current=0, total=0, detail=None):
        real_report(self, stage, current, total, detail)
        gate(stage, current, total)

    def report_unit(self, unit, stage, current=0, total=0, detail=None):
        real_unit(self, unit, stage, current, total, detail)
        gate(stage, current, total)

    dialogs.ProgressScreen.report, dialogs.ProgressScreen.report_unit = report, report_unit
    try:
        yield reached, release
    finally:
        release.set()
        dialogs.ProgressScreen.report, dialogs.ProgressScreen.report_unit = real_report, real_unit


async def wait_for(session: Session, event: threading.Event, what: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not event.is_set():
        if time.monotonic() > deadline:
            raise RuntimeError(f"timed out waiting for {what} on {type(session.app.screen).__name__}")
        await session.pilot.pause(0.05)
    await session.pilot.pause(0.6)  # the progress window draws on a timer


# --------------------------------------------------------------------------------------------------------------
# The flows: one walk through a tool each
# --------------------------------------------------------------------------------------------------------------
async def suite_flow(s: Session) -> None:
    await s.pilot.pause()
    await s.settle()
    await s.capture("suite/tool-menu.png")
    await s.press("s")
    await s.capture("suite/general-settings.png")


def past(stage: str, share: float = 0.5) -> Callable[[str, int, int], bool]:
    """A hold_progress test: `stage` reported with at least `share` of its total done."""
    return lambda st, current, total: st == stage and total > 0 and current >= share * total


async def wtf_cleaner_flow(s: Session) -> None:
    await s.open_tool("wtf-cleaner")
    await s.pick_flavor(None)
    await s.pick_all_accounts()
    await s.capture("wtf-cleaner/review.png")
    await s.part("wtf-cleaner/review")
    await s.part("wtf-cleaner/criteria", pane_to(s.app, "#btn-undo"))
    await s.press("w")
    await s.capture("wtf-cleaner/clean-confirm.png")
    await s.part("wtf-cleaner/confirm", popup(s.app))
    with hold_progress(past("snapshot", 0.8)) as (reached, release):
        await s.pilot.press("enter")
        await wait_for(s, reached, "the WTF backup")
        await s.capture("wtf-cleaner/clean-progress.png")
        await s.part("wtf-cleaner/progress", popup(s.app))
        release.set()
        await s.settle()
    await s.capture("wtf-cleaner/result.png")
    await s.part("wtf-cleaner/result", filled(s.app.screen.query_one("#result-summary"), most=16))


async def screenshot_organizer_flow(s: Session) -> None:
    await s.open_tool("screenshot-organizer")
    await s.pick_flavor(None)
    await s.capture("screenshot-organizer/review.png")
    await s.part("screenshot-organizer/review")
    await s.part("screenshot-organizer/where", pane_to(s.app, "#btn-undo"))
    await s.press("o")
    await s.capture("screenshot-organizer/organize-confirm.png")
    await s.part("screenshot-organizer/confirm", popup(s.app))
    with hold_progress(past("organize", 0.4)) as (reached, release):
        await s.pilot.press("enter")
        await wait_for(s, reached, "the filing")
        await s.capture("screenshot-organizer/organize-progress.png")
        await s.part("screenshot-organizer/progress", popup(s.app))
        release.set()
        await s.settle()
    await s.capture("screenshot-organizer/result.png")
    await s.part("screenshot-organizer/result", filled(s.app.screen.query_one("#result-summary")))


async def reveal(s: Session, tree, wanted: Callable[[Any], bool], depth: int = 4):
    """The first node of `tree` (breadth first, opening nodes down to `depth`) whose data `wanted` accepts; the
    cursor is moved to it."""
    level = [tree.root]
    for _ in range(depth + 1):
        following = []
        for node in level:
            if node.data is not None and wanted(node.data):
                tree.move_cursor(node)
                await s.settle()
                return node
            if node.allow_expand and not node.is_expanded:
                node.expand()
                await s.settle()
            following.extend(node.children)
        level = following
    raise RuntimeError("no such node in the tree")


def change_since_backup(root: Path) -> None:
    """After a backup: a new addon (a restore removes it) and newer settings (a restore loses them)."""
    retail = root / "_retail_"
    for name in ("Simulationcraft", "Narcissus", "Chattynator"):
        for index in range(RNG.randint(3, 30)):
            _write(retail / "Interface" / "AddOns" / name / f"part{index}.lua", "-- new", 0)
    for path in sorted((retail / "WTF" / "Account" / ACCOUNT / "SavedVariables").glob("*.lua"))[:14]:
        _write(path, path.read_bytes() + b"\r\n", 0)
    for path in sorted((retail / "Interface" / "AddOns" / "WeakAuras").rglob("*.lua")):
        _write(path, path.read_bytes() + b"\n", 0)


async def interface_backup_flow(s: Session) -> None:
    await s.open_tool("interface-backup")
    await s.pick_flavor(None)
    await s.press("b", "y")  # an earlier backup of every flavor
    await s.press("r")
    change_since_backup(s.root)
    await s.press("r")
    await s.press("b")
    with hold_progress(past("backup", 0.5)) as (reached, release):
        await s.pilot.press("enter")
        await wait_for(s, reached, "the zipping")
        await s.capture("interface-backup/backup-progress.png")
        await s.part("interface-backup/progress", popup(s.app))
        release.set()
        await s.settle()
    await s.capture("interface-backup/backup-result.png")
    await s.press("r")
    review = s.app.screen
    from textual.widgets import Tree
    tree = review.query_one("#flavors", Tree)
    oldest = min((i for i in review.backups if i.flavor_short == "retail"), key=lambda i: (i.stamp, i.n))
    await reveal(s, tree, lambda data: data[0] == "backup" and data[1] == oldest)
    await s.capture("interface-backup/review.png")
    await s.part("interface-backup/review")
    await s.press("e")
    await s.capture("interface-backup/restore-screen.png")
    await s.part("interface-backup/restore", filled(s.app.screen.query_one("#effects"), most=24))
    await s.press("o")
    await s.part("interface-backup/restore-confirm", popup(s.app))
    await s.press("y")
    await s.capture("interface-backup/restore-result.png")
    await s.press("z")
    await s.part("interface-backup/undo-confirm", popup(s.app))
    await s.press("y")
    await s.capture("interface-backup/undo-result.png")


async def ace3_flow(s: Session) -> None:
    await s.open_tool("ace3-profile-manager")
    await s.pick_flavor(None)
    await s.pick_all_accounts()
    await s.press("x")
    await s.capture("ace3-profile-manager/review.png")
    await s.part("ace3-profile-manager/review")
    await s.press("v", "x")
    await s.capture("ace3-profile-manager/review-by-character.png")
    from textual.widgets import Tree
    await s.part("ace3-profile-manager/by-character", filled(s.app.screen.query_one(Tree), most=22))
    await s.press("v", "c", "a", "p")
    await s.capture("ace3-profile-manager/assign-popup.png")
    await s.part("ace3-profile-manager/assign", popup(s.app))
    await s.press("escape", "o")
    await s.capture("ace3-profile-manager/leftovers-confirm.png")
    await s.part("ace3-profile-manager/leftovers", popup(s.app))
    await s.press("y", "w")
    await s.part("ace3-profile-manager/apply-confirm", popup(s.app))
    with hold_progress(past("snapshot", 0.6)) as (reached, release):
        await s.pilot.press("y")
        await wait_for(s, reached, "the WTF backup")
        await s.capture("ace3-profile-manager/apply-progress.png")
        release.set()
        await s.settle()
    await s.capture("ace3-profile-manager/apply-result.png")


def child(node, text: str):
    """The first child of `node` whose label shows `text`."""
    for kid in node.children:
        label = kid.label.plain if hasattr(kid.label, "plain") else str(kid.label)
        if text in label:
            return kid
    raise RuntimeError(f"no {text!r} under {node.label}")


async def sv_open(s: Session, review, node):
    """Open a Saved Variables Browser node (its children load on open) and return it as the tree has it now."""
    from wowtools.tools.sv_browser.review_screen import ident
    node.expand()
    await s.settle()
    return review._tree_nodes.get(ident(node.data), node)


async def sv_browser_flow(s: Session) -> None:
    from textual.widgets import Tree
    from wowtools.tools.sv_browser.popups import VALUE_CONTAINS
    await s.open_tool("sv-browser")
    await s.pick_flavor(None)
    review = s.app.screen
    tree = review.query_one("#browse", Tree)
    node = child(child(child(tree.root, "Retail"), ACCOUNT), "Account-wide")
    for name in ("ElvUI.lua", "ElvDB", "profiles", "Default", "general"):
        node = await sv_open(s, review, child(node, name))
    unit = await sv_open(s, review, child(node.parent, "unitframe"))
    tree.get_node_at_line(0)
    tree.move_cursor(child(node, "fontSize"))
    tree.focus()
    await s.settle()
    await s.capture("sv-browser/review.png")
    await s.part("sv-browser/review")
    await s.press("e")
    s.app.screen.query_one("#value-text").value = "13"
    await s.settle()
    await s.capture("sv-browser/edit-value.png")
    await s.part("sv-browser/edit", popup(s.app))
    await s.press("enter")
    del unit
    tree.focus()
    await s.press("S")
    search = s.app.screen
    search.query_one("#search-value").value = FONT
    search.query_one("#value-mode").value = VALUE_CONTAINS
    await s.settle()
    await s.capture("sv-browser/search.png")
    await s.part("sv-browser/search", popup(s.app))
    await s.pilot.click("#find")
    await s.settle()
    await s.capture("sv-browser/search-results.png")
    await s.part("sv-browser/results", filled(review.query_one("#browse", Tree), most=22))
    review.query_one("#browse", Tree).focus()
    await s.press("e")
    s.app.screen.query_one("#value-text").value = "Expressway"
    await s.settle()
    await s.capture("sv-browser/bulk-edit.png")
    await s.part("sv-browser/bulk", popup(s.app))
    await s.press("enter")
    await s.press("w")
    await s.capture("sv-browser/apply-confirm.png")
    await s.part("sv-browser/apply", popup(s.app))
    with hold_progress(past("snapshot", 0.6)) as (reached, release):
        await s.pilot.press("y")
        await wait_for(s, reached, "the WTF backup")
        await s.capture("sv-browser/apply-progress.png")
        release.set()
        await s.settle()
    await s.capture("sv-browser/apply-result.png")


def walk(node) -> Iterator[Any]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(list(current.children)))


def character_node(tree, name: str):
    from wowtools.ui.character_tree import CharacterNode
    return next(n for n in walk(tree.root) if isinstance(n.data, CharacterNode) and n.data.kind == "character"
                and n.data.character.name == name)


async def config_copier_flow(s: Session) -> None:
    from textual.widgets import Tree
    from wowtools.tools.config_copier.review_screen import PairNode
    await s.open_tool("config-copier")
    await s.pick_flavor("_retail_")
    sources = s.app.screen.query_one("#sources", Tree)
    sources.focus()
    sources.move_cursor(character_node(sources, "Ellandra"))
    await s.settle()
    await s.capture("config-copier/source.png")
    await s.part("config-copier/source", filled(sources, most=20))
    await s.press("enter")
    targets = s.app.screen.query_one("#targets", Tree)
    targets.focus()
    await s.press("a", "x")
    thrungar = character_node(targets, "Thrungar")
    targets.move_cursor(next(n for n in thrungar.children
                             if isinstance(n.data, PairNode) and n.data.plan.name == "macros-cache.txt"))
    await s.settle()
    await s.capture("config-copier/review.png")
    await s.part("config-copier/review")
    await s.press("d")
    await s.capture("config-copier/diff.png")
    await s.part("config-copier/diff", filled(s.app.screen.query_one("#diff-scroll"), most=26))
    await s.press("v")
    await s.capture("config-copier/diff-inline.png")
    await s.press("v", "escape")  # back to side by side for the next diff, and to the review
    await s.press("w")
    await s.part("config-copier/write", popup(s.app))
    await s.press("y")
    await s.part("config-copier/result", filled(s.app.screen.query_one("#result-summary")))


async def macro_editor_flow(s: Session) -> None:
    from textual.widgets import Tree
    from wowtools.tools.macro_editor.review_screen import MacroNode
    await s.open_tool("macro-editor")
    await s.pick_flavor("_retail_")
    tree = s.app.screen.query_one("#macros", Tree)
    tree.focus()
    await s.press("x")
    node = next(n for n in walk(tree.root) if isinstance(n.data, MacroNode) and n.data.macro.name == "Heal Focus")
    tree.move_cursor(node)
    await s.settle()
    await s.capture("macro-editor/browse.png")
    await s.part("macro-editor/browse")
    await s.press("e")
    body = s.app.screen.query_one("#macro-body")
    body.focus()
    line = body.text.split("\n")[1]
    body.move_cursor((1, line.index("help") + 2))
    await s.settle()
    await s.capture("macro-editor/edit.png")
    edit_body, macro_body = s.app.screen.query_one("#edit-body").region, s.app.screen.query_one("#macro-body")
    rows = macro_body.region.y - edit_body.y + macro_body.virtual_size.height + 8  # the lines and some room after
    await s.part("macro-editor/edit", (edit_body.x, edit_body.y, edit_body.width, min(rows, edit_body.height)))
    await s.press("ctrl+b")
    await s.part("macro-editor/builder", popup(s.app))
    await s.press("escape", "ctrl+o")
    await s.part("macro-editor/optimize", popup(s.app))
    await s.press("escape", "ctrl+t")
    await s.part("macro-editor/template", popup(s.app))
    await s.press("escape")


async def config_editor_flow(s: Session) -> None:
    from textual.widgets import Tree
    from wowtools.tools.config_editor.review_screen import CvarNode, FileNode
    await s.open_tool("config-editor")
    await s.pick_flavor("_retail_")
    tree = s.app.screen.query_one("#cvars", Tree)
    tree.focus()
    character_node(tree, "Ellandra").expand()
    await s.settle()

    def cvar(name: str):  # looked up each time: the tree is rebuilt as edits are staged
        return next(n for n in walk(character_node(tree, "Ellandra"))
                    if isinstance(n.data, CvarNode) and n.data.row.name == name)
    tree.move_cursor(cvar("nameplateShowFriends"))
    await s.press("space")  # a 0/1 CVar: Space stages the other value
    tree.move_cursor(cvar("cameraDistanceMaxZoomFactor"))
    await s.settle()
    await s.capture("config-editor/browse.png")
    await s.part("config-editor/browse")
    await s.part("config-editor/help", s.app.screen.query_one("#side-help-text"))
    tree.move_cursor(next(n for n in walk(tree.root) if isinstance(n.data, FileNode) and n.data.target.label == ACCOUNT))
    await s.press("m")
    await s.capture("config-editor/recommend.png")
    await s.part("config-editor/recommend", popup(s.app))
    await s.press("escape")
    for name in ("Ellandra", "Thrungar", "Vexis"):  # tick three characters: an edit acts on every ticked file
        tree.move_cursor(character_node(tree, name))
        await s.press("space")
    tree.move_cursor(cvar("cameraDistanceMaxZoomFactor"))
    await s.press("e")
    await s.part("config-editor/set-many", popup(s.app))
    await s.press("enter")  # staged on the three: Apply below lists them
    await s.press("N")
    await s.pilot.press(*"nameplate")
    await s.settle()
    await s.part("config-editor/add", popup(s.app))
    await s.press("escape")
    await s.press("w")
    await s.part("config-editor/apply", popup(s.app))
    await s.press("escape")


def popup(app) -> Any:
    """The dialog of the popup on top: the first child of the modal screen that takes room."""
    return next(w for w in app.screen.children if w.region.area)


def pane_to(app, last: str) -> tuple[int, int, int, int]:
    """The left pane (#filters) from its top down to the bottom of widget `last` (its buttons, say)."""
    pane, end = app.screen.query_one("#filters").region, app.screen.query_one(last).region
    return pane.x, pane.y, pane.width, end.bottom - pane.y


def filled(widget, extra: int = 2, most: int | None = None) -> tuple[int, int, int, int]:
    """A widget cut to the rows and columns its content fills (a tree or a table smaller than its box), at most
    `most` rows."""
    box = widget.region
    rows = min(box.height, widget.virtual_size.height + extra, most or box.height)
    return box.x, box.y, min(box.width, widget.virtual_size.width + extra), rows



Flow = Callable[[Session], Awaitable[None]]


@dataclass(frozen=True)
class Shot:
    file: str     # under docs/assets/screenshots/
    flow: Flow
    caption: str  # what it shows (the alt text the docs use)


SHOTS: tuple[Shot, ...] = (
    Shot("suite/tool-menu.png", suite_flow, "The tool menu"),
    Shot("suite/general-settings.png", suite_flow, "The general settings screen"),
    Shot("wtf-cleaner/review.png", wtf_cleaner_flow, "The WTF Cleaner review screen"),
    Shot("wtf-cleaner/clean-confirm.png", wtf_cleaner_flow, "The clean confirmation"),
    Shot("wtf-cleaner/clean-progress.png", wtf_cleaner_flow, "A clean in progress"),
    Shot("wtf-cleaner/result.png", wtf_cleaner_flow, "The results of a clean"),
    Shot("screenshot-organizer/review.png", screenshot_organizer_flow, "The Screenshot Organizer review screen"),
    Shot("screenshot-organizer/organize-confirm.png", screenshot_organizer_flow, "The Organize confirmation"),
    Shot("screenshot-organizer/organize-progress.png", screenshot_organizer_flow, "Organizing in progress"),
    Shot("screenshot-organizer/result.png", screenshot_organizer_flow, "The results of a run"),
    Shot("interface-backup/backup-progress.png", interface_backup_flow, "A backup in progress"),
    Shot("interface-backup/backup-result.png", interface_backup_flow, "The results of a backup"),
    Shot("interface-backup/review.png", interface_backup_flow, "The Interface Backup review screen"),
    Shot("interface-backup/restore-screen.png", interface_backup_flow, "The restore screen"),
    Shot("interface-backup/restore-result.png", interface_backup_flow, "The results of a restore"),
    Shot("interface-backup/undo-result.png", interface_backup_flow, "The results of an undo"),
    Shot("ace3-profile-manager/review.png", ace3_flow, "The Ace3 Profile Manager review screen, By addon"),
    Shot("ace3-profile-manager/review-by-character.png", ace3_flow, "The review screen in the By character view"),
    Shot("ace3-profile-manager/assign-popup.png", ace3_flow, "The Assign a profile popup"),
    Shot("ace3-profile-manager/leftovers-confirm.png", ace3_flow, "The Remove leftover characters popup"),
    Shot("ace3-profile-manager/apply-progress.png", ace3_flow, "The Applying the changes progress window"),
    Shot("ace3-profile-manager/apply-result.png", ace3_flow, "The Apply results"),
    Shot("sv-browser/review.png", sv_browser_flow, "The Saved Variables Browser review screen in the Browse view"),
    Shot("sv-browser/edit-value.png", sv_browser_flow, "The Edit value popup"),
    Shot("sv-browser/search.png", sv_browser_flow, "The Search popup"),
    Shot("sv-browser/search-results.png", sv_browser_flow, "The Results view"),
    Shot("sv-browser/bulk-edit.png", sv_browser_flow, "The bulk edit popup"),
    Shot("sv-browser/apply-confirm.png", sv_browser_flow, "The Apply the pending changes? confirm"),
    Shot("sv-browser/apply-progress.png", sv_browser_flow, "The Applying the changes progress window"),
    Shot("sv-browser/apply-result.png", sv_browser_flow, "The Apply results"),
    Shot("config-copier/source.png", config_copier_flow, "Choosing the source"),
    Shot("config-copier/review.png", config_copier_flow, "The Config Copier review"),
    Shot("config-copier/diff.png", config_copier_flow, "The diff of a replaced file, side by side"),
    Shot("config-copier/diff-inline.png", config_copier_flow, "The same diff inline (v)"),
    Shot("macro-editor/browse.png", macro_editor_flow, "The Macro Editor"),
    Shot("macro-editor/edit.png", macro_editor_flow, "The edit screen"),
    Shot("config-editor/browse.png", config_editor_flow, "The Config Editor"),
    Shot("config-editor/recommend.png", config_editor_flow, "Recommend… for an account's config"),
)


# --------------------------------------------------------------------------------------------------------------
# Showcases: one image per tool for the README, a full screen with readable cut-outs of its popups and panels
# --------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Showcase:
    file: str                         # under docs/assets/screenshots/
    flow: Flow
    title: str
    subtitle: str
    hero: tuple[str, str]             # (part, caption): the full screen on top
    cutouts: tuple[tuple[str, str], ...]  # (part, caption): cut to their popup or panel, in rows below

    @property
    def parts(self) -> list[str]:
        return [self.hero[0], *(part for part, _ in self.cutouts)]


SHOWCASES: tuple[Showcase, ...] = (
    Showcase("wtf-cleaner/showcase.png", wtf_cleaner_flow, "WTF Cleaner",
             "Find and remove the settings that addons you no longer use left in your WTF folder",
             ("wtf-cleaner/review", "Every addon the rules suggest, with why, how many files, their size and age"),
             (("wtf-cleaner/criteria", "Five rules, each with its colour, and a maximum age you set"),
              ("wtf-cleaner/confirm", "Clean: every file zipped and the whole WTF folder backed up first"),
              ("wtf-cleaner/progress", "Progress for every step"),
              ("wtf-cleaner/result", "What it did, with Undo for the last clean"))),
    Showcase("screenshot-organizer/showcase.png", screenshot_organizer_flow, "Screenshot Organizer",
             "File your screenshots into year, month and day folders, in place or into an archive",
             ("screenshot-organizer/review", "Every screenshot by game version and day, before anything moves"),
             (("screenshot-organizer/where", "Where they go, and whether they are moved or copied"),
              ("screenshot-organizer/confirm", "Organize: never overwrites a file, and can be undone"),
              ("screenshot-organizer/progress", "Progress as it files"),
              ("screenshot-organizer/result", "What it moved, with Undo for the last run"))),
    Showcase("interface-backup/showcase.png", interface_backup_flow, "Interface Backup",
             "Zip a game version's Interface and WTF folders, and restore either one exactly as it was",
             ("interface-backup/review", "Every game version with its folders and its backups"),
             (("interface-backup/progress", "Back up: the folders zipped, with progress"),
              ("interface-backup/restore", "Restore: what it removes and which newer changes are lost, before anything changes"),
              ("interface-backup/restore-confirm", "A safety backup is taken before every restore"),
              ("interface-backup/undo-confirm", "Undo puts the folders back as they were"))),
    Showcase("ace3-profile-manager/showcase.png", ace3_flow, "Ace3 Profile Manager",
             "See which characters use which Ace3 profile, and delete, rename, copy and reassign them",
             ("ace3-profile-manager/review", "Every Ace3 addon's profiles and the characters that use each"),
             (("ace3-profile-manager/by-character", "Or by character: each one's profile in every addon"),
              ("ace3-profile-manager/assign", "Assign a profile to many characters at once"),
              ("ace3-profile-manager/leftovers", "Clear out characters that no longer exist"),
              ("ace3-profile-manager/apply-confirm", "Apply: every change listed, backed up first, and Undo after"))),
    Showcase("sv-browser/showcase.png", sv_browser_flow, "Saved Variables Browser",
             "Open any addon's SavedVariables as a tree you can edit, and change every match in one go",
             ("sv-browser/review", "Every SavedVariables file by game version, account and character, as a tree"),
             (("sv-browser/edit", "Edit any value"),
              ("sv-browser/search", "Search keys and values across every file"),
              ("sv-browser/results", "Every match, ready to change"),
              ("sv-browser/bulk", "Change every match at once"),
              ("sv-browser/apply", "Apply: every change listed, backed up first, and Undo after"))),
    Showcase("config-copier/showcase.png", config_copier_flow, "Config Copier",
             "Copy one character's macros, enabled addons, chat windows, CVars and layout to other characters",
             ("config-copier/review", "What each target character gets: every file new, replaced, merged or unchanged"),
             (("config-copier/source", "Pick the character to copy from"),
              ("config-copier/diff", "A side-by-side diff of every file it replaces"),
              ("config-copier/write", "Write: backed up first, with a dry run and Undo"),
              ("config-copier/result", "What it wrote"))),
    Showcase("macro-editor/showcase.png", macro_editor_flow, "Macro Editor",
             "Browse, edit, copy and paste macros across characters, accounts and game versions",
             ("macro-editor/browse", "Every account's and character's macros in every game version"),
             (("macro-editor/edit", "An editor that suggests and explains commands and conditionals as you type"),
              ("macro-editor/builder", "Build a conditional without remembering the syntax"),
              ("macro-editor/optimize", "Shorten a macro with the optimizer"),
              ("macro-editor/template", "Start from a template for a common macro"))),
    Showcase("config-editor/showcase.png", config_editor_flow, "Config Editor",
             "See and change every CVar in every game version, with help, recommendations, a dry run and Undo",
             ("config-editor/browse", ("Every CVar in Config.wtf and each account's and character's config, with "
                                       "its value, default, state and category")),
             (("config-editor/help", "Help for each CVar: what it does, its default and where the game keeps it"),
              ("config-editor/recommend", "Sourced recommendations: tick the ones you want"),
              ("config-editor/set-many", "Set a CVar on every ticked character at once"),
              ("config-editor/add", "Add any CVar the game knows, with its default and what it does"),
              ("config-editor/apply", "Apply: every file it changes, backed up first, and Undo after"))),
)

SHOWCASE_WIDTH = 1920
SHOWCASE_PAD = 48     # around the edge
SHOWCASE_GAP = 28     # between cut-outs
CAPTION_HEIGHT = 58   # two lines of caption under each picture
HEADER_HEIGHT = 112   # the title and the subtitle
CUTOUT_SCALE = 1.0    # cut-outs are drawn at the screen's own size: their text matches the hero's or is larger


def showcase_page(show: Showcase, parts: dict[str, Part]) -> tuple[str, int]:
    """The showcase as an HTML page, and its height: the hero across the top, then the cut-outs in justified rows
    (each row one height, filling the width), each picture over its caption."""
    inner = SHOWCASE_WIDTH - 2 * SHOWCASE_PAD

    def picture(part: Part, width: float, height: float, region: tuple[float, float, float, float]) -> str:
        x, y, w, _ = region
        scale = width / w
        return (f"<div class='pic' style='width:{width:.1f}px;height:{height:.1f}px'>"
                f"<img src='{part.png.as_uri()}' style='width:{PNG_SIZE[0] * scale:.1f}px;"
                f"left:{-x * scale:.1f}px;top:{-y * scale:.1f}px'></div>")

    def pixels(part: Part) -> tuple[float, float, float, float]:
        if part.region is None:
            return 0.0, 0.0, float(PNG_SIZE[0]), float(PNG_SIZE[1])
        cell_w, cell_h = PNG_SIZE[0] / part.cells[0], PNG_SIZE[1] / part.cells[1]
        x, y, w, h = part.region
        return x * cell_w, y * cell_h, w * cell_w, h * cell_h

    hero_part, hero_caption = parts[show.hero[0]], show.hero[1]
    hero_height = inner * PNG_SIZE[1] / PNG_SIZE[0]
    body = [(f"<figure>{picture(hero_part, inner, hero_height, pixels(hero_part))}"
             f"<figcaption>{hero_caption}</figcaption></figure>")]
    height = HEADER_HEIGHT + hero_height + CAPTION_HEIGHT
    # Every cut-out at one scale, so their text is one size, packed in order into rows that fit the width; only
    # one wider than the page on its own is drawn smaller.
    rows: list[list[tuple[str, str, tuple[float, float, float, float], float]]] = [[]]
    for name, caption in show.cutouts:
        box = pixels(parts[name])
        scale = min(CUTOUT_SCALE, inner / box[2])
        used = sum(b[2] * sc for *_, b, sc in rows[-1]) + SHOWCASE_GAP * len(rows[-1])
        if rows[-1] and used + box[2] * scale > inner:
            rows.append([])
        rows[-1].append((name, caption, box, scale))
    for row in rows:
        figures = "".join(f"<figure>{picture(parts[name], box[2] * sc, box[3] * sc, box)}"
                          f"<figcaption style='width:{box[2] * sc:.1f}px'>{caption}</figcaption></figure>"
                          for name, caption, box, sc in row)
        body.append(f"<div class='row'>{figures}</div>")
        height += SHOWCASE_GAP + max(box[3] * sc for *_, box, sc in row) + CAPTION_HEIGHT
    height = int(height + SHOWCASE_PAD)
    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body {{ margin:0; background:{BACKGROUND}; color:{FOREGROUND}; font-family:"DejaVu Sans",sans-serif;
       width:{SHOWCASE_WIDTH}px; height:{height}px; overflow:hidden; }}
main {{ padding:{SHOWCASE_PAD // 2}px {SHOWCASE_PAD}px {SHOWCASE_PAD}px; }}
h1 {{ margin:0; color:{TITLE_GOLD}; font-size:40px; height:52px; }}
p.sub {{ margin:0 0 {HEADER_HEIGHT - 52 - 32 - SHOWCASE_PAD // 2}px; font-size:22px; height:32px; opacity:.85; }}
figure {{ margin:0; }}
.pic {{ position:relative; overflow:hidden; border:1px solid #2B4C73; border-radius:6px; box-sizing:border-box; }}
.pic img {{ position:absolute; max-width:none; }}
figcaption {{ font-size:19px; line-height:24px; height:{CAPTION_HEIGHT - 10}px; padding-top:10px; opacity:.85; }}
.row {{ display:flex; gap:{SHOWCASE_GAP}px; justify-content:center; align-items:flex-start;
        margin-top:{SHOWCASE_GAP}px; }}
</style></head><body><main><h1>{show.title}</h1><p class="sub">{show.subtitle}</p>{"".join(body)}</main></body></html>"""
    return page, height


def build_showcase(show: Showcase, options: Options) -> None:
    page, height = showcase_page(show, options.parts_taken)
    html = options.parts / f"{show.file.replace('/', '--')}.html"
    html.write_text(page, encoding="utf-8")
    png = options.out / show.file
    png.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([options.chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        "--force-device-scale-factor=1", "--allow-file-access-from-files", f"--user-data-dir={profile}",
                        f"--window-size={SHOWCASE_WIDTH},{height}", f"--screenshot={png}", html.as_uri()],
                       check=True, capture_output=True, timeout=120)
    print(f"  {show.file}")


# --------------------------------------------------------------------------------------------------------------
async def run_flow(flow: Flow, options: Options) -> list[str]:
    from wowtools.ui import dialogs
    dialogs.CONFIRM_GUARD = 0.0  # a confirm takes Enter at once
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True)
    try:
        session = Session(options, WORK_DIR)
        session.app = session.make_app()
        with shown_paths(WORK_DIR):
            async with session.app.run_test(size=options.size) as pilot:
                session.pilot = pilot
                asyncio.get_running_loop().set_debug(False)
                await flow(session)
        return session.taken
    finally:
        shutil.rmtree(WORK_DIR, ignore_errors=True)


def parse_size(text: str) -> tuple[int, int]:
    cols, _, rows = text.lower().partition("x")
    return int(cols), int(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", nargs="+", metavar="TOOL_OR_FILE",
                        help="a folder (tool) such as config-copier, or a file such as config-copier/diff.png")
    parser.add_argument("--size", type=parse_size, default=DEFAULT_SIZE, metavar="COLSxROWS",
                        help=f"terminal size in cells (default {DEFAULT_SIZE[0]}x{DEFAULT_SIZE[1]})")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="where the PNGs go (default docs/assets/screenshots)")
    parser.add_argument("--keep-svg", action="store_true", help="keep each SVG beside its PNG")
    parser.add_argument("--font", default=DEFAULT_FONT, help=f"monospace font family (default {DEFAULT_FONT})")
    parser.add_argument("--chrome", help="path to Chrome or Chromium (default: found on PATH)")
    parser.add_argument("--list", action="store_true", help="list the screenshots and exit")
    args = parser.parse_args(argv)
    if args.list:
        for shot in SHOTS:
            print(f"{shot.file:48} {shot.caption}")
        for show in SHOWCASES:
            print(f"{show.file:48} Showcase: {show.title}")
        return 0
    only = args.only or []

    def asked(file: str) -> bool:
        return not only or any(file == o or file.split("/")[0] == o.strip("/") for o in only)
    wanted = {shot.file for shot in SHOTS if asked(shot.file)}
    shows = [show for show in SHOWCASES if asked(show.file)]
    if not wanted and not shows:
        parser.error(f"nothing matches {' '.join(only)} (see --list)")
    with tempfile.TemporaryDirectory() as parts:
        options = Options(args.size, args.out, args.keep_svg, args.font, find_chrome(args.chrome), wanted,
                          Path(parts), {part for show in shows for part in show.parts})
        flows: list[Flow] = []
        for flow in [shot.flow for shot in SHOTS if shot.file in wanted] + [show.flow for show in shows]:
            if flow not in flows:
                flows.append(flow)
        taken: list[str] = []
        for flow in flows:
            print(f"{flow.__name__}:")
            taken += asyncio.run(run_flow(flow, options))
        if shows:
            print("showcases:")
        for show in shows:
            lost = [part for part in show.parts if part not in options.parts_taken]
            if lost:
                print(f"Showcase {show.file} left out: no {', '.join(lost)}", file=sys.stderr)
                continue
            build_showcase(show, options)
            taken.append(show.file)
    wanted |= {show.file for show in shows}
    missing = sorted(wanted - set(taken))
    print(f"{len(taken)} screenshots in {options.out}")
    if missing:
        print("Not taken: " + ", ".join(missing), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
