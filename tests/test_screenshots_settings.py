import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core.config import Config
from wowtools.core.events import REGISTRY
from wowtools.core.install import WowInstall
from wowtools.tools.screenshots import events
from wowtools.tools.screenshots.settings import (DEFAULT_KEEP_JOURNALS, SECTION, ShotSettings, load_settings,
                                                 resolve_journal_dir, save_settings, source_dir, target_root,
                                                 validate_dest)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.install = WowInstall(self.root)
        self.retail = self.install.flavor("retail")

    def test_defaults_and_round_trip(self):
        cfg = Config(self.tmp / "screenshots.cfg")
        self.assertEqual(load_settings(cfg), ShotSettings())
        save_settings(cfg, ShotSettings(self.tmp / "arch", True, "_retail_", 3))
        again = load_settings(Config(cfg.path).load())
        self.assertEqual(again, ShotSettings(self.tmp / "arch", True, "_retail_", 3))

    def test_bad_values_fall_back(self):
        cfg = Config(self.tmp / "screenshots.cfg")
        cfg.set(SECTION, "copy_mode", "maybe", log=False)
        cfg.set(SECTION, "keep_journals", "0", log=False)
        s = load_settings(cfg)
        self.assertFalse(s.copy_mode)
        self.assertEqual(s.keep_journals, 1)
        cfg.set(SECTION, "keep_journals", "x", log=False)
        self.assertEqual(load_settings(cfg).keep_journals, DEFAULT_KEEP_JOURNALS)

    def test_target_root(self):
        self.assertEqual(source_dir(self.retail), self.root / "_retail_" / "Screenshots")
        self.assertEqual(target_root(self.retail, None), self.root / "_retail_" / "Screenshots")
        self.assertEqual(target_root(self.retail, self.tmp / "arch"), self.tmp / "arch" / "_retail_")

    def test_journal_dir(self):
        self.assertIsNone(resolve_journal_dir(None))
        self.assertEqual(resolve_journal_dir(self.root), self.root / "wow-tools" / "screenshots" / "journal")

    def test_validate_dest(self):
        self.assertIsNone(validate_dest(None, self.install))
        self.assertIsNone(validate_dest(self.tmp / "arch", self.install))
        self.assertIsNotNone(validate_dest(self.root, self.install))
        self.assertIsNotNone(validate_dest(self.root / "_retail_" / "Screenshots", self.install))
        self.assertIsNotNone(validate_dest(self.root / "_retail_" / "Screenshots" / "x", self.install))

    def test_events_are_prefixed(self):
        self.assertTrue(events.EVENTS)
        for name in events.EVENTS:
            self.assertTrue(name.startswith("shots."), name)
            self.assertIs(REGISTRY[name], events.EVENTS[name])
