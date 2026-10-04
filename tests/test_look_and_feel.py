"""One look and feel across the tools: the review screens share the left pane, its one-row action buttons and the
hint shape; the result screens share their layout and hint; Esc on a review goes back to the flavor picker. Each
check runs at the default terminal size (80x24), where the left pane is tightest."""
from __future__ import annotations

import tempfile
from pathlib import Path

from textual.widgets import Button, DataTable

from tests.fixtures import (TuiTestCase, build_interface_tree, build_screenshot_tree, build_wow_tree, make_config,
                            settle)
from wowtools.tools import TOOLS as TOOL_INFO
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import FILTERS_WIDTH, RESULT_HINT, REVIEW_HINT, ConfirmScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import WowToolsApp
from wowtools.ui.widgets import NavHint

SMALL = (80, 24)
TOOLS = ("wtf-cleaner", "screenshot-organizer", "interface-backup")
# The action that leads to a result screen without a running-WoW popup in between (dry runs, a backup).
RUN_ACTION = {"wtf-cleaner": "dry_run", "screenshot-organizer": "dry_run", "interface-backup": "back_up"}


class LookAndFeelTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        tmp = Path(t.name)
        self.root = build_interface_tree(build_screenshot_tree(build_wow_tree(tmp / "World of Warcraft")))
        self.config_dir = tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self):
        options = {"wtf-cleaner": {"wow_check": list, "locker_check": list},
                   "interface-backup": {"wow_check": list}}
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options=options)

    async def open_review(self, app, pilot, tool):
        await pilot.pause()
        app.open_tool(tool)
        await settle(app, pilot)
        app.screen._save()  # first open: the tool's settings, saved as they are
        await settle(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        app.screen.dismiss(ALL_FLAVORS)
        await settle(app, pilot)
        return app.screen

    def assert_inside(self, widget, box):
        r = widget.region
        self.assertTrue(r.width > 0 and r.height > 0, f"{widget!r} is not shown: {r}")
        self.assertTrue(box.x <= r.x and box.y <= r.y and r.right <= box.right and r.bottom <= box.bottom,
                        f"{widget!r} is cut off: {r} not inside {box}")

    async def test_review_left_pane_is_the_same_in_every_tool(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=SMALL) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    filters = review.query_one("#filters")
                    self.assertEqual(filters.outer_size.width, FILTERS_WIDTH)
                    buttons = list(review.query_one("#actions").query(Button))
                    self.assertEqual(len(buttons), 4)
                    self.assertEqual({b.region.y for b in buttons}, {buttons[0].region.y})  # one row
                    self.assertTrue(buttons[-1].label.plain.startswith("Undo last "), buttons[-1].label)
                    self.assertEqual(buttons[-1].variant, "warning")  # revert
                    self.assertEqual(buttons[2].label.plain, "Rescan")
                    hint = review.query_one(NavHint)
                    pane = filters.region
                    inside = pane._replace(width=pane.width - 1)  # anything but the border: not cut off
                    for widget in (*buttons, hint):
                        self.assert_inside(widget, inside)
                    text = str(hint.render())
                    self.assertTrue(text.startswith(REVIEW_HINT), text)
                    self.assertIn("r rescan · z undo · f flavors · t tools", text)
                    self.assertTrue(review.summary_text.startswith(("Selected: ", "Nothing to")),
                                    review.summary_text)
                    self.assertTrue(review.sub_title.startswith(f"{TOOL_INFO[tool].title} · All flavors"),
                                    review.sub_title)
                    await pilot.press("escape")  # Esc: back to the flavor picker, as f
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, FlavorScreen)

    async def test_result_screens_share_one_layout(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=SMALL) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    getattr(review, f"action_{RUN_ACTION[tool]}")()
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmScreen)
                    app.screen.dismiss(True)
                    await settle(app, pilot)
                    result = app.screen
                    self.assertTrue(result.sub_title.startswith(f"{TOOL_INFO[tool].title} · "), result.sub_title)
                    self.assertTrue(result.sub_title.endswith("result"), result.sub_title)
                    summary = result.query_one("#result-summary", DataTable)
                    self.assertEqual([c.label.plain for c in summary.columns.values()], ["Item", "Value"])
                    self.assertEqual(len(result.query(".result-detail")), 1)
                    result.query_one(BrandBar)
                    hint = str(result.query_one(NavHint).render())
                    self.assertTrue(hint.startswith(RESULT_HINT), hint)
                    self.assertTrue(hint.endswith("f other flavor · t tools · q quit"), hint)
                    buttons = list(result.query(Button))
                    labels = [b.label.plain for b in buttons]
                    self.assertEqual(labels[0], "Rescan (r)")
                    self.assertEqual(labels[-3:], ["Other flavor (f)", "Tools (t)", "Quit (q)"])
                    for button in buttons:
                        self.assert_inside(button, app.screen.region)
                    self.assertEqual({b.region.y for b in buttons}, {buttons[0].region.y})
