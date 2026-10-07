"""core/snapshot.py: the whole-WTF snapshot shared by the WTF Cleaner and the Ace3 Profile Manager."""
from __future__ import annotations

import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

from tests.fixtures import record_fsyncs, build_wow_tree
from wowtools.core import snapshot
from wowtools.core.install import WowInstall

WHEN = datetime(2026, 10, 4, 12, 0, 0)


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.flavor = WowInstall(build_wow_tree(self.tmp / "wow")).flavor("_retail_")

    def test_snapshot_is_fsynced_before_it_is_moved_into_place(self):
        """F-012: the WTF snapshot is on the disk before the run changes anything it holds."""
        with record_fsyncs(snapshot) as calls:
            out = snapshot.take_snapshot(self.flavor, self.tmp / "s", "snapshot", WHEN)
        size = out.stat().st_size
        self.assertEqual(calls, [("fsync", size), ("rename", size)])

    def test_prefix_and_folder_are_parameters(self):
        out = snapshot.take_snapshot(self.flavor, self.tmp / "out" / "snapshots", "snapshot", WHEN)
        self.assertEqual(out, self.tmp / "out" / "snapshots" / "snapshot-retail-20261004-120000.zip")
        with zipfile.ZipFile(out) as zf:
            self.assertIn("WTF/Account/ACCT1/SavedVariables/Details.lua", zf.namelist())

    def test_second_snapshot_in_the_same_second_gets_a_suffix(self):
        folder = self.tmp / "s"
        first = snapshot.take_snapshot(self.flavor, folder, "snapshot", WHEN)
        second = snapshot.take_snapshot(self.flavor, folder, "snapshot", WHEN)
        self.assertNotEqual(first, second)
        self.assertTrue(second.name.endswith("-2.zip"))

    def test_prune_keeps_newest_of_that_prefix_and_flavor_only(self):
        folder = self.tmp / "s"
        folder.mkdir()
        for name in ("snapshot-retail-20260101-000000.zip", "snapshot-retail-20260102-000000.zip",
                     "snapshot-retail-20260103-000000.zip", "snapshot-classic_era-20260101-000000.zip",
                     "backup-retail-20260101-000000.zip", "notes.txt"):
            (folder / name).write_bytes(b"x")
        removed = snapshot.prune_snapshots(folder, "snapshot", "retail", 2)
        self.assertEqual([p.name for p in removed], ["snapshot-retail-20260101-000000.zip"])
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["backup-retail-20260101-000000.zip", "notes.txt",
                          "snapshot-classic_era-20260101-000000.zip", "snapshot-retail-20260102-000000.zip",
                          "snapshot-retail-20260103-000000.zip"])

    def test_prune_keep_zero_or_less_keeps_all(self):
        """Feedback round 1: the global keep_backups 0 means keep all, never delete every snapshot."""
        folder = self.tmp / "s"
        folder.mkdir()
        for day in range(1, 4):
            (folder / f"snapshot-retail-2026010{day}-000000.zip").write_bytes(b"x")
        self.assertEqual(snapshot.prune_snapshots(folder, "snapshot", "retail", 0), [])
        self.assertEqual(snapshot.prune_snapshots(folder, "snapshot", "retail", -1), [])
        self.assertEqual(len(list(folder.iterdir())), 3)
