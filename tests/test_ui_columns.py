"""The shared tree-label helpers (feedback round 2 spec R2, R4; STD-7.27, STD-7.28): a node's data in aligned
columns (`ui/columns.py`: natural widths, fitting to the pane, cutting with …, the Rich text) and the dimmed leaf
count after a node's label (`ui/counts.py`)."""
from __future__ import annotations

import unittest

from rich.text import Text

from wowtools.ui.columns import (ELLIPSIS, NARROW_GAP, WIDE_GAP, ColumnLayout, column_text, cut_middle, fit_columns,
                                 fit_keeping_count, natural_widths)
from wowtools.ui.counts import COUNT_STYLE, count_text, with_count

# name · reason · files · size · age (the WTF Cleaner's row, the user's example): the name and the reason give way,
# the reason first; files, size and age are short and never cut, the reason is dropped before the age.
LAYOUT = ColumnLayout(caps=(30, 30, None, None, None), minimums=(8, 6, 0, 0, 0), shrink=((1,), (0,)), drop=(1, 4))


class NaturalWidthsTest(unittest.TestCase):
    def test_each_column_is_its_widest_cell_among_the_siblings(self):
        rows = [("Details", "unused", "2 files", "1.2 KB", "40d"), ("WeakAuras", "", "1 file", "512 B", "3d")]
        self.assertEqual(natural_widths(rows), (9, 6, 7, 6, 3))

    def test_wide_characters_take_two_cells(self):
        self.assertEqual(natural_widths([("日本", "x")]), (4, 1))

    def test_no_rows_no_columns(self):
        self.assertEqual(natural_widths([]), ())


class FitColumnsTest(unittest.TestCase):
    def test_capped_two_spaces_apart_when_everything_fits(self):
        self.assertEqual(WIDE_GAP, 2)
        self.assertEqual(fit_columns((50, 40, 7, 6, 3), None, LAYOUT), ((30, 30, 7, 6, 3), WIDE_GAP))
        self.assertEqual(fit_columns((9, 6, 7, 6, 3), 200, LAYOUT), ((9, 6, 7, 6, 3), WIDE_GAP))

    def test_the_free_text_gives_way_first_one_space_apart(self):
        natural = (20, 30, 7, 6, 3)
        widths, gap = fit_columns(natural, 60, LAYOUT)
        self.assertEqual(gap, NARROW_GAP)
        self.assertEqual(sum(widths) + 4 * gap, 60)
        self.assertEqual((widths[0], widths[2:]), (20, (7, 6, 3)))  # only the reason shrank
        widths, gap = fit_columns(natural, 40, LAYOUT)
        self.assertEqual(widths[1], 6)  # the reason at its minimum, then the name
        self.assertEqual(sum(widths) + 4 * gap, 40)
        self.assertEqual(widths[2:], (7, 6, 3))  # the status-like columns are never cut

    def test_columns_are_dropped_when_the_minimums_do_not_fit(self):
        natural = (20, 30, 7, 6, 3)
        # every column at its minimum is 8+6+7+6+3 + 4 = 34 cells: the reason goes, the name takes room back
        self.assertEqual(fit_columns(natural, 28, LAYOUT), ((9, 0, 7, 6, 3), NARROW_GAP))
        self.assertEqual(fit_columns(natural, 26, LAYOUT), ((11, 0, 7, 6, 0), NARROW_GAP))  # then the age
        # past the layout's drops every other column goes: the name alone, cut to the room (a row always fits)
        self.assertEqual(fit_columns(natural, 18, LAYOUT), ((18, 0, 0, 0, 0), NARROW_GAP))
        for room in (30, 20, 10, 3, 0):
            with self.subTest(room=room):
                widths, _ = fit_columns(natural, room, LAYOUT)
                shown = [w for w in widths if w]
                self.assertLessEqual(sum(shown) + len(shown) - 1, max(room, 1))
                self.assertGreaterEqual(widths[0], 1)  # the first column (the name) always shows

    def test_an_empty_column_takes_no_gap(self):
        self.assertEqual(fit_columns((10, 0, 3), 15, ColumnLayout((None,) * 3, (1, 1, 1), ((0,),))),
                         ((10, 0, 3), WIDE_GAP))

    def test_the_config_editor_layout_is_the_shared_fit(self):
        """The fitting moved out of config_editor/report.py (R4): the CVar rows' behaviour (CF2, FB2r) is this one
        with the Config Editor's caps, minimums and drop order."""
        cvars = ColumnLayout(caps=(40, 24, 24, None, None), minimums=(12, 7, 6, 0, 0), shrink=((1, 2), (0,)),
                             drop=(2, 4, 1, 3))
        self.assertEqual(fit_columns((27, 300, 3, 7, 10), 42, cvars), ((15, 7, 0, 7, 10), 1))
        self.assertEqual(fit_columns((30, 7, 6, 7, 11), 20, cvars), ((12, 0, 0, 7, 0), 1))
        self.assertEqual(fit_columns((30, 7, 6, 7, 11), 0, cvars), ((1, 0, 0, 0, 0), 1))


    def test_the_count_is_kept_by_cutting_the_name(self):
        """fit_keeping_count (moved out of the Interface Backup, G6c): where the shared fit would leave the name
        alone, the name is cut (to its minimum at most) so the count column (1) stays (STD-7.27)."""
        layout = ColumnLayout(caps=(None,) * 3, minimums=(4, 0, 0), shrink=(), drop=(2,))
        natural = (20, 7, 10)
        self.assertEqual(fit_columns(natural, 20, layout), ((20, 0, 0), NARROW_GAP))
        self.assertEqual(fit_keeping_count(natural, 20, layout), ((12, 7, 0), NARROW_GAP))
        self.assertEqual(fit_keeping_count(natural, 50, layout), fit_columns(natural, 50, layout))  # it fits
        self.assertEqual(fit_keeping_count(natural, 10, layout), ((10, 0, 0), NARROW_GAP))  # no room for both
        self.assertEqual(fit_keeping_count((20, 0, 10), 20, layout), fit_columns((20, 0, 10), 20, layout))  # none

class CutTest(unittest.TestCase):
    def test_cut_in_the_middle_keeps_the_start_and_the_end(self):
        self.assertEqual(ELLIPSIS, "…")
        self.assertEqual(cut_middle("assistedCombatHighlight", 30), "assistedCombatHighlight")
        self.assertEqual(cut_middle("raidFramesDisplayAggroHighlight", 15), "raidFra…ghlight")
        self.assertEqual([cut_middle("nameplateShowFriends", w) for w in (2, 1, 0)], ["n…", "…", ""])

    def test_cut_in_the_middle_counts_cells(self):
        cut = cut_middle("日本語のテキスト", 7)
        self.assertLessEqual(Text(cut).cell_len, 7)
        self.assertTrue(cut.startswith("日") and ELLIPSIS in cut and cut.endswith("ト"))


class ColumnTextTest(unittest.TestCase):
    def test_cells_padded_to_their_widths_and_styled(self):
        text = column_text(("Details", "unused", "2 files"), (9, 6, 7), ("bold", "", "dim"), WIDE_GAP)
        self.assertEqual(text.plain, "Details    unused  2 files")
        styles = {span.style for span in text.spans}
        self.assertEqual(styles, {"bold", "dim"})

    def test_long_cells_cut_with_an_ellipsis_the_last_one_not_padded(self):
        text = column_text(("WeakAurasOptions", "a long reason here", "3d"), (10, 8, 5), ("", "", ""), NARROW_GAP,
                           middle=(0,))
        self.assertEqual(text.plain, "WeakA…ions a long … 3d")

    def test_a_column_of_width_zero_is_left_out(self):
        text = column_text(("name", "reason", "3d"), (4, 0, 2), ("", "", ""), NARROW_GAP)
        self.assertEqual(text.plain, "name 3d")

    def test_a_rich_cell_keeps_its_own_colours(self):
        """A cell may be Rich text of several colours (the WTF Cleaner's reasons, each in its criterion's colour):
        its spans stay, it is cut and padded like a plain cell, and natural_widths measures it the same."""
        reasons = Text.assemble(("Not installed", "red"), ", ", ("Stray copies", "magenta"))
        self.assertEqual(natural_widths([("Details", reasons)]), (7, 27))
        text = column_text(("Details", reasons, "3d"), (7, 27, 2), ("bold", "", "dim"), WIDE_GAP)
        self.assertEqual(text.plain, "Details  Not installed, Stray copies  3d")
        spans = {text.plain[s.start:s.end]: str(s.style) for s in text.spans}
        self.assertEqual((spans["Not installed"], spans["Stray copies"]), ("red", "magenta"))
        self.assertEqual(reasons.plain, "Not installed, Stray copies")  # the cell itself is left as it was
        cut = column_text(("Details", reasons, "3d"), (7, 16, 2), ("bold", "", "dim"), NARROW_GAP)
        self.assertEqual(cut.plain, "Details Not installed, … 3d")
        self.assertIn("red", {str(s.style) for s in cut.spans})

    def test_siblings_line_up(self):
        rows = [("Details", "unused", "2 files"), ("WeakAuras", "", "1 file")]
        widths, gap = fit_columns(natural_widths(rows), None, ColumnLayout((None,) * 3, (1, 1, 1), ((0,),)))
        lines = [column_text(row, widths, ("", "", ""), gap).plain for row in rows]
        self.assertEqual(lines[0].index("2 files"), lines[1].index("1 file"))


class CountTest(unittest.TestCase):
    def test_count_text(self):
        self.assertEqual([count_text(n) for n in (0, 1, 27)], ["0 items", "1 item", "27 items"])

    def test_with_count_appends_the_dim_count_two_spaces_after_the_label(self):
        self.assertEqual(COUNT_STYLE, "dim")
        label = Text.assemble(("Retail", "bold"))
        counted = with_count(label, 100)
        self.assertEqual(counted.plain, "Retail  100 items")
        self.assertEqual(label.plain, "Retail")  # the label itself is left as it was
        self.assertEqual([(counted.plain[s.start:s.end], s.style) for s in counted.spans],
                         [("Retail", "bold"), ("  100 items", "dim")])
        self.assertEqual(with_count("Aellâ", 1).plain, "Aellâ  1 item")


if __name__ == "__main__":
    unittest.main()
