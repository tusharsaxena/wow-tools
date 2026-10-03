import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_wow_tree
from wowtools.core.backup import BackupError
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.wtf_cleaner import multi
from wowtools.tools.wtf_cleaner.cleaner import CleanError
from wowtools.tools.wtf_cleaner.multi import execute_flavors, scan_flavors
from wowtools.tools.wtf_cleaner.rules import Criteria, evaluate


class MultiFlavorTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.era_sv = self.root / "_classic_era_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        (self.era_sv / "Gone.lua").write_text("x")  # not installed in Classic Era: something to clean there
        self.retail_sv = self.root / "_retail_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        self.install = WowInstall(self.root)
        self.backup_dir = self.tmp / "bk"

    def plan(self):
        scans = scan_flavors(self.install.flavors())
        return [(s.flavor, evaluate(s.result, Criteria(), log=False).items) for s in scans if s.result]

    def test_scan_flavors_lists_failures_and_names_the_flavor_in_progress(self):
        labels = []
        with capture_events():
            scans = scan_flavors(self.install.flavors(), progress=lambda c, t, label: labels.append(label))
        self.assertEqual([s.flavor.folder for s in scans], ["_anniversary_", "_classic_era_", "_retail_"])
        self.assertIsNone(scans[0].result)
        self.assertIn("No addons found", scans[0].error)
        self.assertIsNone(scans[1].error)
        self.assertEqual(scans[2].result.account_names, ("ACCT1", "ACCT2"))
        self.assertTrue(any(label.startswith("Classic Era · ") for label in labels))
        self.assertTrue(any(label.startswith("Retail · ") for label in labels))

    def test_single_flavor_progress_labels_are_unchanged(self):
        labels = []
        scan_flavors([self.install.flavor("retail")], progress=lambda c, t, label: labels.append(label))
        self.assertEqual(labels[0], "Reading AddOns")

    def test_dry_run_across_flavors_deletes_nothing(self):
        flavors = []
        result = execute_flavors(self.plan(), dry_run=True, backup=True, backup_dir=self.backup_dir,
                                 on_flavor=lambda flavor, index, count: flavors.append((flavor.folder, index, count)))
        self.assertEqual(flavors, [("_classic_era_", 0, 2), ("_retail_", 1, 2)])
        self.assertTrue(result.dry_run)
        self.assertEqual([r.status for r in result.runs], ["done", "done"])
        self.assertEqual(len(result.would_delete), 9)
        self.assertEqual(result.deleted, [])
        self.assertIsNone(result.stopped)
        self.assertTrue((self.era_sv / "Gone.lua").exists())
        self.assertTrue((self.retail_sv / "Uninstalled.lua").exists())
        self.assertEqual(sorted(p.name.split("-")[1] for p in self.backup_dir.glob("cleaned/*.zip")),
                         ["classic_era", "retail"])
        self.assertFalse(list(self.backup_dir.glob("backup/*.zip")))

    def test_real_clean_takes_one_wtf_backup_per_flavor(self):
        result = execute_flavors(self.plan(), dry_run=False, backup=True, backup_dir=self.backup_dir)
        self.assertEqual(len(result.deleted), 9)
        self.assertEqual(len(list(self.backup_dir.glob("backup/backup-classic_era-*.zip"))), 1)
        self.assertEqual(len(list(self.backup_dir.glob("backup/backup-retail-*.zip"))), 1)
        self.assertFalse((self.era_sv / "Gone.lua").exists())
        self.assertFalse((self.retail_sv / "Uninstalled.lua").exists())
        self.assertEqual([(flavor.folder, o.path.name) for flavor, o in result.outcomes][0],
                         ("_classic_era_", "Gone.lua"))

    def test_error_stops_before_the_next_flavor(self):
        plan = self.plan()
        plan = [plan[0], plan[1], (self.install.flavor("anniversary"), plan[1][1])]  # a third, never reached
        calls = []
        real = multi.execute

        def fake(items, flavor, **kwargs):
            calls.append(flavor.folder)
            if flavor.folder == "_retail_":
                raise CleanError("locked")
            return real(items, flavor, **kwargs)

        multi.execute = fake
        self.addCleanup(setattr, multi, "execute", real)
        with capture_events() as records:
            result = execute_flavors(plan, dry_run=False, backup=True, backup_dir=self.backup_dir)
        self.assertEqual(calls, ["_classic_era_", "_retail_"])
        self.assertEqual([r.status for r in result.runs], ["done", "stopped", "not_started"])
        self.assertIs(result.stopped, result.runs[1])
        self.assertEqual([r.flavor.folder for r in result.done], ["_classic_era_"])
        self.assertEqual([r.flavor.folder for r in result.not_started], ["_anniversary_"])
        self.assertFalse((self.era_sv / "Gone.lua").exists())
        self.assertTrue((self.retail_sv / "Uninstalled.lua").exists())
        stopped = [r for r in records if r["event"] == "clean.flavors_stopped"]
        self.assertEqual(stopped[0]["data"]["flavor"], "_retail_")
        self.assertEqual(stopped[0]["data"]["not_started"], ["_anniversary_"])

    def test_backup_error_in_the_first_flavor_runs_nothing_else(self):
        calls = []

        def fake(items, flavor, **kwargs):
            calls.append(flavor.folder)
            raise BackupError("disk full")

        real = multi.execute
        multi.execute = fake
        self.addCleanup(setattr, multi, "execute", real)
        result = execute_flavors(self.plan(), dry_run=False, backup=True, backup_dir=self.backup_dir)
        self.assertEqual(calls, ["_classic_era_"])
        self.assertEqual(result.done, [])
        self.assertIsInstance(result.stopped.error, BackupError)
        self.assertTrue((self.retail_sv / "Uninstalled.lua").exists())


if __name__ == "__main__":
    unittest.main()
