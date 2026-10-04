from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from wowtools.core.install import Flavor
from wowtools.core.paths import to_stored
from wowtools.tools.screenshot_organizer import organizer
from wowtools.tools.screenshot_organizer.organizer import (CONFLICT_KEPT, MOVED, RESTORED, WOULD_MOVE, OrganizeResult,
                                                           Outcome)
from wowtools.tools.screenshot_organizer.planner import FILED, NEW, FlavorPlan, Plan, ShotItem
from wowtools.tools.screenshot_organizer.report import (KIND_LABELS, STAGE_TITLES, confirm_text, destination_label,
                                                        result_rows, stopped_text, summary_rows, target_folder)
from wowtools.tools.screenshot_organizer.settings import ShotSettings

# Outcome kinds: the upper-case string constants of organizer, minus the partial-file suffix and the journal
# action names it imports (A_*), which are not outcome kinds.
KINDS = [v for k, v in vars(organizer).items() if k.isupper() and isinstance(v, str)
         and k != "PARTIAL" and not k.startswith("A_")]


class ReportTest(unittest.TestCase):
    def test_stopped_text(self):
        src = Path("/w/_retail_/Screenshots/a.jpg")
        dry = OrganizeResult(True, False, [Outcome("_retail_", src, src, WOULD_MOVE)])
        text = stopped_text("The run stopped: boom.", dry, Path("/j/older.jsonl"))
        self.assertIn("dry run", text)
        self.assertNotIn("Undo", text)
        # The journal could not even be opened: nothing changed, and an older run must not be offered.
        none = OrganizeResult(False, False)
        text = stopped_text("Nothing was filed.", none, Path("/j/older.jsonl"))
        self.assertNotIn("Undo last run (z) to put", text)
        own = OrganizeResult(False, False, [Outcome("_retail_", src, src, MOVED)], journal_path=Path("/j/b.jsonl"))
        self.assertIn("Undo last run (z)", stopped_text("Stopped.", own, Path("/j/b.jsonl")))
        self.assertNotIn("Undo last run (z) to put", stopped_text("Stopped.", own, Path("/j/other.jsonl")))

    def test_every_kind_has_a_label(self):
        self.assertIn("moved", KINDS)
        for kind in KINDS:
            self.assertIn(kind, KIND_LABELS)
        self.assertEqual(set(STAGE_TITLES), {"organize", "prune", "undo"})

    def test_summary_and_rows(self):
        src = Path("/w/_retail_/Screenshots/WoWScrnShot_073119_232713.jpg")
        dst = Path("/a/_retail_/2019/07/31/WoWScrnShot_073119_232713.jpg")
        result = OrganizeResult(False, False, [Outcome("_retail_", src, dst, MOVED),
                                               Outcome("_retail_", src, dst, CONFLICT_KEPT, "different")],
                                journal_path=Path("/j/journal-x.jsonl"))
        rows = dict(summary_rows(result))
        self.assertEqual(rows["Mode"], "Move")
        self.assertEqual(rows[KIND_LABELS[MOVED]], "1")
        self.assertNotIn(KIND_LABELS[WOULD_MOVE], rows)  # zero counts are left out
        self.assertEqual(rows["Journal"], str(Path("/j/journal-x.jsonl")))
        # Target inside the "Target folder" row: the date folders always show at 120x30.
        self.assertEqual(rows["Target folder"], to_stored(Path("/a/_retail_")))
        self.assertEqual(result_rows(result)[1], (KIND_LABELS[CONFLICT_KEPT], "Retail", src.name,
                                                  str(Path("2019", "07", "31")), "different"))
        dry = OrganizeResult(True, False, [Outcome("_retail_", src, dst, WOULD_MOVE)])
        self.assertEqual(dict(summary_rows(dry))["Journal"], "not written (dry run)")
        self.assertEqual(dict(summary_rows(dry))["Mode"], "Dry run (move)")
        nothing = OrganizeResult(False, True, [Outcome("_retail_", src, dst, CONFLICT_KEPT)])
        self.assertEqual(dict(summary_rows(nothing))["Journal"], "none (nothing changed)")
        self.assertEqual(dict(summary_rows(nothing))["Mode"], "Copy")
        undone = OrganizeResult(False, False, [Outcome("_retail_", src, dst, RESTORED)],
                                journal_path=Path("/j/journal-x.jsonl"), undo=True)
        self.assertEqual(dict(summary_rows(undone))["Mode"], "Undo")
        pruned = OrganizeResult(False, False, [Outcome("_retail_", src, dst, MOVED)],
                                journal_path=Path("/j/journal-x.jsonl"), pruned=[Path("/j/a"), Path("/j/b")])
        self.assertEqual(dict(summary_rows(pruned))["Older journals removed"], "2")

    def test_targets_keep_their_date_folders_inside_the_target_folder(self):
        """Terminal size round review: a whole target folder (C:\\Program Files (x86)\\World of Warcraft\\...) cut
        the date folders off at 120x30. Targets are named inside the "Target folder" row, each keeping YYYY/MM/DD."""
        wow = Path("/w/World of Warcraft")

        def shot(folder, day):
            src = wow / folder / "Screenshots" / "WoWScrnShot_073119_232713.jpg"
            return Outcome(folder, src, wow / folder / "Screenshots" / day / src.name, WOULD_MOVE)
        both = OrganizeResult(True, False, [shot("_retail_", "2019/07/31"), shot("_classic_era_", "2012/05/20")])
        self.assertEqual(target_folder(both), wow)
        self.assertEqual([row[3] for row in result_rows(both)],
                         [str(Path("_retail_", "Screenshots", "2019", "07", "31")),
                          str(Path("_classic_era_", "Screenshots", "2012", "05", "20"))])
        one_day = OrganizeResult(True, False, [shot("_retail_", "2019/07/31")])
        self.assertEqual(target_folder(one_day), wow / "_retail_" / "Screenshots")
        self.assertEqual(result_rows(one_day)[0][3], str(Path("2019", "07", "31")))
        self.assertEqual(dict(summary_rows(one_day))["Target folder"], to_stored(wow / "_retail_" / "Screenshots"))
        src = wow / "_retail_" / "Screenshots" / "2019" / "07" / "31" / "a.jpg"
        undone = OrganizeResult(False, False, [Outcome("_retail_", src, wow / "_retail_" / "Screenshots" / "a.jpg",
                                                       RESTORED)], undo=True)
        self.assertEqual(result_rows(undone)[0][3], "Screenshots")
        self.assertIsNone(target_folder(OrganizeResult(True, False)))
        self.assertNotIn("Target folder", dict(summary_rows(OrganizeResult(True, False))))

    def test_destination_label(self):
        self.assertIn("in place", destination_label(None))
        self.assertIn("YYYY", destination_label(Path("/arch")))
        self.assertIn("<flavor>", destination_label(Path("/arch")))

    def test_confirm_text(self):
        flavor = Flavor("_retail_", Path("/w/_retail_"))
        item = ShotItem(flavor, Path("/w/_retail_/Screenshots/a.jpg"), Path("/a/_retail_/2019/07/31/a.jpg"),
                        date(2019, 7, 31), 1, 0.0, NEW)
        plan = Plan([FlavorPlan(flavor, Path("/w/_retail_/Screenshots"), Path("/a/_retail_"), [item])],
                    Path("/a"))
        title, body = confirm_text([item], plan, ShotSettings(dest_dir=Path("/a")), False)
        self.assertIn("Move 1 screenshot", title)
        in_place = Plan(plan.flavors, None)
        title, body = confirm_text([item, item], in_place, ShotSettings(dest_dir=Path("/a"), copy_mode=True), True)
        self.assertTrue(title.startswith("Dry run"))
        self.assertIn("Copy 2 screenshots", title)
        self.assertIn("in place", body)  # the scanned plan's destination wins over changed settings

    def test_confirm_text_mentions_ticked_already_filed_copies(self):
        flavor = Flavor("_retail_", Path("/w/_retail_"))
        item = ShotItem(flavor, Path("/w/_retail_/Screenshots/a.jpg"), Path("/w/_retail_/Screenshots/2019/07/31/a.jpg"),
                        date(2019, 7, 31), 1, 0.0, FILED)
        plan = Plan([FlavorPlan(flavor, Path("/w/_retail_/Screenshots"), Path("/w/_retail_/Screenshots"), [item])],
                    None)
        _, body = confirm_text([item], plan, ShotSettings(copy_mode=True), False)
        self.assertIn("Retail: 1 screenshot (1 already filed)", body)
        self.assertIn("compared by content", body)
