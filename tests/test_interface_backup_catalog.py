from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from wowtools.tools.interface_backup.catalog import list_backups, new_backup_path, prune_backups, prune_safety

NOW = datetime(2026, 10, 4, 15, 30, 12)


class CatalogTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "interface-backup"
        self.root.mkdir()

    def touch(self, name: str) -> Path:
        path = self.root / name
        path.write_bytes(b"z")
        return path

    def test_new_path_and_collision(self):
        first = new_backup_path(self.root, "retail", NOW)
        self.assertEqual(first.name, "backup-retail-20261004-153012.zip")
        first.write_bytes(b"z")
        self.assertEqual(new_backup_path(self.root, "retail", NOW).name, "backup-retail-20261004-153012-2.zip")
        self.assertEqual(new_backup_path(self.root, "retail", NOW, kind="pre-restore").name,
                         "pre-restore-retail-20261004-153012.zip")

    def test_info_fields(self):
        self.touch("backup-classic_era-20261003-010203-2.zip")
        (info,) = list_backups(self.root)
        self.assertEqual((info.kind, info.flavor_short, info.stamp, info.n, info.size),
                         ("backup", "classic_era", "20261003-010203", 2, 1))
        self.assertEqual(info.when, "2026-10-03 01:02:03")
        self.assertFalse(info.is_safety)

    def test_list_newest_first_filtered(self):
        self.touch("backup-retail-20261001-000000.zip")
        self.touch("backup-retail-20261002-000000.zip")
        self.touch("backup-retail-20261002-000000-2.zip")
        self.touch("backup-classic_era-20261003-000000.zip")
        self.touch("pre-restore-retail-20261003-000000.zip")
        self.touch("notes.txt")
        (self.root / "backup-retail-20261009-000000.zip").mkdir()  # a folder with a backup's name is not a backup
        names = [b.path.name for b in list_backups(self.root, {"retail"}, kinds=("backup",))]
        self.assertEqual(names, ["backup-retail-20261002-000000-2.zip", "backup-retail-20261002-000000.zip",
                                 "backup-retail-20261001-000000.zip"])
        everything = list_backups(self.root)
        self.assertEqual(len(everything), 5)
        self.assertTrue(everything[0].is_safety or everything[0].flavor_short == "classic_era")
        self.assertEqual(list_backups(self.root / "missing"), [])
        self.assertEqual(list_backups(None), [])

    def test_prune_per_flavor_never_safety_or_foreign(self):
        for day in range(1, 5):
            self.touch(f"backup-retail-2026100{day}-000000.zip")
        self.touch("backup-classic_era-20261001-000000.zip")
        self.touch("pre-restore-retail-20261001-000000.zip")
        self.touch("notes.txt")
        removed = prune_backups(self.root, "retail", 2)
        self.assertEqual(sorted(p.name for p in removed),
                         ["backup-retail-20261001-000000.zip", "backup-retail-20261002-000000.zip"])
        self.assertTrue((self.root / "backup-retail-20261004-000000.zip").exists())
        self.assertTrue((self.root / "backup-classic_era-20261001-000000.zip").exists())
        self.assertTrue((self.root / "pre-restore-retail-20261001-000000.zip").exists())
        self.assertTrue((self.root / "notes.txt").exists())
        self.assertEqual(prune_backups(self.root, "retail", 0), [])  # 0 = never delete

    def test_prune_protects_the_named_backup_whatever_its_stamp(self):
        new = self.touch("backup-retail-20261001-000000.zip")
        for day in (2, 3, 4):
            self.touch(f"backup-retail-2026100{day}-000000.zip")
        removed = prune_backups(self.root, "retail", 2, protect=new)
        self.assertTrue(new.exists())
        self.assertNotIn(new, removed)
        self.assertEqual(sorted(p.name for p in self.root.glob("backup-retail-*")),
                         ["backup-retail-20261001-000000.zip", "backup-retail-20261004-000000.zip"])
        self.assertEqual(prune_backups(self.root, "retail", 1, protect=new), [self.root / "backup-retail-20261004-000000.zip"])

    def test_prune_safety_deletes_only_the_names_given(self):
        keep = self.touch("pre-restore-retail-20261001-000000.zip")
        drop = self.touch("pre-restore-retail-20261002-000000.zip")
        protected = self.touch("pre-restore-retail-20261003-000000.zip")
        backup = self.touch("backup-retail-20261002-000000.zip")
        names = {drop.name, protected.name, backup.name}
        self.assertEqual(prune_safety(self.root, names, protect=self.root / protected.name), [drop])
        self.assertTrue(keep.exists())
        self.assertTrue(protected.exists())
        self.assertTrue(backup.exists())
        self.assertFalse(drop.exists())
