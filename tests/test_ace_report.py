"""report: labels, tags, summary lines and result rows."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import build_ace_tree
from wowtools.core.install import WowInstall
from wowtools.tools.ace_profiles import ops, report, scanner


class ReportTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = build_ace_tree(Path(tmp.name) / "wow")
        scan = scanner.ScanResult([scanner.scan_flavor(WowInstall(root).flavor("_retail_"), account="ACCT1")])
        self.staging = ops.Staging.from_scan(scan)

    def st(self, sv_name):
        return next(s for s in self.staging.states.values() if s.db.sv_name == sv_name)

    def rows(self, sv_name):
        return {r.name: r for r in report.profile_rows(self.st(sv_name))}

    def test_tags_on_a_fresh_database(self):
        rows = self.rows("KickCDDB")
        self.assertEqual(rows["Default"].tags, ["Default"])
        self.assertEqual(rows["Default"].label, "Default · 3 characters · Default")
        self.assertIn("unused", rows["Backup"].tags)
        self.assertIn("empty", rows["Backup"].tags)
        gone = next(c for c in rows["Default"].chars if c.char == "Gone - Realm1")
        self.assertIn("no character folder", gone.tags)

    def test_missing_and_lds_tags(self):
        self.assertIn("missing", self.rows("StockDB")["Gone"].tags)
        kaelys = next(c for c in self.rows("ElvDB")["Default"].chars if c.char == "Kaelys - Realm1")
        self.assertIn("spec profiles", kaelys.tags)

    def test_staged_marks(self):
        key = self.st("ElvDB").key
        self.staging.copy(key, "Default", "Spare")
        self.staging.delete({key: ["Healer"]}, "Default")
        rows = self.rows("ElvDB")
        self.assertTrue(rows["Healer"].deleted)
        self.assertIn("✘ deleted", rows["Healer"].label)
        self.assertIn("copy of Default", rows["Spare"].tags)
        mierin = next(c for c in rows["Default"].chars if c.char == "Mierin - Khaz Modan")
        self.assertIn("was Healer", mierin.tags)
        self.staging.rename(key, "Spare", "Tank")
        self.assertIn("copy of Default", self.rows("ElvDB")["Tank"].tags)

    def test_removed_character_stays_under_its_profile(self):
        key = self.st("KickCDDB").key
        self.staging.remove_leftovers({key: ["Gone - Realm1"]})
        gone = next(c for c in self.rows("KickCDDB")["Default"].chars if c.char == "Gone - Realm1")
        self.assertTrue(gone.removed)
        self.assertIn("✘ removed", gone.tags)

    def test_selection_and_pending_text(self):
        self.assertEqual(report.selection_text(0, 0, ops.Summary(), 0),
                         "Selected: 0 profiles · 0 characters · No pending changes")
        summary = ops.Summary(deleted=2, reassigned=5, renamed=1, files=2)
        self.assertEqual(report.pending_text(summary), "2 deletes · 1 rename · 5 reassigns")
        self.assertEqual(report.pending_text(ops.Summary()), "No pending changes")
        self.assertEqual(report.selection_text(1, 3, summary, 2),
                         "Selected: 1 profile · 3 characters · 8 pending changes in 2 files · ⚠ 2 scan warnings")
        self.assertNotIn("staged", report.selection_text(1, 3, summary, 2).casefold())

    def test_guidance_steps_when_nothing_is_going_on(self):
        text = report.guidance("root", "", 0, 0, 0, 0)
        self.assertEqual(text, "1 Tick profiles or characters (Space) → 2 pick an action below → 3 check the "
                               "pending changes in the tree → 4 Apply (w) writes them; Dry run (y) only checks them")
        self.assertEqual(report.guidance(None, "", 0, 0, 0, 0), text)
        self.assertEqual(report.guidance("account", "ACCT1", 0, 0, 0, 0), text)

    def test_guidance_on_a_highlighted_node(self):
        self.assertEqual(report.guidance("profile", "Healer", 0, 0, 0, 0),
                         'Profile "Healer": Delete, Rename or Copy it, or tick it with Space')
        for kind in ("char", "pair", "character"):
            self.assertEqual(report.guidance(kind, "Kaelys - Realm1", 0, 0, 0, 0),
                             '"Kaelys - Realm1": Assign it a profile, or remove it if it is a leftover')
        self.assertEqual(report.guidance("addon", "ElvUI", 0, 0, 0, 0),
                         "ElvUI: Keep only Default or Everyone → Default (More…), or Blacklist…")

    def test_guidance_with_ticks(self):
        self.assertEqual(report.guidance("profile", "Healer", 2, 1, 0, 0),
                         "3 ticked: pick an action below (Delete, Assign, …)")

    def test_guidance_with_pending_changes_comes_first(self):
        pending = ("3 pending changes in 2 files, not written yet: Apply (w) writes them, Dry run (y) checks "
                   "them, Discard (⌫) drops them")
        self.assertEqual(report.guidance("root", "", 0, 0, 3, 2), pending)
        self.assertEqual(report.guidance("profile", "Healer", 0, 0, 3, 2),
                         pending + '\nProfile "Healer": Delete, Rename or Copy it, or tick it with Space')
        self.assertTrue(report.guidance("addon", "ElvUI", 1, 0, 1, 1).startswith(
            "1 pending change in 1 file, not written yet"))
        self.assertIn("\n1 ticked: pick an action below", report.guidance("addon", "ElvUI", 1, 0, 1, 1))

    def test_apply_confirm_alerts(self):
        key = self.st("ElvDB").key
        self.staging.delete({key: ["Default"]}, "Healer")
        self.staging.assign({self.st("HandyNotesDB").key: ["Kaelys - Realm1"]}, "Default")
        title, body, alerts = report.apply_confirm(self.staging.summary(), self.staging.changed(), dry_run=False)
        self.assertEqual(title, "Apply the pending changes?")
        self.assertIn("2 files", body)
        self.assertTrue(any("Default" in a and "deleted" in a for a in alerts))
        self.assertTrue(any("next login" in a for a in alerts))
        self.assertTrue(any("LibDualSpec" in a for a in alerts))
        self.assertIn("Retail", body)

    def test_plural(self):
        self.assertEqual(report.plural(1, "profile"), "1 profile")
        self.assertEqual(report.plural(2, "copy", "copies"), "2 copies")

    def test_removed_character_follows_a_renamed_profile(self):
        key = self.st("KickCDDB").key
        self.staging.remove_leftovers({key: ["Gone - Realm1"]})
        self.staging.rename(key, "Default", "Main")
        rows = self.rows("KickCDDB")
        self.assertNotIn("Default", rows)
        self.assertEqual(rows["Main"].label, "Main · 2 characters · renamed from Default")
        gone = next(c for c in rows["Main"].chars if c.char == "Gone - Realm1")
        self.assertTrue(gone.removed)

    def test_removed_character_of_a_missing_profile_is_not_put_under_a_deleted_one(self):
        state = self.st("KickCDDB")
        state.db.profile_keys["Gone - Realm1"] = "Lost"
        state.keys["Gone - Realm1"] = "Lost"
        self.staging.remove_leftovers({state.key: ["Gone - Realm1"]})
        self.staging.delete({state.key: ["Backup"]}, "Default")
        rows = self.rows("KickCDDB")
        self.assertTrue(rows["Backup"].deleted)
        self.assertEqual(rows["Backup"].chars, [])
        self.assertIn("missing", rows["Lost"].tags)
        self.assertEqual([c.char for c in rows["Lost"].chars], ["Gone - Realm1"])
