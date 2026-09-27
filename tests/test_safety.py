import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core.backup import BackupError
from wowtools.core.install import WowInstall
from wowtools.tools.wtf_cleaner.safety import (MARKER_NAME, Marker, clear_marker, read_marker, recovery_message,
                                               restore_deleted, take_snapshot, write_marker)

WHEN = datetime(2026, 9, 27, 14, 3, 11)


class SafetyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.retail = WowInstall(self.root).flavor("retail")
        self.backup_dir = self.tmp / "backups"

    def wtf_files(self) -> set[str]:
        found = set()
        for dirpath, _, names in os.walk(self.retail.wtf_dir):
            for name in names:
                found.add((Path(dirpath) / name).relative_to(self.retail.path).as_posix())
        return found

    def test_snapshot_contains_whole_wtf_and_verifies(self):
        calls = []
        snap = take_snapshot(self.retail, self.backup_dir, WHEN, progress=lambda *a: calls.append(a))
        self.assertEqual(snap, self.backup_dir / "wtf-snapshot_retail_20260927-140311.zip")
        self.assertTrue(snap.exists())
        self.assertFalse(snap.with_name(snap.name + ".partial").exists())
        with zipfile.ZipFile(snap) as zf:
            names = set(zf.namelist())
            self.assertIsNone(zf.testzip())
        self.assertEqual(names, self.wtf_files())
        self.assertIn("WTF/Account/ACCT1/config-cache.wtf", names)
        self.assertIn("WTF/Account/ACCT1/Realm1/CharA/AddOns.txt", names)
        self.assertTrue(calls)
        self.assertTrue(all(c[0] == "snapshot" for c in calls))
        self.assertEqual(calls[-1][1], calls[-1][2])

    def test_snapshot_failure_raises_backup_error(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("a file where the backup folder should be")
        with self.assertRaises(BackupError):
            take_snapshot(self.retail, blocker / "sub", WHEN)

    def test_marker_round_trip_and_unreadable_marker_returns_none(self):
        self.assertIsNone(read_marker(self.backup_dir))
        marker = Marker(snapshot=self.backup_dir / "wtf-snapshot_retail_20260927-140311.zip", flavor="_retail_",
                        flavor_path=self.retail.path, started="2026-09-27T14:03:11", pid=1234,
                        suite_version="0.1.0", files=["WTF/Account/ACCT1/SavedVariables/Uninstalled.lua"])
        write_marker(self.backup_dir, marker)
        self.assertTrue((self.backup_dir / MARKER_NAME).exists())
        self.assertEqual(read_marker(self.backup_dir), marker)
        clear_marker(self.backup_dir)
        self.assertFalse((self.backup_dir / MARKER_NAME).exists())
        clear_marker(self.backup_dir)  # clearing twice is fine
        (self.backup_dir / MARKER_NAME).write_text("{not json", encoding="utf-8")
        self.assertIsNone(read_marker(self.backup_dir))
        (self.backup_dir / MARKER_NAME).write_text('{"snapshot": "x"}', encoding="utf-8")
        self.assertIsNone(read_marker(self.backup_dir))
        (self.backup_dir / MARKER_NAME).write_bytes(b"\xff\xfe\x00garbage")
        self.assertIsNone(read_marker(self.backup_dir))

    def test_restore_deleted_never_overwrites(self):
        sv = self.retail.account_dir / "ACCT1" / "SavedVariables"
        original = (sv / "Uninstalled.lua").read_bytes()
        snap = take_snapshot(self.retail, self.backup_dir, WHEN)
        (sv / "Uninstalled.lua").unlink()
        (sv / "DisabledAddon.lua").unlink()
        (sv / "DisabledAddon.lua").write_text("recreated by WoW", encoding="utf-8")
        rels = ["WTF/Account/ACCT1/SavedVariables/Uninstalled.lua",
                "WTF/Account/ACCT1/SavedVariables/DisabledAddon.lua"]
        restored = restore_deleted(snap, self.retail, rels)
        self.assertEqual(restored, ["WTF/Account/ACCT1/SavedVariables/Uninstalled.lua"])
        self.assertEqual((sv / "Uninstalled.lua").read_bytes(), original)
        self.assertEqual((sv / "DisabledAddon.lua").read_text(encoding="utf-8"), "recreated by WoW")

    def test_restore_from_unreadable_snapshot_raises(self):
        bad = self.tmp / "bad.zip"
        bad.write_text("not a zip")
        with self.assertRaises(BackupError):
            restore_deleted(bad, self.retail, ["WTF/Account/ACCT1/SavedVariables/Uninstalled.lua"])
        with self.assertRaises(BackupError):
            restore_deleted(self.tmp / "missing.zip", self.retail, ["WTF/x.lua"])

    def test_recovery_message(self):
        marker = Marker(snapshot=Path("/b/wtf-snapshot_retail_20260927-140311.zip"), flavor="_retail_",
                        flavor_path=Path("/wow/_retail_"), started="2026-09-27T14:03:11", pid=1,
                        suite_version="0.1.0", files=[])
        text = recovery_message(marker)
        self.assertIn("did not finish", text)
        self.assertIn("2026-09-27T14:03:11", text)
        self.assertIn(str(marker.snapshot), text)
        self.assertIn(f"close WoW, then unzip it into {marker.flavor_path} to restore", text)
