"""The shared dialogs and tree helpers in wowtools/ui/dialogs.py (F-009). The TUI tests of both tools drive them
on real screens; these pin the small pieces on their own."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import ClassVar

from wowtools.ui.dialogs import ProgressScreen, theme_colour, tick_mark
from wowtools.ui.theme import KA0S_THEME
from wowtools.ui.widgets import CHECK_OFF, CHECK_ON


class DialogHelpersTest(unittest.TestCase):
    def test_tick_mark(self):
        self.assertEqual(tick_mark([1, 2], set(), success="#00FF00"), (f"{CHECK_ON} ", "bold #00FF00"))
        self.assertEqual(tick_mark([1, 2], {1}), ("◩ ", "bold"))
        self.assertEqual(tick_mark([1, 2], {1, 2}), (f"{CHECK_OFF} ", "dim"))
        self.assertEqual(tick_mark([], {1}), (f"{CHECK_ON} ", f"bold {KA0S_THEME.success}"))
        items = [SimpleNamespace(src="a"), SimpleNamespace(src="b")]
        self.assertEqual(tick_mark(items, {"a", "b"}, lambda i: i.src)[0], f"{CHECK_OFF} ")

    def test_theme_colour_falls_back_to_ka0s(self):
        self.assertEqual(theme_colour(None, "success"), KA0S_THEME.success)
        app = SimpleNamespace(current_theme=SimpleNamespace(success="#123456", warning=None))
        self.assertEqual(theme_colour(app, "success"), "#123456")
        self.assertEqual(theme_colour(app, "warning"), KA0S_THEME.warning)

    def test_progress_stage_titles(self):
        class Demo(ProgressScreen):
            ID_PREFIX = "demo"
            STAGE_TITLES: ClassVar[dict[str, str]] = {"work": "Working", "undo": "Undoing"}
            SIMULATED_STAGE = "work"

        self.assertEqual(Demo(first_stage="work").stage_title("work"), "Working")
        dry = Demo(dry_run=True, first_stage="work")
        self.assertEqual((dry.stage_title("work"), dry.stage_title("undo"), dry.stage_title("x")),
                         ("Simulating", "Undoing", "x"))
        dry.set_flavor("Retail")
        self.assertEqual(dry.stage_title("undo"), "Retail: Undoing")
