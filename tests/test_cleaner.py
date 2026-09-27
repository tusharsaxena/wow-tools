import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import NOW, build_wow_tree
from wowtools.core.backup import BackupError
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.wtf_cleaner.cleaner import CleanError, execute
from wowtools.tools.wtf_cleaner.report import format_result_text, result_to_dict
from wowtools.tools.wtf_cleaner.rules import Criteria, ProposalItem, evaluate
from wowtools.tools.wtf_cleaner.scanner import SVFile, scan

WHEN = datetime(2026, 9, 27, 14, 3, 11)


def snapshot(root: Path) -> dict:
    result = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            stat = path.stat()
            result[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime)
    return result


class CleanerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.retail = WowInstall(self.root).flavor("retail")
        self.sv = self.retail.account_dir / "ACCT1" / "SavedVariables"
        self.proposal = evaluate(scan(self.retail), Criteria(), now=NOW)
        self.backup_dir = self.tmp / "backups"

    def paths(self):
        return [f.path for item in self.proposal.items for f in item.files]

    def item(self, addon, owner="account-wide"):
        return next(i for i in self.proposal.items if i.addon == addon and i.owner_label == owner)

    def test_clean_backs_up_then_deletes(self):
        with capture_events() as records:
            result = execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                             backup_dir=self.backup_dir, now=WHEN)
        self.assertEqual(len(result.deleted), 8)
        for path in self.paths():
            self.assertFalse(path.exists(), path)
        self.assertEqual(result.backup_path, self.backup_dir / "wtf-cleaner_retail_20260927-140311.zip")
        with zipfile.ZipFile(result.backup_path) as zf:
            self.assertEqual(len(zf.namelist()), 9)
        for kept in ("Auctionator.lua", "Auctionator.lua.bak", "Details.lua", "Blizzard_Foo.lua"):
            self.assertTrue((self.sv / kept).exists(), kept)
        names = [r["event"] for r in records]
        self.assertEqual(names[0], "clean.started")
        self.assertEqual(names[-1], "clean.completed")
        self.assertEqual(names.count("sv.deleted"), 8)
        self.assertIn("backup.created", names)
        self.assertLess(names.index("backup.created"), names.index("sv.deleted"))

    def test_dry_run_touches_nothing(self):
        before = snapshot(self.root)
        with capture_events() as records:
            result = execute(self.proposal.items, self.retail, dry_run=True, backup=True,
                             backup_dir=self.backup_dir, now=WHEN)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.backup_dir.exists())
        self.assertTrue(result.dry_run)
        self.assertEqual(len(result.would_delete), 8)
        self.assertEqual(result.deleted, [])
        would = [r for r in records if r["event"] == "sv.would_delete"]
        self.assertEqual(len(would), 8)
        self.assertTrue(all(r["dry_run"] for r in would))
        self.assertIn("backup.would_create", [r["event"] for r in records])
        self.assertIn("DRY RUN", format_result_text(result))

    def test_changed_and_missing_files_are_skipped(self):
        (self.sv / "Uninstalled.lua").write_text("written by WoW after the scan, longer than before")
        (self.sv / "Uninstalled.lua.bak").unlink()
        result = execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                         backup_dir=self.backup_dir, now=WHEN)
        self.assertEqual(sorted(o.detail for o in result.skipped), ["changed", "missing"])
        self.assertTrue((self.sv / "Uninstalled.lua").exists())
        self.assertEqual(len(result.deleted), 6)
        with zipfile.ZipFile(result.backup_path) as zf:
            self.assertNotIn("WTF/Account/ACCT1/SavedVariables/Uninstalled.lua", zf.namelist())

    def test_backup_failure_deletes_nothing(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("a file where the backup folder should be")
        with capture_events() as records:
            with self.assertRaises(BackupError):
                execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                        backup_dir=blocker / "sub", now=WHEN)
        for path in self.paths():
            self.assertTrue(path.exists(), path)
        self.assertIn("backup.failed", [r["event"] for r in records])

    def test_without_backup(self):
        result = execute(self.proposal.items, self.retail, dry_run=False, backup=False,
                         backup_dir=self.backup_dir, now=WHEN)
        self.assertIsNone(result.backup_path)
        self.assertEqual(len(result.deleted), 8)
        self.assertFalse(self.backup_dir.exists())

    def test_empty_selection_makes_no_backup(self):
        result = execute([], self.retail, dry_run=False, backup=True, backup_dir=self.backup_dir, now=WHEN)
        self.assertIsNone(result.backup_path)
        self.assertEqual(result.outcomes, [])
        self.assertFalse(self.backup_dir.exists())

    def test_path_guard_rejects_files_outside_savedvariables(self):
        outside = self.retail.account_dir / "ACCT1" / "config-cache.wtf"
        stat = outside.stat()
        rogue = ProposalItem(self.item("DisabledAddon").group,
                             [SVFile(outside, stat.st_size, stat.st_mtime, False)], ["not_enabled"])
        with self.assertRaises(CleanError):
            execute([rogue], self.retail, dry_run=False, backup=False, backup_dir=None, now=WHEN)
        self.assertTrue(outside.exists())

    @unittest.skipIf(os.name == "nt", "symlinks need admin rights on Windows")
    def test_symlink_escaping_wtf_is_rejected(self):
        target = self.tmp / "elsewhere.lua"
        target.write_text("precious")
        (self.sv / "Evil.lua").symlink_to(target)
        proposal = evaluate(scan(self.retail), Criteria(), now=NOW)
        with self.assertRaises(CleanError):
            execute(proposal.items, self.retail, dry_run=False, backup=False, backup_dir=None, now=WHEN)
        self.assertTrue(target.exists())
        self.assertTrue((self.sv / "DisabledAddon.lua").exists())

    def test_delete_failure_is_reported_and_others_continue(self):
        original = Path.unlink

        def flaky(path, *args, **kwargs):
            if path.name == "DisabledAddon.lua":
                raise PermissionError("locked by another program")
            return original(path, *args, **kwargs)

        with capture_events() as records:
            with patch.object(Path, "unlink", flaky):
                result = execute(self.proposal.items, self.retail, dry_run=False, backup=False,
                                 backup_dir=None, now=WHEN)
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(len(result.deleted), 7)
        completed = [r for r in records if r["event"] == "clean.completed"][0]
        self.assertEqual(completed["level"], "warning")
        self.assertIn("sv.failed", [r["event"] for r in records])

    def test_result_dict(self):
        result = execute(self.proposal.items, self.retail, dry_run=True, backup=True,
                         backup_dir=self.backup_dir, now=WHEN)
        data = result_to_dict(result)
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["counts"]["would_delete"], 8)
        self.assertEqual(len(data["outcomes"]), 8)
