"""scanner: SavedVariables across accounts and characters, AceDB databases, leftovers and warnings (spec §6)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_ace_tree
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.tools.ace_profiles import scanner


class ScannerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = build_ace_tree(Path(tmp.name) / "wow")
        self.install = WowInstall(self.root)
        self.retail = self.install.flavor("_retail_")

    def files(self, scan):
        return {(f.file.account, f.file.owner, f.file.addon): [db.sv_name for db in f.dbs] for f in scan.files()}

    def test_finds_databases_per_file(self):
        scan = scanner.scan_flavor(self.retail)
        self.assertIsNone(scan.error)
        self.assertEqual(self.files(scan), {
            ("ACCT1", "Account-wide", "ElvUI"): ["ElvDB", "ElvPrivateDB"],
            ("ACCT1", "Account-wide", "HandyNotes"): ["HandyNotesDB", "HandyNotes_MapNotesDB"],
            ("ACCT1", "Account-wide", "KickCD"): ["KickCDDB"],
            ("ACCT1", "Account-wide", "Stock"): ["StockDB"],
            ("ACCT1", "Realm1/Kaelys", "PerChar"): ["PerCharDB"],
            ("ACCT2", "Account-wide", "KickCD"): ["KickCDDB"],
        })

    def test_skips_bak_blizzard_and_non_lua(self):
        names = {f.file.path.name for f in scanner.scan_flavor(self.retail).files()}
        self.assertNotIn("KickCD.lua.bak", names)
        self.assertNotIn("Blizzard_AceThing.lua", names)

    def test_warnings_for_unparsable_and_lookalike(self):
        with capture_events() as events:
            scan = scanner.scan_flavor(self.retail)
        messages = [w.message for w in scan.warnings]
        self.assertTrue(any("Broken.lua" in str(w.path) for w in scan.warnings))
        self.assertTrue(any("not readable" in m for m in messages))
        self.assertIn("ace.parse_failed", [e["event"] for e in events])
        self.assertIn("ace.scan_completed", [e["event"] for e in events])

    def test_leftovers_and_characters(self):
        scan = scanner.scan_flavor(self.retail)
        acct1 = next(a for a in scan.accounts if a.account == "ACCT1")
        self.assertTrue(acct1.is_leftover("Gone - Realm1"))
        self.assertFalse(acct1.is_leftover("kaelys - realm1"))
        self.assertFalse(acct1.is_leftover("Mierin - Khaz Modan"))

    def test_file_identity(self):
        scan = scanner.scan_flavor(self.retail)
        kick = next(f.file for f in scan.files() if f.file.addon == "KickCD" and f.file.account == "ACCT1")
        data = kick.path.read_bytes()
        self.assertEqual(kick.sha256, scanner.sha256_of(data))
        self.assertEqual(kick.size, len(data))
        self.assertEqual(kick.rel, "WTF/Account/ACCT1/SavedVariables/KickCD.lua")

    def test_one_account_case_insensitive(self):
        scan = scanner.scan_flavor(self.retail, account="acct2")
        self.assertEqual([a.account for a in scan.accounts], ["ACCT2"])

    def test_progress_and_multi_flavor(self):
        seen = []
        result = scanner.scan_flavors([self.retail, self.install.flavor("_classic_era_")],
                                      progress=lambda flavor, i, n, label: seen.append((flavor.folder, i, n)))
        self.assertEqual([f.flavor.folder for f in result.flavors], ["_retail_", "_classic_era_"])
        self.assertEqual(seen[-1][0], "_classic_era_")
        self.assertEqual(seen[-1][1], seen[-1][2])

    def test_flavor_without_wtf_is_an_error_not_an_exception(self):
        empty = self.root / "_ptr_"
        empty.mkdir()
        scan = scanner.scan_flavor(self.install.flavor("_ptr_"))
        self.assertIsNotNone(scan.error)

    @unittest.skipIf(os.name == "nt", "symlink creation needs privileges on Windows")
    def test_saved_variables_under_a_link_is_skipped(self):
        target = self.root.parent / "elsewhere"
        target.mkdir()
        link = self.retail.account_dir / "ACCT2" / "Realm2" / "Linked"
        os.symlink(target, link)
        (target / "SavedVariables").mkdir()
        (target / "SavedVariables" / "X.lua").write_bytes(b'X = {\n["profileKeys"] = {\n},\n}\n')
        scan = scanner.scan_flavor(self.retail)
        self.assertNotIn("X", {f.file.addon for f in scan.files()})
        self.assertTrue(any("link" in w.message for w in scan.warnings))
