"""L16: Interface Backup keeps its zips in <root>/backup, and moves the ones an older version left in <root> there."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import build_interface_tree, build_wow_tree
from wowtools.core import activity
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.paths import to_stored
from wowtools.tools.interface_backup import catalog
from wowtools.tools.interface_backup.backup import back_up
from wowtools.tools.interface_backup.catalog import (ZIPS_SUBDIR, list_backups, move_old_zips, new_backup_path,
                                                     prune_backups, prune_safety, zips_dir)
from wowtools.tools.interface_backup.journal import read_restore_journal
from wowtools.tools.interface_backup.restore import open_backup, plan_restore, restore
from wowtools.tools.interface_backup.scanner import scan_flavor
from wowtools.tools.interface_backup.undo import undo_restore

NOW = datetime(2026, 10, 4, 15, 30, 12)


class FolderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "interface-backup"
        self.root.mkdir()
        self.zips = self.root / "backup"

    def touch(self, name: str, folder: Path | None = None) -> Path:
        path = (folder or self.root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        return path

    def test_backup_sub_folder(self):
        self.assertEqual(ZIPS_SUBDIR, "backup")
        self.assertEqual(zips_dir(self.root), self.zips)

    def test_new_zips_go_to_the_backup_folder(self):
        self.assertEqual(new_backup_path(self.root, "retail", NOW), self.zips / "backup-retail-20261004-153012.zip")
        self.assertEqual(new_backup_path(self.root, "retail", NOW, kind="pre-restore"),
                         self.zips / "pre-restore-retail-20261004-153012.zip")

    def test_a_name_taken_in_the_old_place_is_not_reused(self):
        self.touch("backup-retail-20261004-153012.zip")  # not moved yet
        self.assertEqual(new_backup_path(self.root, "retail", NOW).name, "backup-retail-20261004-153012-2.zip")
        self.touch("backup-retail-20261004-153012-2.zip", self.zips)
        self.assertEqual(new_backup_path(self.root, "retail", NOW).name, "backup-retail-20261004-153012-3.zip")

    def test_listing_sees_both_places(self):
        self.touch("backup-retail-20261001-000000.zip")
        self.touch("backup-retail-20261002-000000.zip", self.zips)
        self.touch("pre-restore-retail-20261003-000000.zip")
        self.touch("notes.txt")
        found = list_backups(self.root)
        self.assertEqual([(b.path.parent.name, b.path.name) for b in found],
                         [("interface-backup", "pre-restore-retail-20261003-000000.zip"),
                          ("backup", "backup-retail-20261002-000000.zip"),
                          ("interface-backup", "backup-retail-20261001-000000.zip")])

    def test_pruning_spans_both_places_and_spares_safety_zips(self):
        old1 = self.touch("backup-retail-20261001-000000.zip")
        new2 = self.touch("backup-retail-20261002-000000.zip", self.zips)
        old3 = self.touch("backup-retail-20261003-000000.zip")
        new4 = self.touch("backup-retail-20261004-000000.zip", self.zips)
        safety = self.touch("pre-restore-retail-20261000-000000.zip")
        safety_new = self.touch("pre-restore-retail-20261000-000001.zip", self.zips)
        self.assertEqual(prune_backups(self.root, "retail", 2, protect=new4), [new2, old1])
        self.assertTrue(old3.exists() and new4.exists() and safety.exists() and safety_new.exists())

    def test_prune_safety_spans_both_places(self):
        old = self.touch("pre-restore-retail-20261001-000000.zip")
        new = self.touch("pre-restore-retail-20261002-000000.zip", self.zips)
        kept = self.touch("pre-restore-retail-20261003-000000.zip", self.zips)
        self.assertEqual(sorted(prune_safety(self.root, {old.name, new.name})), sorted([old, new]))
        self.assertTrue(kept.exists())

    def test_move_old_zips(self):
        backup = self.touch("backup-retail-20261001-000000.zip")
        safety = self.touch("pre-restore-classic_era-20261002-000000.zip")
        other = self.touch("notes.txt")
        partial = self.touch("backup-retail-20261003-000000.zip.partial")
        journal = self.touch("restore-x.jsonl", self.root / "journal")
        with capture_events() as events:
            result = move_old_zips(self.root)
        self.assertEqual(sorted(result.moved), [backup.name, safety.name])
        self.assertEqual(result.taken, [])
        self.assertEqual(result.failed, [])
        self.assertEqual((self.zips / backup.name).read_bytes(), backup.name.encode())
        self.assertTrue((self.zips / safety.name).exists())
        self.assertFalse(backup.exists() or safety.exists())
        self.assertTrue(other.exists() and partial.exists() and journal.exists())
        moved = [e for e in events if e["event"] == "ibackup.zips_moved"]
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["level"], "info")
        self.assertEqual(moved[0]["data"]["moved"], 2)
        self.assertEqual(moved[0]["data"]["folder"], to_stored(self.zips))
        with capture_events() as events:
            self.assertIsNone(move_old_zips(self.root))  # once: nothing left to move, nothing logged
        self.assertEqual(events, [])

    def test_move_leaves_a_taken_name_in_place(self):
        taken = self.touch("backup-retail-20261001-000000.zip")
        self.zips.mkdir()
        (self.zips / taken.name).write_bytes(b"newer")
        free = self.touch("backup-retail-20261002-000000.zip")
        with capture_events() as events:
            result = move_old_zips(self.root)
        self.assertEqual(result.moved, [free.name])
        self.assertEqual(result.taken, [taken.name])
        self.assertEqual(taken.read_bytes(), taken.name.encode())  # left where it was
        self.assertEqual((self.zips / taken.name).read_bytes(), b"newer")  # never replaced
        moved = [e for e in events if e["event"] == "ibackup.zips_moved"]
        self.assertEqual(moved[0]["level"], "warning")
        self.assertEqual(moved[0]["data"]["taken"], [taken.name])
        self.assertIn(taken.name, [b.path.name for b in list_backups(self.root) if b.path.parent == self.root])

    def test_a_taken_name_is_listed_in_both_places(self):
        """Left in place, the old zip and the one in backup/ are two rows of the same name under Backups."""
        taken = self.touch("backup-retail-20261001-000000.zip")
        newer = self.touch(taken.name, self.zips)
        move_old_zips(self.root)
        self.assertEqual(sorted(str(b.path) for b in list_backups(self.root) if b.path.name == taken.name),
                         sorted([str(taken), str(newer)]))

    def test_a_zip_left_in_place_is_reported_once(self):
        """The move is tried on every scan; a zip it leaves is logged the first time only, a new one again."""
        taken = self.touch("backup-retail-20261001-000000.zip")
        self.touch(taken.name, self.zips)
        with capture_events() as events:
            self.assertEqual(move_old_zips(self.root).taken, [taken.name])
            self.assertEqual(move_old_zips(self.root).taken, [taken.name])  # tried again, not logged again
        self.assertEqual(len([e for e in events if e["event"] == "ibackup.zips_moved"]), 1)
        second = self.touch("backup-retail-20261002-000000.zip")
        self.touch(second.name, self.zips)
        with capture_events() as events:
            move_old_zips(self.root)
        moved = [e for e in events if e["event"] == "ibackup.zips_moved"]
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["data"]["taken"], [taken.name, second.name])

    def test_a_failing_move_is_retried_and_reported_once(self):
        stuck = self.touch("backup-retail-20261001-000000.zip")
        real = catalog.rename_no_replace

        def refuse(src, dst):
            raise PermissionError(13, "read-only", str(src))

        with capture_events() as events:
            with patch.object(catalog, "rename_no_replace", refuse):
                self.assertEqual(len(move_old_zips(self.root).failed), 1)
                self.assertEqual(len(move_old_zips(self.root).failed), 1)
            self.assertEqual(len([e for e in events if e["event"] == "ibackup.zips_moved"]), 1)
            with patch.object(catalog, "rename_no_replace", real):
                self.assertEqual(move_old_zips(self.root).moved, [stuck.name])  # the retry that works is logged
        self.assertEqual([e["level"] for e in events if e["event"] == "ibackup.zips_moved"], ["warning", "info"])
        self.assertTrue((self.zips / stuck.name).exists())

    def test_the_move_runs_inside_activity_running(self):
        """STD-5.19: renaming the user's zips is file-changing work; suite.run()'s wait_idle() waits for it."""
        self.touch("backup-retail-20261001-000000.zip")
        seen = []
        real = catalog.rename_no_replace

        def rename(src, dst):
            seen.append(activity.wait_idle(0))
            real(src, dst)

        with patch.object(catalog, "rename_no_replace", rename):
            move_old_zips(self.root)
        self.assertEqual(seen, [False])
        self.assertTrue(activity.wait_idle(0))

    def test_a_linked_backup_folder_is_followed_like_new_backups(self):
        """The same rule as new_backup_path and the zip writers: a backup/ that is a link to a folder is used."""
        elsewhere = self.root.parent / "elsewhere"
        elsewhere.mkdir()
        try:
            self.zips.symlink_to(elsewhere, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks not available")
        old = self.touch("backup-retail-20261001-000000.zip")
        result = move_old_zips(self.root)
        self.assertEqual((result.moved, result.failed), ([old.name], []))
        self.assertTrue((elsewhere / old.name).exists())
        self.assertEqual(new_backup_path(self.root, "retail", NOW).parent, self.zips)

    def test_a_failing_move_is_left_in_place_and_reported(self):
        stuck = self.touch("backup-retail-20261001-000000.zip")
        fine = self.touch("backup-retail-20261002-000000.zip")
        real = catalog.rename_no_replace

        def rename(src, dst):
            if Path(src).name == stuck.name:
                raise PermissionError(13, "read-only", str(src))
            real(src, dst)

        with patch.object(catalog, "rename_no_replace", rename), capture_events() as events:
            result = move_old_zips(self.root)
        self.assertEqual(result.moved, [fine.name])
        self.assertEqual(len(result.failed), 1)
        self.assertIn(stuck.name, result.failed[0])
        self.assertTrue(stuck.exists())
        moved = [e for e in events if e["event"] == "ibackup.zips_moved"]
        self.assertEqual(moved[0]["level"], "warning")
        self.assertEqual(len(moved[0]["data"]["failed"]), 1)

    def test_backup_folder_that_cannot_be_made(self):
        old = self.touch("backup-retail-20261001-000000.zip")
        self.zips.write_bytes(b"a file where the folder goes")
        with capture_events() as events:
            result = move_old_zips(self.root)
        self.assertEqual(result.moved, [])
        self.assertEqual(len(result.failed), 1)
        self.assertTrue(old.exists())
        self.assertEqual([e["level"] for e in events if e["event"] == "ibackup.zips_moved"], ["warning"])

    def test_nothing_to_move(self):
        with capture_events() as events:
            self.assertIsNone(move_old_zips(None))
            self.assertIsNone(move_old_zips(self.root / "missing"))
            self.assertIsNone(move_old_zips(self.root))
        self.assertEqual(events, [])
        self.assertFalse(self.zips.exists())  # no empty folder made for nothing


class FolderRunTest(unittest.TestCase):
    """Backups, restores and Undo with zips in both places."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.wow = build_interface_tree(build_wow_tree(self.tmp / "WoW"))
        self.flavor = next(f for f in WowInstall(self.wow).flavors() if f.folder == "_retail_")
        self.retail = self.wow / "_retail_"
        self.root = self.tmp / "bk" / "interface-backup"
        self.journal_dir = self.wow / "wow-tools" / "interface-backup" / "journal"

    def back_up(self) -> Path:
        with capture_events():
            return back_up(scan_flavor(self.flavor, with_stats=False), self.root, keep=10, now=NOW).path

    def restore(self, backup: Path):
        plan = plan_restore(open_backup(backup), scan_flavor(self.flavor, with_stats=True), ("Interface", "WTF"))
        with capture_events():
            return restore(plan, root=self.root, journal_dir=self.journal_dir, keep_journals=10)

    def to_old_place(self, path: Path) -> Path:
        """Put a zip where an older version wrote it (<root>, not <root>/backup)."""
        old = self.root / path.name
        path.rename(old)
        return old

    def test_backup_and_safety_zips_go_to_the_backup_folder(self):
        backup = self.back_up()
        self.assertEqual(backup.parent, self.root / "backup")
        result = self.restore(backup)
        self.assertEqual(result.safety_zip.parent, self.root / "backup")

    def test_restore_from_a_moved_zip(self):
        old = self.to_old_place(self.back_up())
        (self.retail / "WTF" / "Config.wtf").write_bytes(b"changed")
        with capture_events():
            move_old_zips(self.root)
        [info] = list_backups(self.root, {"retail"})
        self.assertEqual(info.path, self.root / "backup" / old.name)
        result = self.restore(info.path)
        self.assertTrue(result.ok)
        self.assertNotEqual((self.retail / "WTF" / "Config.wtf").read_bytes(), b"changed")

    def test_restore_from_a_zip_not_moved_yet(self):
        old = self.to_old_place(self.back_up())
        [info] = list_backups(self.root, {"retail"})
        self.assertEqual(info.path, old)
        self.assertTrue(self.restore(info.path).ok)

    def old_run(self) -> tuple[Path, Path]:
        """A restore an older version made: its safety zip in <root>, its journal naming that path."""
        (self.retail / "WTF" / "Config.wtf").write_bytes(b"mine")
        result = self.restore(self.back_up())
        old = self.to_old_place(result.safety_zip)
        lines = result.journal_path.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines]
        for record in records:
            if record.get("action") == "safety_backup":
                record["zip"] = to_stored(old)
        result.journal_path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        entry = next(e for e in read_restore_journal(result.journal_path).entries if e["action"] == "safety_backup")
        self.assertEqual(entry["zip"], old)
        return result.journal_path, old

    def test_undo_of_an_older_run_finds_its_moved_zip(self):
        journal, old = self.old_run()
        with capture_events():
            move_old_zips(self.root)
        self.assertFalse(old.exists())
        with capture_events():
            undone = undo_restore(journal, wow_root=self.wow, root=self.root)
        self.assertTrue(undone.ok)
        self.assertEqual(undone.backup, self.root / "backup" / old.name)
        self.assertEqual((self.retail / "WTF" / "Config.wtf").read_bytes(), b"mine")

    def test_undo_of_an_older_run_before_the_move(self):
        journal, old = self.old_run()
        with capture_events():
            undone = undo_restore(journal, wow_root=self.wow, root=self.root)
        self.assertTrue(undone.ok)
        self.assertEqual(undone.backup, old)
        self.assertEqual((self.retail / "WTF" / "Config.wtf").read_bytes(), b"mine")

    def test_pruning_after_a_backup_spans_both_places(self):
        for day in (1, 2):
            path = self.root / f"backup-retail-2026100{day}-000000.zip"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"z")
        safety = self.root / "pre-restore-retail-20261001-000000.zip"
        safety.write_bytes(b"z")
        with capture_events():
            outcome = back_up(scan_flavor(self.flavor, with_stats=False), self.root, keep=2, now=NOW)
        self.assertEqual([p.name for p in outcome.pruned], ["backup-retail-20261001-000000.zip"])
        self.assertTrue((self.root / "backup-retail-20261002-000000.zip").exists())
        self.assertTrue(safety.exists())


if __name__ == "__main__":
    unittest.main()
