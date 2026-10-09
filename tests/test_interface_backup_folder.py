"""L16: Interface Backup keeps its zips in <root>/backup; only that folder counts."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tests.fixtures import build_interface_tree, build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.paths import to_stored
from wowtools.tools.interface_backup.backup import back_up
from wowtools.tools.interface_backup.catalog import (ZIPS_SUBDIR, list_backups, new_backup_path, prune_backups,
                                                     prune_safety, zips_dir)
from wowtools.tools.interface_backup.journal import read_restore_journal
from wowtools.tools.interface_backup.restore import RestoreError, open_backup, plan_restore, restore
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

    def test_only_the_backup_folder_is_listed(self):
        self.touch("backup-retail-20261001-000000.zip")  # loose in <root>: not a backup of this tool
        self.touch("backup-retail-20261002-000000.zip", self.zips)
        self.touch("pre-restore-retail-20261003-000000.zip", self.zips)
        self.touch("notes.txt", self.zips)
        self.assertEqual([b.path.name for b in list_backups(self.root)],
                         ["pre-restore-retail-20261003-000000.zip", "backup-retail-20261002-000000.zip"])

    def test_a_name_taken_in_root_is_not_avoided(self):
        self.touch("backup-retail-20261004-153012.zip")
        self.assertEqual(new_backup_path(self.root, "retail", NOW).name, "backup-retail-20261004-153012.zip")
        self.touch("backup-retail-20261004-153012.zip", self.zips)
        self.assertEqual(new_backup_path(self.root, "retail", NOW).name, "backup-retail-20261004-153012-2.zip")

    def test_pruning_touches_only_the_backup_folder_and_spares_safety_zips(self):
        loose = self.touch("backup-retail-20261001-000000.zip")
        old = self.touch("backup-retail-20261002-000000.zip", self.zips)
        mid = self.touch("backup-retail-20261003-000000.zip", self.zips)
        new = self.touch("backup-retail-20261004-000000.zip", self.zips)
        safety = self.touch("pre-restore-retail-20261000-000000.zip", self.zips)
        self.assertEqual(prune_backups(self.root, "retail", 2, protect=new), [old])
        self.assertTrue(loose.exists() and mid.exists() and new.exists() and safety.exists())

    def test_prune_safety_touches_only_the_backup_folder(self):
        loose = self.touch("pre-restore-retail-20261001-000000.zip")
        named = self.touch("pre-restore-retail-20261002-000000.zip", self.zips)
        kept = self.touch("pre-restore-retail-20261003-000000.zip", self.zips)
        self.assertEqual(prune_safety(self.root, {loose.name, named.name}), [named])
        self.assertTrue(loose.exists() and kept.exists())


class FolderRunTest(unittest.TestCase):
    """Backups, restores and Undo with their zips in <root>/backup."""

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

    def test_backup_and_safety_zips_go_to_the_backup_folder(self):
        backup = self.back_up()
        self.assertEqual(backup.parent, self.root / "backup")
        result = self.restore(backup)
        self.assertEqual(result.safety_zip.parent, self.root / "backup")

    def test_undo_refuses_a_safety_zip_outside_the_backup_folder(self):
        """A journal naming a safety zip in <root> itself (not <root>/backup) is refused, nothing changed."""
        (self.retail / "WTF" / "Config.wtf").write_bytes(b"mine")
        result = self.restore(self.back_up())
        outside = self.root / result.safety_zip.name
        result.safety_zip.rename(outside)
        records = [json.loads(line) for line in result.journal_path.read_text(encoding="utf-8").splitlines()]
        for record in records:
            if record.get("action") == "safety_backup":
                record["zip"] = to_stored(outside)
        result.journal_path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        entry = next(e for e in read_restore_journal(result.journal_path).entries if e["action"] == "safety_backup")
        self.assertEqual(entry["zip"], outside)
        restored = (self.retail / "WTF" / "Config.wtf").read_bytes()
        with capture_events(), self.assertRaisesRegex(RestoreError, "not in the backup folder"):
            undo_restore(result.journal_path, wow_root=self.wow, root=self.root)
        self.assertEqual((self.retail / "WTF" / "Config.wtf").read_bytes(), restored)


if __name__ == "__main__":
    unittest.main()
