"""Ace3 Profile Manager settings: [ace_profiles] in config/ace-profiles.cfg (spec §11)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wowtools.core.config import Config
from wowtools.core.events import TOOL_REGISTRIES
from wowtools.tools.ace_profiles import settings as s
from wowtools.tools.ace_profiles.events import TOOL_NAME


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.cfg = Config(self.tmp / "ace-profiles.cfg")

    def test_defaults(self):
        loaded = s.load_settings(self.cfg)
        self.assertEqual(loaded, s.ProfileSettings())
        self.assertEqual(loaded.blacklist, [])

    def test_round_trip(self):
        saved = s.ProfileSettings(backup_dir=self.tmp / "out", blacklist=["ElvUI", "Questie"],
                                  last_flavor_choice="", last_account="ACCT1")
        s.save_settings(self.cfg, saved)
        self.assertEqual(s.load_settings(Config(self.tmp / "ace-profiles.cfg").load()), saved)

    def test_retention_is_global_and_stale_keys_go_on_save(self):
        """Feedback round 1: retention lives in [general]; the old per-tool keys are ignored, then removed."""
        for key, value in (("keep_backups", "3"), ("keep_journals", "2"), ("keep_snapshots", "2")):
            self.cfg.set(s.SECTION, key, value, log=False)
        loaded = s.load_settings(self.cfg)
        for name in ("keep_backups", "keep_journals", "keep_snapshots"):
            self.assertFalse(hasattr(loaded, name), name)
        s.save_settings(self.cfg, loaded)
        again = Config(self.cfg.path).load()
        for key in ("keep_backups", "keep_journals", "keep_snapshots"):
            self.assertIsNone(again.get(s.SECTION, key), key)

    def test_blacklist_parsing(self):
        self.assertEqual(s.parse_blacklist(" ElvUI, questie\nQuestie ,, Bartender4 "), ["Bartender4", "ElvUI", "questie"])
        self.assertEqual(s.format_blacklist(["ElvUI", "Questie"]), "ElvUI, Questie")
        self.assertTrue(s.is_blacklisted(["ElvUI"], "elvui"))
        self.assertFalse(s.is_blacklisted(["ElvUI"], "ElvUI_Options"))

    def test_root_and_journal_dir(self):
        wow = self.tmp / "World of Warcraft"
        self.assertEqual(s.resolve_root(s.ProfileSettings(), wow), wow / "wow-tools" / "ace-profiles")
        self.assertEqual(s.resolve_root(s.ProfileSettings(backup_dir=self.tmp / "b"), wow),
                         self.tmp / "b" / "ace-profiles")
        self.assertIsNone(s.resolve_root(s.ProfileSettings(), None))
        self.assertEqual(s.resolve_journal_dir(wow), wow / "wow-tools" / "ace-profiles" / "journal")

    def test_events_registered_with_prefix(self):
        self.assertIn(TOOL_NAME, TOOL_REGISTRIES)
        self.assertTrue(all(name.startswith("ace.") for name in TOOL_REGISTRIES[TOOL_NAME]))
