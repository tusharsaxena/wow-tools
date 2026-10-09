"""Ace3 Profile Manager settings: [ace3_profile_manager] in config/ace3-profile-manager.cfg (spec §11)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wowtools.core import blacklist as bl
from wowtools.core.config import Config
from wowtools.core.events import TOOL_REGISTRIES
from wowtools.tools.ace3_profile_manager import settings as s
from wowtools.tools.ace3_profile_manager.events import TOOL_NAME
from wowtools.tools.ace3_profile_manager.journal import resolve_journal_dir


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.cfg = Config(self.tmp / "ace3-profile-manager.cfg")

    def test_defaults(self):
        loaded = s.load_settings(self.cfg)
        self.assertEqual(loaded, s.ProfileSettings())
        self.assertEqual(loaded.blacklist, [])

    def test_round_trip(self):
        saved = s.ProfileSettings(backup_dir=self.tmp / "out", blacklist=[("_retail_", "ElvUI"), ("*", "Questie")],
                                  last_flavor_choice="", last_account="ACCT1")
        s.save_settings(self.cfg, saved)
        self.assertEqual(s.load_settings(Config(self.tmp / "ace3-profile-manager.cfg").load()), saved)

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

    def test_blacklist_pairs_parse_and_format(self):
        """Feedback round 1: the blacklist holds (flavor folder, addon) pairs; a bare (legacy) name is "*"."""
        self.assertEqual(bl.parse_blacklist("_retail_:ElvUI, Questie"), [("_retail_", "ElvUI"), ("*", "Questie")])
        self.assertEqual(bl.parse_blacklist(" _retail_:ElvUI\n_RETAIL_:elvui ,, _classic_era_ : Questie "),
                         [("_retail_", "ElvUI"), ("_classic_era_", "Questie")])
        pairs = [("_classic_era_", "Questie"), ("_retail_", "ElvUI")]
        text = bl.format_blacklist(pairs)
        self.assertEqual(text, "_retail_:ElvUI, _classic_era_:Questie")
        self.assertEqual(bl.parse_blacklist(text), sorted(pairs, key=lambda p: (p[1], p[0])))
        self.assertEqual(bl.format_blacklist([("*", "Questie")]), "Questie")  # a wildcard stays a bare name
        self.assertEqual(bl.parse_blacklist(bl.format_blacklist([("*", "Questie")])), [("*", "Questie")])
        self.assertEqual(bl.parse_blacklist(""), [])

    def test_blacklist_matches_flavor_and_addon(self):
        retail = [("_retail_", "ElvUI")]
        self.assertTrue(bl.is_blacklisted(retail, "_retail_", "elvui"))
        self.assertTrue(bl.is_blacklisted([("_Retail_", "ELVUI")], "_retail_", "ElvUI"))
        self.assertFalse(bl.is_blacklisted(retail, "_classic_era_", "ElvUI"))  # Retail's pair: not Classic Era
        self.assertFalse(bl.is_blacklisted(retail, "_retail_", "ElvUI_Options"))
        legacy = [("*", "Questie")]  # a bare name from the first build: every flavor
        self.assertTrue(bl.is_blacklisted(legacy, "_retail_", "Questie"))
        self.assertTrue(bl.is_blacklisted(legacy, "_classic_era_", "questie"))

    def test_toggle_pair(self):
        folders = ["_retail_", "_classic_era_"]
        pairs, now = bl.toggle_pair([], "_retail_", "ElvUI", folders)
        self.assertEqual((pairs, now), ([("_retail_", "ElvUI")], True))
        self.assertEqual(bl.toggle_pair(pairs, "_RETAIL_", "elvui", folders), ([], False))
        # Un-blacklisting a wildcard in one flavor keeps it in the others, as explicit pairs.
        self.assertEqual(bl.toggle_pair([("*", "ElvUI"), ("_retail_", "KickCD")], "_retail_", "ElvUI", folders),
                         ([("_classic_era_", "ElvUI"), ("_retail_", "KickCD")], False))

    def test_legacy_names_load_as_wildcards(self):
        self.cfg.set(s.SECTION, "blacklist", "ElvUI, _retail_:KickCD", log=False)
        self.assertEqual(s.load_settings(self.cfg).blacklist, [("*", "ElvUI"), ("_retail_", "KickCD")])

    def test_root_and_journal_dir(self):
        wow = self.tmp / "World of Warcraft"
        self.assertEqual(s.resolve_root(s.ProfileSettings(), wow), wow / "wow-tools" / "ace3-profile-manager")
        self.assertEqual(s.resolve_root(s.ProfileSettings(backup_dir=self.tmp / "b"), wow),
                         self.tmp / "b" / "ace3-profile-manager")
        self.assertIsNone(s.resolve_root(s.ProfileSettings(), None))
        self.assertEqual(resolve_journal_dir(wow), wow / "wow-tools" / "ace3-profile-manager" / "journal")

    def test_events_registered_with_prefix(self):
        self.assertIn(TOOL_NAME, TOOL_REGISTRIES)
        self.assertTrue(all(name.startswith("ace.") for name in TOOL_REGISTRIES[TOOL_NAME]))
