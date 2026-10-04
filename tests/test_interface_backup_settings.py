from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core.config import Config
from wowtools.core.events import REGISTRY, TOOL_REGISTRIES
from wowtools.core.install import WowInstall
from wowtools.core.journal import TOOLS_SUBDIR
from wowtools.tools.interface_backup import events
from wowtools.tools.interface_backup.settings import (SECTION, BackupSettings, load_settings, resolve_backup_root,
                                                      resolve_journal_dir, save_settings, validate_backup_dir)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.cfg = Config(self.tmp / "interface-backup.cfg")

    def test_defaults(self):
        s = load_settings(self.cfg)
        self.assertEqual((s.backup_dir, s.keep_backups, s.keep_journals, s.last_flavor_choice), (None, 10, 10, ""))
        self.assertEqual(s, BackupSettings())

    def test_round_trip_and_zero_means_keep_all(self):
        save_settings(self.cfg, BackupSettings(self.tmp / "bk", 0, 3, "_retail_"))
        s = load_settings(Config(self.tmp / "interface-backup.cfg").load())
        self.assertEqual((s.backup_dir, s.keep_backups, s.keep_journals, s.last_flavor_choice),
                         (self.tmp / "bk", 0, 3, "_retail_"))

    def test_bad_values_fall_back(self):
        self.cfg.set(SECTION, "keep_backups", "-4", log=False)
        self.cfg.set(SECTION, "keep_journals", "zero", log=False)
        s = load_settings(self.cfg)
        self.assertEqual((s.keep_backups, s.keep_journals), (10, 10))
        self.cfg.set(SECTION, "keep_journals", "0", log=False)
        self.assertEqual(load_settings(self.cfg).keep_journals, 10)

    def test_roots(self):
        wow = self.tmp / "WoW"
        self.assertEqual(resolve_backup_root(BackupSettings(), wow), wow / TOOLS_SUBDIR / "interface-backup")
        self.assertEqual(resolve_backup_root(BackupSettings(self.tmp / "x"), wow), self.tmp / "x" / "interface-backup")
        self.assertEqual(resolve_backup_root(BackupSettings(self.tmp / "x"), None), self.tmp / "x" / "interface-backup")
        self.assertIsNone(resolve_backup_root(BackupSettings(), None))
        self.assertEqual(resolve_journal_dir(wow), wow / TOOLS_SUBDIR / "interface-backup" / "journal")
        self.assertIsNone(resolve_journal_dir(None))

    def test_validate(self):
        root = build_wow_tree(self.tmp / "WoW")
        install = WowInstall(root)
        self.assertIsNone(validate_backup_dir(None, install))
        self.assertIsNone(validate_backup_dir(self.tmp / "bk", install))
        self.assertIn("Interface", validate_backup_dir(root / "_retail_" / "Interface" / "x", install))
        self.assertIn("WTF", validate_backup_dir(root / "_retail_" / "WTF", install))
        self.assertIn("WoW folder", validate_backup_dir(root, install))
        self.assertIn("full path", validate_backup_dir(Path("relative"), install))


class EventsTest(unittest.TestCase):
    def test_events_are_registered_under_the_tool_with_the_prefix(self):
        self.assertEqual(events.TOOL_NAME, "interface-backup")
        self.assertEqual(TOOL_REGISTRIES[events.TOOL_NAME], events.EVENTS)
        for name, spec in events.EVENTS.items():
            self.assertTrue(name.startswith("ibackup."), name)
            self.assertIs(REGISTRY[name], spec)
