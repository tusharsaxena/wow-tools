from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from datetime import date
from pathlib import Path

from tests.fixtures import SHOT_BYTES, build_screenshot_tree, build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.screenshot_organizer.organizer import execute
from wowtools.tools.screenshot_organizer.planner import CONFLICT, FILED, MAYBE_DUPLICATE, NEW, scan, waiting_count


class PlannerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_screenshot_tree(build_wow_tree(self.tmp / "World of Warcraft"))
        self.install = WowInstall(self.root)
        self.retail = self.install.flavor("retail")
        self.era = self.install.flavor("classic_era")
        self.shots = self.root / "_retail_" / "Screenshots"

    def test_in_place_plan(self):
        plan = scan([self.retail], None)
        [fp] = plan.flavors
        self.assertEqual(fp.target_root, self.shots)
        self.assertEqual(sorted(i.src.name for i in fp.items), sorted(n for n, d in SHOT_BYTES.items()
                                                                     if not d.startswith(b"era")))
        item = next(i for i in fp.items if i.src.name == "WoWScrnShot_073119_232713.jpg")
        self.assertEqual(item.dst, self.shots / "2019" / "07" / "31" / "WoWScrnShot_073119_232713.jpg")
        self.assertEqual((item.day, item.size, item.state), (date(2019, 7, 31), 6, NEW))
        self.assertEqual(sorted(s.path.name for s in fp.skipped), ["WoWScrnShot_023119_120000.jpg", "notes.txt"])
        self.assertTrue(all(s.reason == "name not recognised" for s in fp.skipped))

    def test_already_filed_folders_are_not_rescanned(self):
        plan = scan([self.retail], None)
        self.assertNotIn("WoWScrnShot_010225_090000.jpg", [i.src.name for i in plan.items])

    def test_external_plan_and_flavor_folder_names(self):
        dest = self.tmp / "arch"
        plan = scan([self.retail, self.era], dest)
        self.assertEqual([fp.target_root for fp in plan.flavors], [dest / "_retail_", dest / "_classic_era_"])
        era_item = plan.flavors[1].items[0]
        self.assertEqual(era_item.dst.parent, dest / "_classic_era_" / "2020" / "12" / "05")

    def test_existing_targets_are_duplicates_or_conflicts(self):
        dest = self.tmp / "arch"
        day = dest / "_retail_" / "2019" / "07" / "31"
        day.mkdir(parents=True)
        (day / "WoWScrnShot_073119_232713.jpg").write_bytes(b"shot-a")       # same size
        (day / "WoWScrnShot_073119_232800.jpg").write_bytes(b"different!")   # other size
        plan = scan([self.retail], dest)
        states = {i.src.name: i.state for i in plan.items}
        self.assertEqual(states["WoWScrnShot_073119_232713.jpg"], MAYBE_DUPLICATE)
        self.assertEqual(states["WoWScrnShot_073119_232800.jpg"], CONFLICT)
        self.assertEqual(len(plan.selectable), len(plan.items) - 1)

    def test_flavor_without_screenshots_is_listed_with_nothing_to_do(self):
        anniversary = self.install.flavor("anniversary")
        plan = scan([anniversary, self.retail], None)
        self.assertEqual([fp.flavor.folder for fp in plan.flavors], ["_anniversary_", "_retail_"])
        self.assertTrue(plan.flavors[0].missing)
        self.assertEqual((plan.flavors[0].items, plan.flavors[0].skipped), ([], []))
        self.assertFalse(plan.flavors[1].missing)
        self.assertEqual(len(plan.selectable), 4)

    def test_progress_and_events(self):
        calls = []
        with capture_events() as records:
            scan([self.retail, self.era], None, progress=lambda *a: calls.append(a))
        self.assertEqual(calls[0][:2], (0, 2))
        self.assertEqual(calls[-1][:2], (2, 2))
        names = [r["event"] for r in records]
        self.assertEqual(names[0], "shots.scan_started")
        done = next(r for r in records if r["event"] == "shots.scan_completed")
        self.assertEqual(done["data"]["flavors"]["_retail_"]["to_file"], 4)
        self.assertEqual(done["data"]["flavors"]["_retail_"]["unrecognised"], 2)

    def test_unreadable_folder_is_a_warning(self):
        self.assertEqual(scan([self.retail], None).warnings, [])
        with unittest.mock.patch("wowtools.tools.screenshot_organizer.planner.list_files",
                                 side_effect=PermissionError(13, "denied")):
            with capture_events() as records:
                plan = scan([self.retail, self.era], None)
        self.assertEqual(len(plan.warnings), 2)
        self.assertEqual([fp.items for fp in plan.flavors], [[], []])
        self.assertTrue(all(fp.error for fp in plan.flavors))
        self.assertIn("shots.scan_warning", [r["event"] for r in records])

    def test_target_day_folders_are_listed_by_name_only(self):
        day = self.shots / "2019" / "07" / "31"
        day.mkdir(parents=True)
        for n in range(5):
            (day / f"WoWScrnShot_073119_10000{n}.jpg").write_bytes(b"old")
        (day / "WoWScrnShot_073119_232713.jpg").write_bytes(b"shot-a")
        real_stat = __import__("os").stat
        stats = []

        def counting_stat(path, *a, **k):
            stats.append(Path(path).name)
            return real_stat(path, *a, **k)

        with unittest.mock.patch("wowtools.tools.screenshot_organizer.planner.os.stat", counting_stat):
            plan = scan([self.retail], None)
        item = next(i for i in plan.items if i.src.name == "WoWScrnShot_073119_232713.jpg")
        self.assertEqual(item.state, MAYBE_DUPLICATE)
        shot_stats = [n for n in stats if n.startswith("WoWScrnShot")]
        self.assertEqual(shot_stats, ["WoWScrnShot_073119_232713.jpg"])  # only the name already at the target

    def copy_all(self, dest):
        plan = scan([self.retail, self.era], dest, copy=True)
        result = execute(plan.selectable, dest_dir=dest, copy=True, dry_run=False, journal_dir=self.tmp / "j",
                         keep_journals=10)
        self.assertEqual(result.count("copied"), 6)

    def test_copy_mode_in_place_filed_copies_are_not_waiting(self):
        """F-027: in copy mode the originals stay; their identical filed copies make them already filed."""
        self.assertEqual(waiting_count(self.retail, None, copy=True), 4)
        self.copy_all(None)
        plan = scan([self.retail, self.era], None, copy=True)
        self.assertEqual({i.state for i in plan.items}, {FILED})
        self.assertEqual([len(fp.filed) for fp in plan.flavors], [4, 2])
        self.assertEqual([fp.to_file for fp in plan.flavors], [[], []])
        self.assertEqual(len(plan.selectable), 6)  # can still be ticked by hand
        self.assertEqual(waiting_count(self.retail, None, copy=True), 0)
        self.assertEqual(waiting_count(self.era, None, copy=True), 0)
        self.assertEqual(waiting_count(self.retail), 4)  # move mode counts names only, as before

    def test_copy_mode_with_destination_filed_copies_are_not_waiting(self):
        dest = self.tmp / "arch"
        self.copy_all(dest)
        plan = scan([self.retail], dest, copy=True)
        self.assertEqual({i.state for i in plan.items}, {FILED})
        self.assertEqual(waiting_count(self.retail, dest, copy=True), 0)

    def test_filed_needs_same_size_and_copy_mode(self):
        """R3: a same-size filed copy with another modified time (a copy that did not keep it) is filed too, so the
        picker's count and the review screen agree."""
        self.copy_all(None)
        filed = self.shots / "2019" / "07" / "31" / "WoWScrnShot_073119_232713.jpg"
        __import__("os").utime(filed, (1_000_000_000, 1_000_000_000))  # same size, other time
        plan = scan([self.retail], None, copy=True)
        states = {i.src.name: i.state for i in plan.items}
        self.assertEqual(states["WoWScrnShot_073119_232713.jpg"], FILED)
        self.assertEqual(len(plan.to_file), 0)
        self.assertEqual(waiting_count(self.retail, None, copy=True), len(plan.to_file))
        # Move mode: a same-name file at the target is a possible duplicate to remove, never "filed".
        self.assertEqual({i.state for i in scan([self.retail], None).items}, {MAYBE_DUPLICATE})
        # A filed copy of another size is a conflict and is not waiting either.
        (self.shots / "2019" / "08" / "01" / "WoWScrnShot_080119_101010.PNG").write_bytes(b"other size")
        self.assertEqual(waiting_count(self.retail, None, copy=True), 0)
        self.assertEqual(len(scan([self.retail], None, copy=True).to_file), 0)

    def test_scan_completed_counts_filed(self):
        self.copy_all(None)
        with capture_events() as records:
            scan([self.retail], None, copy=True)
        done = next(r for r in records if r["event"] == "shots.scan_completed")
        self.assertEqual(done["data"]["flavors"]["_retail_"]["already_filed"], 4)
        self.assertEqual(done["data"]["flavors"]["_retail_"]["to_file"], 0)
