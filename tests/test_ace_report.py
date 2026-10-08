"""report: labels, tags, summary lines and result rows."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rich.cells import cell_len

from tests.fixtures import build_ace_tree
from wowtools.core.install import Flavor, WowInstall
from wowtools.core.paths import to_stored
from wowtools.tools.ace3_profile_manager import editor, multi, ops, report, scanner
from wowtools.tools.ace3_profile_manager.undo import UndoResult


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
        self.assertEqual(report.selection_text(0, 0, ops.Summary()),
                         "Selected: 0 profiles · 0 characters · No pending changes")
        summary = ops.Summary(deleted=2, reassigned=5, renamed=1, files=2)
        self.assertEqual(report.pending_text(summary), "2 deletes · 1 rename · 5 reassigns")
        self.assertEqual(report.pending_text(ops.Summary()), "No pending changes")
        # the scan warnings are on the bottom line's Warnings button, not in this text (spec W1)
        self.assertEqual(report.selection_text(1, 3, summary),
                         "Selected: 1 profile · 3 characters · 8 pending changes in 2 files")
        self.assertNotIn("staged", report.selection_text(1, 3, summary).casefold())

    def test_guidance_steps_when_nothing_is_going_on(self):
        text = report.guidance("root", "", 0, 0, 0)
        self.assertEqual(text, "1 Tick profiles or characters (Space) → 2 pick an action below → 3 check the "
                               "pending changes in the tree → 4 Apply writes them")
        self.assertEqual(report.guidance(None, "", 0, 0, 0), text)
        self.assertEqual(report.guidance("account", "ACCT1", 0, 0, 0), text)

    def test_guidance_on_a_highlighted_node(self):
        self.assertEqual(report.guidance("profile", "Healer", 0, 0, 0), 'Profile "Healer": Delete, Rename or Copy it')
        for kind in ("char", "pair", "character"):
            self.assertEqual(report.guidance(kind, "Kaelys - Realm1", 0, 0, 0),
                             '"Kaelys - Realm1": Assign a profile, or remove it if a leftover')
        self.assertEqual(report.guidance("addon", "ElvUI", 0, 0, 0),
                         "ElvUI: Only Default, Everyone → Default (below)")

    def test_guidance_on_a_blacklisted_node(self):
        """Feedback round 1 review: a locked addon offers no action but the unlock."""
        for kind, name in (("addon", "ElvUI"), ("db", "ElvUI"), ("profile", "Healer"), ("char", "Kaelys - Realm1")):
            text = report.guidance(kind, name, 0, 0, 0, locked="ElvUI")
            self.assertEqual(text, "ElvUI is blacklisted: u unlocks it for this session", kind)
        self.assertEqual(report.guidance("root", "", 0, 0, 0, locked=""), report.STEPS)
        pending = report.guidance("profile", "Healer", 0, 0, 3, locked="ElvUI")
        self.assertEqual(pending.splitlines()[1], "ElvUI is blacklisted: u unlocks it for this session")

    def test_guidance_without_the_hint(self):
        """When the hint does not fit, only the pending line is shown (the steps when nothing is pending)."""
        text = report.guidance("profile", "Healer", 0, 0, 3, hint=False)
        self.assertEqual(text.splitlines(), [report.guidance("root", "", 0, 0, 3)])
        self.assertEqual(report.guidance("profile", "Healer", 2, 0, 0, hint=False), report.STEPS)

    def test_guidance_with_ticks(self):
        self.assertEqual(report.guidance("profile", "Healer", 2, 1, 0),
                         "3 ticked: pick an action below (Delete, Assign, …)")

    def test_guidance_with_pending_changes_comes_first(self):
        pending = "3 pending changes, not written: Apply, Dry run or Discard them"
        self.assertEqual(report.guidance("root", "", 0, 0, 3), pending)
        self.assertEqual(report.guidance("profile", "Healer", 0, 0, 3),
                         pending + '\nProfile "Healer": Delete, Rename or Copy it')
        self.assertTrue(report.guidance("addon", "ElvUI", 1, 0, 1).startswith("1 pending change, not written"))
        self.assertIn("\n1 ticked: pick an action below", report.guidance("addon", "ElvUI", 1, 0, 1))

    def test_guide_lines_fit_one_row_of_the_tree_pane_at_base(self):
        """Terminal size plan, Task S3: at 120x30 the guide is 68 columns wide (the tree pane, less its padding).
        The pending line (up to 99999 changes: a whole account's Everyone -> Default is easily 100+) and each hint,
        with a name of up to 16 characters, take one row each, so both show together; a longer name is shortened by
        the screen (GUIDE_MAX_ROWS)."""
        width = 68
        name = "N" * 16
        lines = [report.guidance("root", "", 0, 0, 99), report.guidance("root", "", 0, 0, 99999)]
        lines += [report.guidance(kind, name, 0, 0, 0) for kind in ("profile", "char", "addon")]
        lines += [report.guidance("profile", name, 0, 0, 0, locked=name), report.guidance("profile", name, 99, 0, 0)]
        for line in lines:
            self.assertLessEqual(cell_len(line), width, line)

    def test_shorten(self):
        self.assertEqual(report.shorten("Healer", 6), "Healer")
        self.assertEqual(report.shorten("Healer", 3), "Hea…")

    def test_result_summaries_name_files_inside_the_backup_folder(self):
        """Terminal size plan, Task S3: a whole zip path is cut off at 120 columns. The backup folder has a row of
        its own; the zips (and the journal, when it is in there) are named inside it; a file elsewhere keeps its
        whole path."""
        root = Path("/wow/wow-tools/ace3-profile-manager")
        flavor = Flavor("_retail_", Path("/wow/_retail_"))
        apply = editor.ApplyResult(flavor, False, snapshot=root / "snapshots" / "snapshot-retail-1.zip",
                                   backup_zip=root / "edited" / "edited-retail-all-1.zip")
        result = multi.MultiApplyResult(False, [multi.FlavorRun(flavor, apply)], root / "journal" / "journal-1.jsonl")
        rows = report.apply_summary_rows(result)
        self.assertEqual([item for item, _ in rows], ["Changed", "Backup folder", "WTF backup (Retail)",
                                                       "Original files (Retail)", "Journal"])
        values = dict(rows)
        self.assertEqual(values["Backup folder"], to_stored(root))
        self.assertEqual(values["WTF backup (Retail)"], str(Path("snapshots", "snapshot-retail-1.zip")))
        self.assertEqual(values["Original files (Retail)"], str(Path("edited", "edited-retail-all-1.zip")))
        self.assertEqual(values["Journal"], str(Path("journal", "journal-1.jsonl")))
        elsewhere = Path("/journals/journal-1.jsonl")
        result.journal_path = elsewhere
        self.assertEqual(dict(report.apply_summary_rows(result))["Journal"], to_stored(elsewhere))
        undo = UndoResult(snapshots=[root / "snapshots" / "snapshot-retail-2.zip"])
        self.assertEqual(report.undo_summary_rows(undo), [
            ("Put back", "0 files"), ("Backup folder", to_stored(root)),
            ("WTF backup", str(Path("snapshots", "snapshot-retail-2.zip")))])
        dry = multi.MultiApplyResult(True, [multi.FlavorRun(flavor, editor.ApplyResult(flavor, True))])
        self.assertEqual([item for item, _ in report.apply_summary_rows(dry)], ["Would change"])

    def test_apply_confirm_alerts(self):
        key = self.st("ElvDB").key
        self.staging.delete({key: ["Default"]}, "Healer")
        self.staging.assign({self.st("HandyNotesDB").key: ["Kaelys - Realm1"]}, "Default")
        title, body, warnings = report.apply_confirm(self.staging.summary(), self.staging.changed(), dry_run=False)
        self.assertEqual(title, "Apply the pending changes?")
        self.assertIn("2 files", body)
        self.assertIn("Retail", body)
        # one Listed per warning (spec L10): the message once, where (flavor · account) and the addon apart
        deleted = [w for w in warnings if "Default" in w.message and "deleted" in w.message]
        self.assertEqual([(w.where, w.item) for w in deleted], [("Retail · ACCT1", "ElvUI")])
        self.assertEqual(deleted[0].message, 'The "Default" profile will be deleted.')
        self.assertTrue(any("next login" in w.message for w in warnings))
        self.assertTrue(any("LibDualSpec" in w.message for w in warnings))
        self.assertFalse(any(w.item in w.message for w in warnings))  # the addon is never in the message

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
