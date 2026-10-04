from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_interface_tree, build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.interface_backup.scanner import PARTS, leftover_folders, scan_flavor, scan_flavors


class ScannerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_interface_tree(build_wow_tree(self.tmp / "WoW"))
        self.flavors = {f.folder: f for f in WowInstall(self.root).flavors()}

    def link(self, target: Path, link: Path) -> None:
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")

    def test_parts_files_and_sizes(self):
        scan = scan_flavor(self.flavors["_retail_"], with_stats=True)
        self.assertEqual(tuple(scan.parts), PARTS)
        files = {f.rel: f for f in scan.parts["Interface"].files}
        self.assertEqual(files["AddOns/Auctionator/Auctionator.lua"].size, 3)
        self.assertIsNotNone(files["AddOns/Auctionator/Auctionator.lua"].mtime)
        self.assertIn("Config.wtf", [f.rel for f in scan.parts["WTF"].files])
        self.assertTrue(scan.has_data)
        self.assertEqual(scan.size, sum(p.size for p in scan.parts.values()))
        self.assertEqual(scan.file_count, sum(len(p.files) for p in scan.parts.values()))
        self.assertEqual(scan.link_count, 0)

    def test_without_stats_sizes_unknown(self):
        scan = scan_flavor(self.flavors["_retail_"], with_stats=False)
        self.assertIsNone(scan.size)
        self.assertIsNone(scan.parts["WTF"].size)
        self.assertGreater(scan.file_count, 0)

    def test_missing_parts(self):
        scan = scan_flavor(self.flavors["_anniversary_"], with_stats=True)
        self.assertFalse(scan.parts["Interface"].exists)
        self.assertTrue(scan.parts["WTF"].exists)
        self.assertTrue(scan.has_data)
        empty = scan_flavor(self.flavors["_ptr_"], with_stats=True)
        self.assertFalse(empty.has_data)
        self.assertEqual((empty.file_count, empty.size), (0, 0))

    def test_only_chosen_parts(self):
        scan = scan_flavor(self.flavors["_retail_"], with_stats=True, parts=("WTF",))
        self.assertFalse(scan.parts["Interface"].exists)
        self.assertEqual(scan.parts["Interface"].files, [])
        self.assertTrue(scan.parts["WTF"].exists)

    def test_links_not_followed(self):
        repo = self.tmp / "repo"
        (repo / "deep").mkdir(parents=True)
        (repo / "deep" / "x.lua").write_text("x", encoding="utf-8")
        self.link(repo, self.root / "_retail_" / "Interface" / "AddOns" / "Dev")
        scan = scan_flavor(self.flavors["_retail_"], with_stats=True)
        part = scan.parts["Interface"]
        self.assertEqual(part.links, ["AddOns/Dev"])
        self.assertFalse(any(f.rel.startswith("AddOns/Dev/") for f in part.files))
        self.assertEqual(scan.link_count, 1)

    def test_part_that_is_a_link_is_not_scanned(self):
        target = self.tmp / "ext-wtf"
        target.mkdir()
        (target / "a.txt").write_text("a", encoding="utf-8")
        era = self.root / "_classic_era_"
        os.rename(era / "WTF", self.tmp / "old-wtf")
        self.link(target, era / "WTF")
        with capture_events() as events:
            (scan,) = scan_flavors([self.flavors["_classic_era_"]], with_stats=True)
        part = scan.parts["WTF"]
        self.assertTrue(part.linked)
        self.assertFalse(part.exists)
        self.assertEqual(part.files, [])
        self.assertTrue(part.errors)
        warnings = [e for e in events if e["event"] == "ibackup.scan_warning"]
        self.assertEqual([e["data"]["part"] for e in warnings], ["WTF"])

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "permission bits do not stop this user")
    def test_unreadable_folder_is_skipped_and_reported(self):
        locked = self.root / "_retail_" / "Interface" / "AddOns" / "Details"
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)
        with capture_events() as events:
            (scan,) = scan_flavors([self.flavors["_retail_"]], with_stats=True)
        part = scan.parts["Interface"]
        self.assertTrue(part.exists)
        self.assertEqual(len(part.errors), 1)
        self.assertFalse(any(f.rel.startswith("AddOns/Details/") for f in part.files))
        self.assertIn("AddOns/Auctionator/Auctionator.lua", [f.rel for f in part.files])
        self.assertIn("ibackup.scan_warning", [e["event"] for e in events])

    def test_leftovers_and_events(self):
        leftover = self.root / "_retail_" / "Interface.replaced"
        leftover.mkdir()
        self.assertEqual(leftover_folders(self.flavors["_retail_"]), [leftover])
        with capture_events() as events:
            scans = scan_flavors([self.flavors["_retail_"]], with_stats=True)
        self.assertEqual(scans[0].leftovers, [leftover])
        names = [e["event"] for e in events]
        self.assertIn("ibackup.scan_started", names)
        self.assertIn("ibackup.scan_completed", names)
        self.assertIn("ibackup.leftover_found", names)
        completed = next(e for e in events if e["event"] == "ibackup.scan_completed")
        self.assertEqual(completed["data"]["flavor"], "_retail_")
        self.assertEqual(completed["data"]["parts"]["WTF"]["files"], len(scans[0].parts["WTF"].files))

    def test_progress_called(self):
        calls = []
        scan_flavor(self.flavors["_retail_"], with_stats=False, progress=lambda *a: calls.append(a))
        self.assertTrue(calls)
        self.assertEqual({c[0] for c in calls}, {"scan"})
        self.assertEqual({c[2] for c in calls}, {0})

    def test_broken_progress_does_not_stop_scan(self):
        def broken(*_args):
            raise RuntimeError("display gone")
        scan = scan_flavor(self.flavors["_retail_"], with_stats=False, progress=broken)
        self.assertGreater(scan.file_count, 0)


if __name__ == "__main__":
    unittest.main()
