"""One look and feel across the tools: the review screens share the left pane, its one-row action buttons and the
hint shape; the result screens share their layout and hint; Esc on a review goes back to the flavor picker. Each
check runs at the default terminal size (80x24), where the left pane is tightest."""
from __future__ import annotations

import tempfile
from pathlib import Path

from textual.widgets import Button, Checkbox, DataTable, Tree

from tests.fixtures import (TuiTestCase, build_ace_tree, build_interface_tree, build_screenshot_tree, build_wow_tree,
                            make_config, settle)
from wowtools.tools import TOOLS as TOOL_INFO
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import FILTERS_WIDTH, RESULT_HINT, REVIEW_HINT, TREE_HINT, ConfirmScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import WowToolsApp
from wowtools.ui.widgets import NavHint

SMALL = (80, 24)
TOOLS = ("wtf-cleaner", "screenshot-organizer", "interface-backup", "ace-profiles")
# The action that leads to a result screen without a running-WoW popup in between (dry runs, a backup).
RUN_ACTION = {"wtf-cleaner": "dry_run", "screenshot-organizer": "dry_run", "interface-backup": "back_up",
              "ace-profiles": "dry_run"}
# What a review needs before its run action has something to do (the Ace3 Profile Manager runs staged changes).
PREPARE = {"ace-profiles": lambda review: (review.staging.everyone_to_default(list(review.staging.states)),
                                           review.refresh_view())}


def walk(node):
    """node and every node below it."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(current.children)


class LookAndFeelTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        tmp = Path(t.name)
        self.root = build_ace_tree(build_interface_tree(build_screenshot_tree(build_wow_tree(tmp / "World of Warcraft"))))
        self.config_dir = tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self):
        options = {"wtf-cleaner": {"wow_check": list, "locker_check": list},
                   "interface-backup": {"wow_check": list}, "ace-profiles": {"wow_check": list}}
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

    async def test_review_left_pane_has_one_control_per_row(self):
        """Every focusable control of the left pane sits on its own row, so up/down reaches each one; only the
        action buttons share a row (left/right moves there)."""
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=SMALL) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    actions = review.query_one("#actions")
                    controls = [w for w in review.query_one("#filters").query("*")
                                if w.focusable and actions not in w.ancestors]
                    rows = [w.region.y for w in controls]
                    self.assertEqual(len(rows), len(set(rows)), [(w.id, w.region) for w in controls])

    async def test_review_tree_expands_and_collapses_all(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=SMALL) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    self.assertIn(TREE_HINT + "r rescan", str(review.query_one(NavHint).render()))
                    self.assertTrue(TREE_HINT.startswith("x expand all · c collapse all"))
                    tree = review.query_one(review.TREE_SELECTOR, Tree)
                    tree.focus()
                    await pilot.press("x")
                    await settle(app, pilot)
                    parents = [n for n in walk(tree.root) if n.children]
                    self.assertGreater(len(parents), 1)
                    self.assertEqual([n for n in parents if not n.is_expanded], [])
                    await pilot.press("c")
                    await settle(app, pilot)
                    self.assertEqual([n for n in walk(tree.root) if n.is_expanded], [tree.root])
                    self.assertIs(app.screen, review)  # c collapses: it never starts a run

    async def test_result_screens_share_one_layout(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=SMALL) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    PREPARE.get(tool, lambda r: None)(review)
                    getattr(review, f"action_{RUN_ACTION[tool]}")()
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmScreen)
                    body = app.screen.title_text + "\n" + app.screen.body_text
                    self.assertIn("Retail", body)  # flavors by name, as in the result tables
                    self.assertNotRegex(body, r"(?<![/\\\w])_[a-z]+(_[a-z]+)*_(?![/\\\w])", body)  # never a bare folder
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

    async def test_settings_screens_open_at_the_title_and_fit(self):
        """Each settings form opens showing its title (not scrolled down to the focused field) and no checkbox
        label runs past the right edge at 80 columns."""
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=SMALL) as pilot:
                    await pilot.pause()
                    app.open_tool(tool)
                    await settle(app, pilot)
                    screen = app.screen
                    form = screen.query_one("#settings")
                    self.assertEqual(form.scroll_y, 0)
                    self.assert_inside(screen.query_one(".title"), form.region)
                    self.assert_inside(screen.focused, form.region)
                    for box in screen.query(Checkbox):
                        self.assertLessEqual(box.region.right, form.content_region.right, box.id)
                        self.assertGreaterEqual(box.content_size.width, box.get_content_width(box.size, box.size),
                                                box.id)  # the whole label, not cut with an ellipsis
