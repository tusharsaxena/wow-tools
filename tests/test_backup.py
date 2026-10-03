from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_wow_tree
from wowtools.core import backup
from wowtools.core.backup import BackupEntry, BackupError, create_backup


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

    def test_verify_reports_every_entry(self):
        calls = []
        create_backup(self.entries, self.flavor_dir, self.dest, {}, on_verify=lambda *a: calls.append(a))
        self.assertEqual([c[:2] for c in calls], [(1, 3), (2, 3), (3, 3)])

    def test_verify_catches_a_corrupt_entry(self):
        data = b"saved variables " * 200
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        bad = self.dest.with_name("c.zip")
        with zipfile.ZipFile(bad, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr("a.lua", data)
        raw = bytearray(bad.read_bytes())
        offset = raw.index(data)
        raw[offset + 10] ^= 0xFF  # flip a byte inside the stored data: the CRC no longer matches
        bad.write_bytes(bytes(raw))
        with self.assertRaises(BackupError):
            backup.verify_backup(bad, {"a.lua": len(data)})

    def test_known_size_and_mtime_skip_the_stat(self):
        entry = BackupEntry(self.sv / "Uninstalled.lua", (), size=12345, mtime=1.0)
        with patch.object(Path, "stat", side_effect=AssertionError("stat called")):
            with self.assertRaises(BackupError):  # zip size differs from the given size: verify catches it
                create_backup([entry], self.flavor_dir, self.dest, {})

    def test_dotdot_path_is_resolved_and_rejected(self):
        sneaky = self.flavor_dir / "WTF" / ".." / ".." / "elsewhere.lua"
        (self.tmp / "World of Warcraft" / "elsewhere.lua").write_text("x")
        with self.assertRaises(BackupError):
            create_backup([BackupEntry(sneaky)], self.flavor_dir, self.dest, {})
