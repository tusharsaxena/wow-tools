from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core.config import Config
from wowtools.core.events import REGISTRY
from wowtools.core.install import WowInstall
from wowtools.core.paths import to_native
from wowtools.tools.screenshot_organizer import events
from wowtools.tools.screenshot_organizer.settings import (SECTION, ShotSettings, load_settings, resolve_journal_dir,
                                                          save_settings, source_dir, target_root, validate_dest)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.install = WowInstall(self.root)
        self.retail = self.install.flavor("retail")

    def test_defaults_and_round_trip(self):
        cfg = Config(self.tmp / "screenshot-organizer.cfg")
        self.assertEqual(load_settings(cfg), ShotSettings())
        save_settings(cfg, ShotSettings(self.tmp / "arch", True, "_retail_"))
        again = load_settings(Config(cfg.path).load())
        self.assertEqual(again, ShotSettings(self.tmp / "arch", True, "_retail_"))

    def test_bad_values_fall_back(self):
        cfg = Config(self.tmp / "screenshot-organizer.cfg")
        cfg.set(SECTION, "copy_mode", "maybe", log=False)
        self.assertFalse(load_settings(cfg).copy_mode)

    def test_retention_is_global_and_stale_keys_go_on_save(self):
        """Feedback round 1: retention lives in [general]; the old per-tool key is ignored, then removed."""
        cfg = Config(self.tmp / "screenshot-organizer.cfg")
        cfg.set(SECTION, "keep_journals", "2", log=False)
        s = load_settings(cfg)
        self.assertFalse(hasattr(s, "keep_journals"))
        save_settings(cfg, s)
        self.assertIsNone(Config(cfg.path).load().get(SECTION, "keep_journals"))

    def test_target_root(self):
        self.assertEqual(source_dir(self.retail), self.root / "_retail_" / "Screenshots")
        self.assertEqual(target_root(self.retail, None), self.root / "_retail_" / "Screenshots")
        self.assertEqual(target_root(self.retail, self.tmp / "arch"), self.tmp / "arch" / "_retail_")

    def test_journal_dir(self):
        self.assertIsNone(resolve_journal_dir(None))
        self.assertEqual(resolve_journal_dir(self.root), self.root / "wow-tools" / "screenshot-organizer" / "journal")

    def test_validate_dest(self):
        self.assertIsNone(validate_dest(None, self.install))
        self.assertIsNone(validate_dest(self.tmp / "arch", self.install))
        self.assertIsNotNone(validate_dest(self.root, self.install))
        self.assertIsNotNone(validate_dest(self.root / "_retail_" / "Screenshots", self.install))
        self.assertIsNotNone(validate_dest(self.root / "_retail_" / "Screenshots" / "x", self.install))
        self.assertIsNotNone(validate_dest(self.root / "_retail_" / "WTF" / "x", self.install))
        self.assertIsNotNone(validate_dest(self.root / "_retail_" / "Interface" / "AddOns" / "x", self.install))

    def test_validate_dest_needs_a_full_path(self):
        # A relative destination would be filed under whatever folder the suite was started from.
        for raw in ("Shots", "~/shots", "D:Shots"):
            self.assertIn("full path", validate_dest(Path(raw), self.install) or "", raw)

    @unittest.skipIf(os.name == "nt", "simulates WSL: on Windows a UNC path is a full path")
    def test_validate_dest_rejects_unc_under_wsl(self):
        unc = to_native(r"\\nas\share\Shots", wsl=True)  # a UNC path has no WSL form: it stays relative
        self.assertIn("full path", validate_dest(unc, self.install) or "")

    def test_events_are_prefixed(self):
        self.assertTrue(events.EVENTS)
        for name in events.EVENTS:
            self.assertTrue(name.startswith("shots."), name)
            self.assertIs(REGISTRY[name], events.EVENTS[name])
