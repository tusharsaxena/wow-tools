"""Saved Variables Browser skeleton (spec D1, §4, §6, §7): its registry entry, events, settings, help and the
build_sv_tree fixture."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import SVB_FONT, build_sv_tree
from wowtools.core.config import Config
from wowtools.core.events import TOOL_REGISTRIES
from wowtools.core.install import WowInstall
from wowtools.core.luasv import LuaParseError, parse
from wowtools.core.sv_events import sv_events
from wowtools.core.svfiles import walk_sv_files
from wowtools.tools import TOOLS
from wowtools.tools.sv_browser import settings as s
from wowtools.tools.sv_browser.events import EVENTS, SV_TOOL, TOOL_NAME
from wowtools.tools.sv_browser.help import GUIDE_URL, HELP
from wowtools.ui.tool_flow import ToolFlow


class RegistryTest(unittest.TestCase):
    def test_entry_is_last_and_named_per_d1(self):
        tool = list(TOOLS.values())[-1]
        self.assertEqual((tool.name, tool.title, tool.module, tool.section),
                         ("sv-browser", "Saved Variables Browser", "wowtools.tools.sv_browser.app", "sv_browser"))
        self.assertEqual(tool.description, "Browse and edit every SavedVariables file, with bulk find and replace.")
        flow = tool.flow()
        self.assertTrue(issubclass(flow, ToolFlow))
        self.assertEqual(flow.__name__, "SvBrowserFlow")
        self.assertEqual(flow.SECTION, "sv_browser")
        self.assertEqual(tool.help(), HELP)


class EventsTest(unittest.TestCase):
    def test_tool_events_and_the_shared_pipeline_under_svb(self):
        self.assertEqual(TOOL_NAME, "sv-browser")
        self.assertEqual((SV_TOOL.name, SV_TOOL.prefix), ("sv-browser", "svb"))
        self.assertEqual(TOOL_REGISTRIES[TOOL_NAME], EVENTS)
        levels = {name: spec.level for name, spec in EVENTS.items()}
        own = {"svb.started": "info", "svb.disclaimer_accepted": "info", "svb.disclaimer_declined": "info",
               "svb.scan_completed": "info", "svb.file_unreadable": "warning", "svb.search_started": "info",
               "svb.search_completed": "info", "svb.staged": "debug", "svb.unstaged": "debug"}
        for name, level in own.items():
            self.assertEqual(levels.get(name), level, name)
        for name, spec in sv_events("svb").items():
            self.assertEqual(EVENTS.get(name), spec, name)
        self.assertTrue(all(name.startswith("svb.") for name in EVENTS))
        self.assertEqual(SV_TOOL.journals.pruned_event, "svb.journal_pruned")


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.cfg = Config(self.tmp / "sv-browser.cfg")

    def test_defaults_and_round_trip(self):
        self.assertEqual(s.SECTION, "sv_browser")
        self.assertEqual(s.load_settings(self.cfg), s.SvBrowserSettings())
        saved = s.SvBrowserSettings(backup_dir=self.tmp / "out", last_flavor_choice="")
        s.save_settings(self.cfg, saved)
        self.assertEqual(s.load_settings(Config(self.cfg.path).load()), saved)
        saved = s.SvBrowserSettings(backup_dir=None, last_flavor_choice="_retail_")
        s.save_settings(self.cfg, saved)
        self.assertEqual(s.load_settings(Config(self.cfg.path).load()), saved)

    def test_retention_is_global_and_stray_keys_go_on_save(self):
        for key in ("keep_backups", "keep_journals", "keep_snapshots"):
            self.cfg.set(s.SECTION, key, "3", log=False)
        loaded = s.load_settings(self.cfg)
        self.assertFalse(any(hasattr(loaded, k) for k in ("keep_backups", "keep_journals", "keep_snapshots")))
        s.save_settings(self.cfg, loaded)
        again = Config(self.cfg.path).load()
        for key in ("keep_backups", "keep_journals", "keep_snapshots"):
            self.assertIsNone(again.get(s.SECTION, key), key)

    def test_root_is_the_backup_folder_or_the_wow_folder(self):
        wow = self.tmp / "World of Warcraft"
        self.assertEqual(s.resolve_root(s.SvBrowserSettings(), wow), wow / "wow-tools" / "sv-browser")
        self.assertEqual(s.resolve_root(s.SvBrowserSettings(backup_dir=self.tmp / "b"), wow),
                         self.tmp / "b" / "sv-browser")
        self.assertIsNone(s.resolve_root(s.SvBrowserSettings(), None))


class HelpTest(unittest.TestCase):
    def test_help_links_the_guide_and_warns(self):
        self.assertEqual(GUIDE_URL, "https://github.com/tusharsaxena/wow-tools/blob/master/docs/sv-browser.md")
        self.assertIn(GUIDE_URL, HELP)
        self.assertIn("USE AT YOUR OWN RISK", HELP)


class FixtureTest(unittest.TestCase):
    """build_sv_tree (spec §7): what later tasks rely on."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = build_sv_tree(Path(tmp.name) / "World of Warcraft")
        self.install = WowInstall(self.root)

    def files(self) -> dict[str, list[tuple[str, str | None, Path]]]:
        found: dict[str, list[tuple[str, str | None, Path]]] = {}
        for flavor in self.install.flavors():
            for acct, char, path in walk_sv_files(flavor):
                found.setdefault(flavor.folder, []).append((acct.name, char.name if char else None, path))
        return found

    def test_two_flavors_two_accounts_account_wide_and_per_character(self):
        found = self.files()
        self.assertEqual(sorted(found), ["_classic_era_", "_retail_"])
        retail = found["_retail_"]
        self.assertEqual({a for a, _, _ in retail}, {"ACCT1", "ACCT2"})
        self.assertTrue(any(c is None for _, c, _ in retail))
        self.assertTrue(any(c is not None for _, c, _ in retail))
        self.assertTrue(any(c is not None for _, c, _ in found["_classic_era_"]))
        names = {p.name for _, _, p in retail}
        self.assertIn("Blizzard_Console.lua", names)  # D4: Blizzard_* files are listed
        self.assertTrue((self.root / "_retail_/WTF/Account/ACCT1/SavedVariables/ElvUI.lua.bak").is_file())
        self.assertNotIn("ElvUI.lua.bak", names)

    def test_contents_cover_the_cases_later_tasks_need(self):
        parsed, broken = {}, []
        for flavor, entries in self.files().items():
            for _, _, path in entries:
                data = path.read_bytes()
                self.assertIn(b"\r\n", data)  # CRLF, as WoW writes
                try:
                    parsed[(flavor, path)] = (data, parse(data))
                except LuaParseError:
                    broken.append(path.name)
        self.assertEqual(broken, ["Broken.lua"])
        texts = b"".join(data for data, _ in parsed.values())
        for needle in (b'["Font"]', b'["font"]', b'["barFont"]', b'[1] = ', b'[true] = ', b'[false] = ',
                       b"nil, -- [2]", b"\\\"", b"\\\\", b"\\n", b"\\226", b"0.6000000000000001", b"= nil"):
            self.assertIn(needle, texts, needle)
        with_font = {(flavor, path) for (flavor, path), (data, _) in parsed.items()
                     if SVB_FONT.encode() in data}
        self.assertGreaterEqual(len(with_font), 4)
        self.assertEqual({flavor for flavor, _ in with_font}, {"_retail_", "_classic_era_"})
