import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_wow_tree
from wowtools.core import backup
from wowtools.core.backup import BackupEntry, BackupError, backup_filename, create_backup


class BackupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        root = build_wow_tree(self.tmp / "World of Warcraft")
        self.flavor_dir = root / "_retail_"
        self.sv = self.flavor_dir / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        self.dest = self.tmp / "backups" / "b.zip"
        self.entries = [BackupEntry(self.sv / "Uninstalled.lua", ("not_installed",)),
                        BackupEntry(self.sv / "Uninstalled.lua.bak", ("not_installed",))]

    def test_zip_contains_files_relative_to_flavor_and_manifest(self):
        out = create_backup(self.entries, self.flavor_dir, self.dest, {"tool": "wtf-cleaner", "flavor": "_retail_"})
        self.assertEqual(out, self.dest)
        with zipfile.ZipFile(self.dest) as zf:
            self.assertEqual(sorted(zf.namelist()), [
                "WTF/Account/ACCT1/SavedVariables/Uninstalled.lua",
                "WTF/Account/ACCT1/SavedVariables/Uninstalled.lua.bak",
                "manifest.json",
            ])
            manifest = json.loads(zf.read("manifest.json"))
        self.assertEqual(manifest["tool"], "wtf-cleaner")
        self.assertEqual(manifest["files"][0]["reasons"], ["not_installed"])
        self.assertEqual(manifest["files"][0]["size"], (self.sv / "Uninstalled.lua").stat().st_size)
        self.assertFalse(self.dest.with_name("b.zip.partial").exists())

    def test_file_outside_base_is_rejected(self):
        outside = self.tmp / "elsewhere.lua"
        outside.write_text("x")
        with self.assertRaises(BackupError):
            create_backup([BackupEntry(outside)], self.flavor_dir, self.dest, {})
        self.assertFalse(self.dest.exists())

    def test_missing_file_raises_and_leaves_no_zip(self):
        with self.assertRaises(BackupError):
            create_backup([BackupEntry(self.sv / "Gone.lua")], self.flavor_dir, self.dest, {})
        self.assertFalse(self.dest.exists())

    def test_verification_failure_leaves_nothing(self):
        with patch.object(backup, "verify_backup", side_effect=BackupError("boom")):
            with self.assertRaises(BackupError):
                create_backup(self.entries, self.flavor_dir, self.dest, {})
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.dest.with_name("b.zip.partial").exists())

    def test_unwritable_destination_raises_backup_error(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("a file, not a folder")
        with self.assertRaises(BackupError):
            create_backup(self.entries, self.flavor_dir, blocker / "b.zip", {})

    def test_empty_entries_rejected(self):
        with self.assertRaises(BackupError):
            create_backup([], self.flavor_dir, self.dest, {})

    def test_backup_filename(self):
        self.assertEqual(backup_filename("wtf-cleaner", "retail", datetime(2026, 9, 27, 14, 3, 11)),
                         "wtf-cleaner_retail_20260927-140311.zip")
