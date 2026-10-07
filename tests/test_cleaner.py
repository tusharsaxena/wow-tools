from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import NOW, build_wow_tree
from wowtools.core import svfiles as svfiles_module
from wowtools.core.backup import BackupError
from wowtools.core.events import TOOL_REGISTRIES, capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.wtf_cleaner import cleaner as cleaner_module
from wowtools.tools.wtf_cleaner.cleaner import CleanError, execute, prune_cleaned_zips, prune_dry_run_zips
from wowtools.tools.wtf_cleaner.result_screen import summary_rows
from wowtools.tools.wtf_cleaner.rules import Criteria, ProposalItem, evaluate
from wowtools.tools.wtf_cleaner.safety import MARKER_NAME
from wowtools.tools.wtf_cleaner.scanner import SVFile, scan

WHEN = datetime(2026, 9, 27, 14, 3, 11)
CLEANED = "cleaned/cleaned-retail-all-20260927-140311.zip"
SNAPSHOT = "backup/backup-retail-20260927-140311.zip"


def files_under(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) \
        if folder.exists() else []


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
        self.assertEqual(result.backup_path, self.backup_dir / CLEANED)
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

    def test_dry_run_writes_backup_but_deletes_nothing(self):
        before = snapshot(self.root)
        with capture_events() as records:
            result = execute(self.proposal.items, self.retail, dry_run=True, backup=True,
                             backup_dir=self.backup_dir, now=WHEN)
        self.assertEqual(snapshot(self.root), before)
        zips = list(self.backup_dir.rglob("*.zip"))
        self.assertEqual(len(zips), 1)
        self.assertEqual(result.backup_path, zips[0])
        with zipfile.ZipFile(zips[0]) as zf:
            self.assertEqual(len(zf.namelist()), 9)
        self.assertTrue(result.dry_run)
        self.assertEqual(len(result.would_delete), 8)
        self.assertEqual(result.deleted, [])
        would = [r for r in records if r["event"] == "sv.would_delete"]
        self.assertEqual(len(would), 8)
        self.assertTrue(all(r["dry_run"] for r in would))
        created = [r for r in records if r["event"] == "backup.created"]
        self.assertEqual(len(created), 1)
        self.assertIs(created[0]["dry_run"], True)
        self.assertNotIn("backup.would_create", [r["event"] for r in records])

    def test_dry_run_without_backup_writes_nothing(self):
        before = snapshot(self.root)
        result = execute(self.proposal.items, self.retail, dry_run=True, backup=False,
                         backup_dir=self.backup_dir, now=WHEN)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.backup_dir.exists())
        self.assertIsNone(result.backup_path)
        self.assertEqual(len(result.would_delete), 8)

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

    def test_a_file_changed_after_the_snapshot_is_not_deleted(self):
        # F-004 (STD-5.7): WoW rewrites a selected file while the WTF backup is taken; the clean rechecks each
        # file right before deleting it, so the newer data is kept (with no cleaned-files zip to catch it).
        target = self.sv / "Uninstalled.lua"
        newer = "written by WoW during the WTF backup, longer than before"
        real_snapshot = cleaner_module._take_safety_snapshot

        def snapshot_then_rewrite(*args, **kwargs):
            path = real_snapshot(*args, **kwargs)
            target.write_text(newer)
            return path

        with capture_events() as records, \
                patch.object(cleaner_module, "_take_safety_snapshot", snapshot_then_rewrite):
            result = execute(self.proposal.items, self.retail, dry_run=False, backup=False,
                             backup_dir=self.backup_dir, now=WHEN)
        self.assertEqual(target.read_text(), newer)
        self.assertEqual([(o.path, o.detail) for o in result.skipped], [(target, "changed")])
        self.assertEqual(len(result.deleted), 7)
        for path in self.paths():
            if path != target:
                self.assertFalse(path.exists(), path)
        self.assertEqual(result.check_problems, [])
        self.assertIn("sv.skipped", [r["event"] for r in records])

    def test_backup_failure_deletes_nothing(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("a file where the backup folder should be")
        with capture_events() as records, self.assertRaises(BackupError):
            execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                    backup_dir=blocker / "sub", now=WHEN)
        for path in self.paths():
            self.assertTrue(path.exists(), path)
        # An unwritable backup folder now fails at the safety snapshot, which comes before the backup.
        self.assertIn("snapshot.failed", [r["event"] for r in records])

    def test_without_backup(self):
        result = execute(self.proposal.items, self.retail, dry_run=False, backup=False,
                         backup_dir=self.backup_dir, now=WHEN)
        self.assertIsNone(result.backup_path)
        self.assertEqual(len(result.deleted), 8)
        self.assertEqual(files_under(self.backup_dir), [SNAPSHOT])  # only the WTF backup, which is kept

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

        with capture_events() as records, patch.object(Path, "unlink", flaky):
            result = execute(self.proposal.items, self.retail, dry_run=False, backup=False,
                             backup_dir=self.backup_dir, now=WHEN)
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(len(result.deleted), 7)
        completed = next(r for r in records if r["event"] == "clean.completed")
        self.assertEqual(completed["level"], "warning")
        self.assertIn("sv.failed", [r["event"] for r in records])


class ProbeLeftoverTest(unittest.TestCase):
    setUp = CleanerTest.setUp
    item = CleanerTest.item

    def test_execute_recovers_probe_leftover_before_snapshot(self):
        canonical = self.sv / "Details.lua"
        original = canonical.read_bytes()
        canonical.rename(self.sv / "Details.lua.wowtools-lockcheck")  # left by a crash during an earlier probe
        with capture_events() as records:
            execute([self.item("Uninstalled")], self.retail, dry_run=False, backup=True,
                    backup_dir=self.backup_dir, now=WHEN)
        self.assertEqual(canonical.read_bytes(), original)
        self.assertFalse((self.sv / "Details.lua.wowtools-lockcheck").exists())
        recovered = [r for r in records if r["event"] == "clean.probe_recovered"]
        self.assertEqual(len(recovered), 1)
        self.assertTrue(recovered[0]["data"]["path"].endswith("Details.lua"))
        names = [r["event"] for r in records]
        self.assertLess(names.index("clean.probe_recovered"), names.index("snapshot.created"))
        with zipfile.ZipFile(self.backup_dir / SNAPSHOT) as zf:
            self.assertIn("WTF/Account/ACCT1/SavedVariables/Details.lua", zf.namelist())

    def test_execute_recovers_leftovers_in_folders_with_nothing_selected(self):
        """A leftover in a character folder and in another account is put back by a clean of account-wide files."""
        char_file = self.retail.account_dir / "ACCT1" / "Realm1" / "CharA" / "SavedVariables" / "Auctionator.lua"
        other_file = self.retail.account_dir / "ACCT2" / "SavedVariables" / "Details.lua"
        for path in (char_file, other_file):
            path.rename(path.with_name(path.name + ".wowtools-lockcheck"))
        execute([self.item("Uninstalled")], self.retail, dry_run=False, backup=True,
                backup_dir=self.backup_dir, now=WHEN)
        self.assertTrue(char_file.exists())
        self.assertTrue(other_file.exists())
        self.assertEqual(list(self.retail.account_dir.rglob("*.wowtools-lockcheck")), [])

    def test_account_scoped_clean_leaves_other_accounts_alone(self):
        other_file = self.retail.account_dir / "ACCT2" / "SavedVariables" / "Details.lua"
        other_file.rename(other_file.with_name("Details.lua.wowtools-lockcheck"))
        execute([self.item("Uninstalled")], self.retail, dry_run=False, backup=True,
                backup_dir=self.backup_dir, now=WHEN, account="ACCT1")
        self.assertTrue(other_file.with_name("Details.lua.wowtools-lockcheck").exists())

    def test_leftover_is_kept_when_the_original_exists_again(self):
        leftover = self.sv / "Details.lua.wowtools-lockcheck"
        leftover.write_bytes(b"old copy")
        with capture_events() as records:
            execute([self.item("Uninstalled")], self.retail, dry_run=False, backup=True,
                    backup_dir=self.backup_dir, now=WHEN)
        self.assertEqual(leftover.read_bytes(), b"old copy")
        self.assertEqual((self.sv / "Details.lua").read_text(encoding="utf-8"), "-- saved variables\n")
        self.assertNotIn("clean.probe_recovered", [r["event"] for r in records])

    def test_dry_run_changes_no_leftover(self):
        (self.sv / "Details.lua").rename(self.sv / "Details.lua.wowtools-lockcheck")
        execute([self.item("Uninstalled")], self.retail, dry_run=True, backup=False, backup_dir=self.backup_dir,
                now=WHEN)
        self.assertTrue((self.sv / "Details.lua.wowtools-lockcheck").exists())
        self.assertFalse((self.sv / "Details.lua").exists())


class CleanErrorTest(unittest.TestCase):
    def test_clean_error_instances_do_not_share_lists(self):
        first, second = CleanError("a"), CleanError("b")
        self.assertIsNot(first.restored, second.restored)
        first.restored.append("x")
        self.assertEqual(second.restored, [])
        self.assertEqual(CleanError("c", restored=["y"], files_missing=True).restored, ["y"])
        self.assertTrue(CleanError("c", files_missing=True).files_missing)
        self.assertFalse(second.files_missing)
        self.assertEqual(str(first), "a")


class SafetySnapshotCleanTest(unittest.TestCase):
    """Safety snapshot, marker and restore around a real clean (spec A.4), and progress stages (A.5)."""

    setUp = CleanerTest.setUp
    paths = CleanerTest.paths

    def run_clean(self, **kwargs):
        options = {"dry_run": False, "backup": True, "backup_dir": self.backup_dir, "now": WHEN}
        options.update(kwargs)
        return execute(self.proposal.items, self.retail, **options)

    def snapshot_path(self):
        return self.backup_dir / SNAPSHOT

    def test_clean_success_keeps_the_wtf_backup_and_clears_the_marker(self):
        with capture_events() as records:
            result = self.run_clean()
        self.assertEqual(files_under(self.backup_dir), [SNAPSHOT, CLEANED])
        self.assertEqual(result.snapshot_path, self.snapshot_path())
        self.assertEqual(result.restored, [])
        names = [r["event"] for r in records]
        self.assertIn("snapshot.created", names)
        self.assertNotIn("snapshot.removed", names)
        self.assertLess(names.index("snapshot.created"), names.index("backup.created"))

    def _hold_marker(self):
        """Patch core.marker's os.remove so clean-in-progress.json can never be removed (a virus scanner holds it)."""
        real_remove = os.remove

        def remove(path, *args, **kwargs):
            if Path(path).name == MARKER_NAME:
                raise PermissionError(13, "held by another program", str(path))
            return real_remove(path, *args, **kwargs)
        return patch("wowtools.core.marker.os.remove", side_effect=remove)

    def test_a_marker_that_cannot_be_removed_after_a_clean_is_reported(self):
        """T5.1 (F-002 follow-through): a clean that finished but could not remove its marker says so."""
        with self._hold_marker(), patch("wowtools.core.marker.time.sleep") as slept, \
                capture_events() as records:
            result = self.run_clean()
        self.assertTrue(slept.called)  # retried before giving up
        self.assertTrue(result.marker_left)
        self.assertTrue(result.deleted)
        self.assertTrue((self.backup_dir / MARKER_NAME).exists())
        left = [r for r in records if r["event"] == "clean.marker_left"]
        self.assertEqual(len(left), 1)
        self.assertEqual(left[0]["data"]["stage"], "finished")
        self.assertEqual(TOOL_REGISTRIES["wtf-cleaner"]["clean.marker_left"].level, "warning")
        self.assertIn("Crash marker", dict(summary_rows(result)))

    def test_a_removed_marker_is_not_reported(self):
        with capture_events() as records:
            result = self.run_clean()
        self.assertFalse(result.marker_left)
        self.assertNotIn("clean.marker_left", [r["event"] for r in records])
        self.assertNotIn("Crash marker", dict(summary_rows(result)))

    def test_snapshot_failure_deletes_nothing(self):
        def boom(*args, **kwargs):
            raise BackupError("disk full")

        with (
            capture_events() as records, patch.object(cleaner_module, "take_snapshot", boom),
            self.assertRaises(BackupError),
        ):
            self.run_clean()
        for path in self.paths():
            self.assertTrue(path.exists(), path)
        self.assertFalse((self.backup_dir / MARKER_NAME).exists())
        names = [r["event"] for r in records]
        self.assertIn("snapshot.failed", names)
        self.assertNotIn("sv.deleted", names)

    def _interrupt_on_fourth_unlink(self, exc_type):
        before = {p: p.read_bytes() for p in self.paths()}
        original = Path.unlink
        deleted = []

        def flaky(path, *args, **kwargs):
            if len(deleted) == 3:
                raise exc_type("boom")
            deleted.append(path)
            return original(path, *args, **kwargs)

        with capture_events() as records, patch.object(Path, "unlink", flaky), self.assertRaises(CleanError) as ctx:
            self.run_clean()
        self.assertEqual(len(deleted), 3)
        for path, data in before.items():
            self.assertTrue(path.exists(), path)
            self.assertEqual(path.read_bytes(), data, path)
        self.assertFalse((self.backup_dir / MARKER_NAME).exists())
        self.assertIn("restored", str(ctx.exception))
        self.assertIn("3 deleted files", str(ctx.exception))
        self.assertFalse(ctx.exception.files_missing)
        names = [r["event"] for r in records]
        self.assertIn("restore.completed", names)
        self.assertNotIn("restore.failed", names)

    def test_unexpected_error_mid_delete_restores_deleted_files(self):
        self._interrupt_on_fourth_unlink(RuntimeError)

    def test_keyboard_interrupt_mid_delete_restores(self):
        self._interrupt_on_fourth_unlink(KeyboardInterrupt)

    def test_restore_failure_keeps_marker_and_snapshot(self):
        original = Path.unlink
        calls = []

        def flaky(path, *args, **kwargs):
            calls.append(path)
            if len(calls) == 2:
                raise RuntimeError("boom")
            return original(path, *args, **kwargs)

        def broken_restore(*args, **kwargs):
            raise BackupError("snapshot unreadable")

        with (
            capture_events() as records, patch.object(Path, "unlink", flaky),
            patch.object(cleaner_module, "restore_deleted", broken_restore),
            self.assertRaises(CleanError) as ctx,
        ):
            self.run_clean()
        self.assertTrue((self.backup_dir / MARKER_NAME).exists())
        self.assertTrue(self.snapshot_path().exists())
        self.assertIn(str(self.snapshot_path()), str(ctx.exception))
        self.assertTrue(ctx.exception.files_missing)  # deleted and not put back
        names = [r["event"] for r in records]
        self.assertIn("restore.failed", names)
        self.assertNotIn("restore.completed", names)

    def test_selective_backup_failure_after_snapshot_deletes_nothing(self):
        def boom(*args, **kwargs):
            raise BackupError("zip broke")

        with (
            capture_events() as records, patch.object(cleaner_module, "create_backup", boom),
            self.assertRaises(BackupError),
        ):
            self.run_clean()
        for path in self.paths():
            self.assertTrue(path.exists(), path)
        self.assertEqual(files_under(self.backup_dir), [SNAPSHOT])  # the WTF backup is kept; no marker
        names = [r["event"] for r in records]
        self.assertIn("snapshot.created", names)
        self.assertIn("backup.failed", names)

    def test_dry_run_takes_no_snapshot(self):
        with capture_events() as records:
            result = self.run_clean(dry_run=True)
        self.assertEqual(files_under(self.backup_dir), [CLEANED.replace("cleaned/cleaned-", "cleaned/dryrun-")])
        self.assertIsNone(result.snapshot_path)
        names = [r["event"] for r in records]
        self.assertNotIn("snapshot.created", names)
        self.assertFalse((self.backup_dir / MARKER_NAME).exists())

    def test_progress_stages_in_order(self):
        calls = []
        result = self.run_clean(progress=lambda *a: calls.append(a))
        self.assertEqual(len(result.deleted), 8)
        stages = []
        for stage, *_ in calls:
            if not stages or stages[-1] != stage:
                stages.append(stage)
        self.assertEqual(stages, ["check", "lock_check", "snapshot_list", "snapshot", "snapshot_verify", "backup", "verify",
                                  "delete", "validate"])
        for stage in stages:
            last = [c for c in calls if c[0] == stage][-1]
            self.assertEqual(last[1], last[2], stage)
        self.assertEqual(len([c for c in calls if c[0] == "backup"]), 8)
        self.assertEqual(len([c for c in calls if c[0] == "check"]), 8)
        self.assertEqual(len([c for c in calls if c[0] == "verify"]), 9)  # 8 files + manifest.json
        self.assertEqual(len([c for c in calls if c[0] == "delete"]), 8)

    def test_raising_progress_callback_changes_nothing(self):
        def bad(*args):
            raise RuntimeError("the UI went away")

        with capture_events() as records:
            result = self.run_clean(progress=bad)
        self.assertEqual(len(result.deleted), 8)
        self.assertEqual(result.failed, [])
        self.assertEqual(files_under(self.backup_dir), [SNAPSHOT, CLEANED])
        names = [r["event"] for r in records]
        self.assertNotIn("restore.completed", names)
        self.assertNotIn("restore.failed", names)


class LockAndCheckTest(unittest.TestCase):
    """The lock check before a real clean, and the post-clean check against the snapshot."""

    setUp = CleanerTest.setUp
    paths = CleanerTest.paths
    run_clean = SafetySnapshotCleanTest.run_clean
    snapshot_path = SafetySnapshotCleanTest.snapshot_path
    item = CleanerTest.item

    def _lock(self, locked_name):
        """Windows refuses to rename a file another program holds open; simulate that for one file."""
        original = svfiles_module.rename_no_replace

        def rename(src, dst):
            if Path(src).name == locked_name:
                raise PermissionError(13, "The process cannot access the file because it is being used")
            return original(src, dst)
        return patch.object(svfiles_module, "rename_no_replace", rename)

    def test_locked_file_stops_a_real_clean_before_anything(self):
        before = snapshot(self.root)
        with capture_events() as records, self._lock("Uninstalled.lua.bak"), self.assertRaises(CleanError) as ctx:
            self.run_clean()
        self.assertIn("locked", str(ctx.exception))
        self.assertIn("Uninstalled.lua.bak", str(ctx.exception))
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.backup_dir.exists() and any(self.backup_dir.iterdir()))
        names = [r["event"] for r in records]
        self.assertIn("clean.locked", names)
        self.assertNotIn("snapshot.created", names)

    def test_dry_run_skips_the_lock_check(self):
        calls = []
        with self._lock("Uninstalled.lua.bak"):
            result = self.run_clean(dry_run=True, progress=lambda *a: calls.append(a[0]))
        self.assertEqual(len(result.would_delete), 8)
        self.assertNotIn("lock_check", calls)

    def test_lock_probe_leaves_files_in_place(self):
        before = snapshot(self.root)
        for path in self.paths():
            self.assertIsNone(cleaner_module._probe_lock(path))
        self.assertEqual(snapshot(self.root), before)

    def test_clean_is_validated_and_backup_kept(self):
        with capture_events() as records:
            result = self.run_clean()
        self.assertEqual(result.check_problems, [])
        self.assertTrue(self.snapshot_path().exists())
        self.assertIn("clean.validated", [r["event"] for r in records])

    def test_unselected_file_going_missing_is_reported(self):
        extra = self.sv / "Details.lua"
        original = cleaner_module._delete_one

        def delete_one(result, item, sv, flavor, dry_run, deleted):
            original(result, item, sv, flavor, dry_run, deleted)
            if extra.exists():
                extra.unlink()  # something else removed a file that was not selected
        with capture_events() as records, patch.object(cleaner_module, "_delete_one", delete_one):
            result = self.run_clean()
        self.assertTrue(any("ACCT1/SavedVariables/Details.lua is missing" in p for p in result.check_problems))
        self.assertTrue(self.snapshot_path().exists())
        self.assertFalse((self.backup_dir / MARKER_NAME).exists())
        names = [r["event"] for r in records]
        self.assertIn("clean.check_failed", names)
        self.assertNotIn("clean.validated", names)

    def test_check_that_cannot_run_is_reported(self):
        with patch.object(cleaner_module, "check_clean", return_value=["the check could not run: boom"]):
            result = self.run_clean()
        self.assertEqual(result.check_problems, ["the check could not run: boom"])
        self.assertTrue(self.snapshot_path().exists())

    def test_file_under_a_linked_account_is_never_deleted(self):
        account_dir = self.retail.account_dir
        try:
            os.symlink(account_dir / "ACCT2", account_dir / "ACCT3", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")
        linked = account_dir / "ACCT3" / "SavedVariables" / "Details.lua"
        stat = linked.stat()
        item = self.item("Uninstalled").with_files([SVFile(linked, stat.st_size, stat.st_mtime, False)])
        with capture_events(), self.assertRaisesRegex(BackupError, "would not be in the WTF backup"):
            execute([item], self.retail, dry_run=False, backup=False, backup_dir=self.backup_dir, now=WHEN)
        self.assertTrue((account_dir / "ACCT2" / "SavedVariables" / "Details.lua").exists())
        self.assertFalse((self.backup_dir / MARKER_NAME).exists())

    def test_guard_refuses_a_link_out_of_the_account_folder(self):
        outside = self.tmp / "outside.lua"
        outside.write_text("x")
        link = self.sv / "Linked.lua"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("symlinks not available")
        item = self.item("Uninstalled")
        stat = link.lstat()
        bad = item.with_files([SVFile(link, stat.st_size, stat.st_mtime, False)])
        with self.assertRaises(CleanError):
            execute([bad], self.retail, dry_run=True, backup=False, backup_dir=None, now=WHEN)


class ZipLayoutTest(unittest.TestCase):
    """cleaned/cleaned-<account>-<stamp>.zip, backup/backup-<stamp>.zip, and keeping the newest N backups."""

    setUp = CleanerTest.setUp

    def test_cleaned_zip_is_named_after_the_account(self):
        result = execute(self.proposal.items, self.retail, dry_run=False, backup=True, backup_dir=self.backup_dir,
                         now=WHEN, account="ACCT1")
        self.assertEqual(result.backup_path, self.backup_dir / "cleaned" / "cleaned-retail-ACCT1-20260927-140311.zip")
        with zipfile.ZipFile(result.backup_path) as zf:
            self.assertEqual(json.loads(zf.read("manifest.json"))["account"], "ACCT1")

    def test_dry_run_zip_has_its_own_name(self):
        result = execute(self.proposal.items, self.retail, dry_run=True, backup=True, backup_dir=self.backup_dir,
                         now=WHEN, account="ACCT1")
        self.assertEqual(result.backup_path, self.backup_dir / "cleaned" / "dryrun-retail-ACCT1-20260927-140311.zip")

    def test_dry_run_zips_are_pruned_per_flavor_and_cleaned_zips_untouched_by_dry_run(self):
        # F-018: dry runs are repeated often; keep the newest keep_backups dry-run zips of the flavor. A dry run
        # never prunes real cleaned-files zips (only a real clean does, when keep_cleaned > 0), nor other flavors'
        # or the user's files.
        folder = self.backup_dir / "cleaned"
        folder.mkdir(parents=True)
        for day in range(1, 6):
            (folder / f"dryrun-retail-all-202609{day:02d}-120000.zip").write_bytes(b"old")
        (folder / "dryrun-retail-ACCT1-20260904-120000-2.zip").write_bytes(b"old, other account")
        (folder / "dryrun-classic_era-all-20260901-120000.zip").write_bytes(b"other flavor")
        for day in range(1, 4):
            (folder / f"cleaned-retail-all-202609{day:02d}-120000.zip").write_bytes(b"real")
        (folder / "notes.txt").write_text("mine")
        with capture_events() as records:
            result = execute(self.proposal.items, self.retail, dry_run=True, backup=True,
                             backup_dir=self.backup_dir, now=WHEN, keep_backups=3)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted([
            "cleaned-retail-all-20260901-120000.zip", "cleaned-retail-all-20260902-120000.zip",
            "cleaned-retail-all-20260903-120000.zip", "dryrun-classic_era-all-20260901-120000.zip",
            "dryrun-retail-all-20260905-120000.zip", "dryrun-retail-ACCT1-20260904-120000-2.zip",
            "dryrun-retail-all-20260927-140311.zip", "notes.txt"]))
        self.assertEqual(len(result.dry_runs_pruned), 4)
        pruned = [r for r in records if r["event"] == "backup.dry_runs_pruned"]
        self.assertEqual(len(pruned), 1)
        self.assertEqual(pruned[0]["data"]["keep"], 3)

    def _old_cleaned_zips(self):
        folder = self.backup_dir / "cleaned"
        folder.mkdir(parents=True, exist_ok=True)
        for day in range(1, 5):
            (folder / f"cleaned-retail-all-202609{day:02d}-120000.zip").write_bytes(b"old")
        (folder / "cleaned-retail-ACCT1-20260904-120000-2.zip").write_bytes(b"old, other account")
        (folder / "cleaned-classic_era-all-20260901-120000.zip").write_bytes(b"other flavor")
        (folder / "dryrun-retail-all-20260901-120000.zip").write_bytes(b"dry run")
        (folder / "cleaned-retail-all-notes.zip").write_bytes(b"mine")
        (folder / "notes.txt").write_text("mine")
        return folder

    def test_keep_cleaned_zero_keeps_every_cleaned_zip(self):
        """#4: keep_cleaned 0 (the default) never prunes a cleaned-files zip."""
        folder = self._old_cleaned_zips()
        before = len(list(folder.iterdir()))
        result = execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                         backup_dir=self.backup_dir, now=WHEN)
        self.assertEqual(result.cleaned_pruned, [])
        self.assertEqual(len(list(folder.iterdir())), before + 1)

    def test_keep_cleaned_keeps_newest_per_flavor(self):
        """#4: a real clean keeps the flavor's newest keep_cleaned cleaned zips (any account), counting its own;
        other flavors, dry-run zips and files not named like a cleaned zip are untouched."""
        folder = self._old_cleaned_zips()
        with capture_events() as records:
            result = execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                             backup_dir=self.backup_dir, now=WHEN, keep_cleaned=2)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted([
            "cleaned-classic_era-all-20260901-120000.zip", "cleaned-retail-ACCT1-20260904-120000-2.zip",
            "cleaned-retail-all-20260927-140311.zip", "cleaned-retail-all-notes.zip",
            "dryrun-retail-all-20260901-120000.zip", "notes.txt"]))
        self.assertEqual(len(result.cleaned_pruned), 4)
        pruned = [r for r in records if r["event"] == "backup.cleaned_pruned"]
        self.assertEqual(len(pruned), 1)
        self.assertEqual(pruned[0]["data"]["keep"], 2)

    def test_keep_cleaned_never_deletes_the_zip_just_written(self):
        # An older zip with a stamp in the future (a clock that was wrong) must not push out this run's zip.
        folder = self._old_cleaned_zips()
        (folder / "cleaned-retail-all-20301231-235959.zip").write_bytes(b"future")
        result = execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                         backup_dir=self.backup_dir, now=WHEN, keep_cleaned=1)
        self.assertTrue(result.backup_path.exists())
        self.assertFalse((folder / "cleaned-retail-all-20301231-235959.zip").exists())
        self.assertEqual([p.name for p in folder.iterdir() if p.name.startswith("cleaned-retail-all-2")],
                         [result.backup_path.name])

    def test_result_names_the_cleaned_zips_removed(self):
        self._old_cleaned_zips()
        result = execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                         backup_dir=self.backup_dir, now=WHEN, keep_cleaned=2)
        self.assertTrue(dict(summary_rows(result))["Cleaned files zip"].endswith("(4 older cleaned zips removed)"))

    def test_dry_run_never_prunes_cleaned_zips(self):
        folder = self._old_cleaned_zips()
        result = execute(self.proposal.items, self.retail, dry_run=True, backup=True,
                         backup_dir=self.backup_dir, now=WHEN, keep_cleaned=1)
        self.assertEqual(result.cleaned_pruned, [])
        self.assertEqual(len([p for p in folder.iterdir() if p.name.startswith("cleaned-retail-")]), 6)

    def test_prune_cleaned_zips_keep_zero_or_missing_folder(self):
        self.assertEqual(prune_cleaned_zips(self.backup_dir, "retail", 1), [])  # no cleaned/ folder yet
        folder = self._old_cleaned_zips()
        self.assertEqual(prune_cleaned_zips(self.backup_dir, "retail", 0), [])
        self.assertEqual(len(prune_cleaned_zips(self.backup_dir, "retail", 1)), 4)
        self.assertTrue((folder / "cleaned-retail-ACCT1-20260904-120000-2.zip").exists())

    def test_keep_backups_zero_prunes_no_dry_run_zips_or_backups(self):
        """Feedback round 1: the global keep_backups 0 means keep all."""
        cleaned, backups = self.backup_dir / "cleaned", self.backup_dir / "backup"
        cleaned.mkdir(parents=True)
        backups.mkdir(parents=True)
        for day in range(1, 4):
            (cleaned / f"dryrun-retail-all-202609{day:02d}-120000.zip").write_bytes(b"old")
            (backups / f"backup-retail-202609{day:02d}-120000.zip").write_bytes(b"old")
        self.assertEqual(prune_dry_run_zips(self.backup_dir, "retail", 0), [])
        result = execute(self.proposal.items, self.retail, dry_run=True, backup=True,
                         backup_dir=self.backup_dir, now=WHEN, keep_backups=0)
        self.assertEqual(result.dry_runs_pruned, [])
        self.assertEqual(len(list(cleaned.iterdir())), 4)
        result = execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                         backup_dir=self.backup_dir, now=WHEN, keep_backups=0)
        self.assertEqual(result.pruned, [])
        self.assertEqual(len(list(backups.iterdir())), 4)

    def test_real_clean_prunes_no_dry_run_zips(self):
        folder = self.backup_dir / "cleaned"
        folder.mkdir(parents=True)
        for day in range(1, 4):
            (folder / f"dryrun-retail-all-202609{day:02d}-120000.zip").write_bytes(b"old")
        result = execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                         backup_dir=self.backup_dir, now=WHEN, keep_backups=1)
        self.assertEqual(result.dry_runs_pruned, [])
        self.assertEqual(len([p for p in folder.iterdir() if p.name.startswith("dryrun-")]), 3)

    def test_only_the_newest_backups_are_kept(self):
        folder = self.backup_dir / "backup"
        folder.mkdir(parents=True)
        for day in range(1, 7):
            (folder / f"backup-retail-202609{day:02d}-120000.zip").write_bytes(b"old")
        (folder / "backup-classic_era-20260901-120000.zip").write_bytes(b"other flavor")
        (folder / "notes.txt").write_text("mine")
        with capture_events() as records:
            result = execute(self.proposal.items, self.retail, dry_run=False, backup=True,
                             backup_dir=self.backup_dir, now=WHEN, keep_backups=3)
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["backup-classic_era-20260901-120000.zip", "backup-retail-20260905-120000.zip",
                          "backup-retail-20260906-120000.zip", "backup-retail-20260927-140311.zip", "notes.txt"])
        self.assertEqual(len(result.pruned), 4)
        self.assertIn("snapshot.pruned", [r["event"] for r in records])

    def test_a_clean_that_deletes_nothing_prunes_no_backups(self):
        # An earlier clean's Undo may need its WTF backup; a run whose every delete failed must not prune it.
        folder = self.backup_dir / "backup"
        folder.mkdir(parents=True)
        (folder / "backup-retail-20260901-120000.zip").write_bytes(b"old")

        original = Path.unlink

        def locked(path, *args, **kwargs):
            if "SavedVariables" in path.parts:
                raise PermissionError("locked by another program")
            return original(path, *args, **kwargs)

        with patch.object(Path, "unlink", locked):
            result = execute(self.proposal.items, self.retail, dry_run=False, backup=False,
                             backup_dir=self.backup_dir, now=WHEN, keep_backups=1)
        self.assertEqual(result.deleted, [])
        self.assertTrue(result.failed)
        self.assertEqual(result.pruned, [])
        self.assertTrue((folder / "backup-retail-20260901-120000.zip").exists())

    def test_dry_run_prunes_nothing(self):
        folder = self.backup_dir / "backup"
        folder.mkdir(parents=True)
        for day in range(1, 4):
            (folder / f"backup-retail-202609{day:02d}-120000.zip").write_bytes(b"old")
        execute(self.proposal.items, self.retail, dry_run=True, backup=True, backup_dir=self.backup_dir,
                now=WHEN, keep_backups=1)
        self.assertEqual(len(list(folder.iterdir())), 3)
