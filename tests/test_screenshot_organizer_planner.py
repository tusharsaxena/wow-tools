import tempfile
import unittest
import unittest.mock
from datetime import date
from pathlib import Path

from tests.fixtures import SHOT_BYTES, build_screenshot_tree, build_wow_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.screenshot_organizer.planner import CONFLICT, MAYBE_DUPLICATE, NEW, scan


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
