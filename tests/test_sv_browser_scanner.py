"""Saved Variables Browser scanner (spec D3, D4, D18): every SavedVariables file of a flavor (or all flavors), every
account, account-wide and per character, listed with its size and never parsed."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import build_sv_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.svfiles import LOCK_PROBE_SUFFIX
from wowtools.tools.sv_browser import scanner


def listing(scan):
    """{flavor folder: {account: {owner: [file names]}}}."""
    return {f.flavor.folder: {a.name: {o.label: [sv.path.name for sv in o.files] for o in a.owners}
                              for a in f.accounts}
            for f in scan.flavors}


class ScannerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = build_sv_tree(Path(tmp.name) / "wow")
        self.install = WowInstall(self.root)
        self.retail = self.install.flavor("_retail_")
        self.era = self.install.flavor("_classic_era_")

    def test_lists_every_file_of_every_account_and_owner(self):
        scan = scanner.scan_flavors([self.retail, self.era])
        self.assertEqual(listing(scan), {
            "_retail_": {
                "ACCT1": {"Account-wide": ["Blizzard_Console.lua", "Broken.lua", "Details.lua", "ElvUI.lua"],
                          "Realm1/Kaelys": ["ElvUI.lua"]},
                "ACCT2": {"Account-wide": ["Details.lua"], "Realm2/Chârb": ["Bartender4.lua"]},
            },
            "_classic_era_": {
                "ACCT1": {"Account-wide": ["Questie.lua"], "Realm1/Kaelys": ["Questie.lua"]},
            },
        })
        self.assertEqual(len(scan.files()), 9)
        self.assertEqual(scan.warnings, [])

    def test_one_flavor_lists_only_that_flavor(self):
        scan = scanner.scan_flavors([self.era])
        self.assertEqual([f.flavor.folder for f in scan.flavors], ["_classic_era_"])
        self.assertEqual({sv.path.name for sv in scan.files()}, {"Questie.lua"})

    def test_files_carry_owner_size_and_mtime_and_are_never_read(self):
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("the scan must not read files")):
            scan = scanner.scan_flavors([self.retail])
        elv = next(sv for sv in scan.files() if sv.addon == "ElvUI" and sv.character is None)
        info = os.stat(elv.path)
        self.assertEqual((elv.account, elv.owner, elv.size, elv.mtime), ("ACCT1", "Account-wide", info.st_size,
                                                                         info.st_mtime))
        self.assertEqual(elv.flavor, self.retail)
        self.assertEqual(elv.sha256, "")  # taken when the file is first read (the model, the search; D17)
        char = next(sv for sv in scan.files() if sv.character is not None and sv.account == "ACCT1")
        self.assertEqual((char.owner, char.character.name), ("Realm1/Kaelys", "Kaelys"))

    def test_broken_and_blizzard_files_are_listed_bak_is_not(self):
        names = [sv.path.name for sv in scanner.scan_flavors([self.retail]).files()]
        self.assertIn("Broken.lua", names)
        self.assertIn("Blizzard_Console.lua", names)
        self.assertNotIn("ElvUI.lua.bak", names)

    def test_old_and_other_files_are_never_listed(self):
        sv = self.retail.account_dir / "ACCT1" / "SavedVariables"
        for name in ("ElvUI.lua.old", "notes.txt", ".lua"):
            (sv / name).write_text("x = 1\n")
        names = [f.path.name for f in scanner.scan_flavors([self.retail]).files()]
        self.assertEqual([n for n in names if not n.endswith(".lua") or n == ".lua"], [])

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_links_are_never_followed(self):
        sv = self.retail.account_dir / "ACCT1" / "SavedVariables"
        os.symlink(sv / "Details.lua", sv / "Linked.lua")
        outside = self.root / "outside"
        (outside / "SavedVariables").mkdir(parents=True)
        (outside / "SavedVariables" / "Far.lua").write_text("Far = 1\n")
        realm = self.retail.account_dir / "ACCT2" / "RealmL"
        realm.mkdir()
        os.symlink(outside, realm / "Linked")
        scan = scanner.scan_flavors([self.retail])
        names = [f.path.name for f in scan.files()]
        self.assertNotIn("Linked.lua", names)
        self.assertNotIn("Far.lua", names)
        self.assertTrue(any("under a link" in w.message for w in scan.warnings))

    def test_recovers_probe_leftovers_before_listing(self):
        sv = self.retail.account_dir / "ACCT2" / "SavedVariables"
        (sv / "Details.lua").rename(sv / ("Details.lua" + LOCK_PROBE_SUFFIX))
        with capture_events() as events:
            scan = scanner.scan_flavors([self.retail])
        self.assertTrue((sv / "Details.lua").is_file())
        self.assertIn(sv / "Details.lua", [f.path for f in scan.files()])
        recovered = [e for e in events if e["event"] == "svb.probe_recovered"]
        self.assertEqual([e["data"]["path"] for e in recovered], ["WTF/Account/ACCT2/SavedVariables/Details.lua"])

    def test_logs_scan_completed_with_counts(self):
        with capture_events() as events:
            scan = scanner.scan_flavors([self.retail, self.era])
        done = [e for e in events if e["event"] == "svb.scan_completed"]
        self.assertEqual(len(done), 1)
        data = done[0]["data"]
        self.assertEqual((data["flavors"], data["accounts"], data["files"], data["bytes"]),
                         (2, 3, 9, sum(f.size for f in scan.files())))
        self.assertIn("seconds", data)

    def test_flavor_without_account_folder_is_an_error_not_a_crash(self):
        empty = self.root / "_ptr_"
        (empty / "Interface" / "AddOns").mkdir(parents=True)
        flavor = WowInstall(self.root).flavor("_ptr_")
        scan = scanner.scan_flavors([flavor])
        self.assertIn("no WTF/Account folder", scan.flavors[0].error)
        self.assertEqual(scan.files(), [])

    def test_progress_reports_each_flavor(self):
        seen = []
        scanner.scan_flavors([self.retail, self.era], progress=lambda f, i, n, label: seen.append((f.folder, i, n)))
        self.assertEqual(seen, [("_retail_", 1, 2), ("_classic_era_", 2, 2)])


if __name__ == "__main__":
    unittest.main()
