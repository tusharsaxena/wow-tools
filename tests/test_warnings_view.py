"""Spec W1/W2 on every tool's review: with warnings the bottom line shows the Warnings button ("⚠ N ... (!)"), `!` and
a click open the warnings view listing every one of them, Esc comes back to the review as it was, and h there opens
the tool's help, which names the view's buttons. Without warnings no button shows. (The Interface Backup restore
screen: tests/test_interface_backup_app.py.)"""
from __future__ import annotations

import tempfile
from pathlib import Path

from textual.widgets import Tree

from tests.fixtures import (BASE, TINY, TuiTestCase, accept_disclaimer, build_ace_tree, build_interface_tree,
                            build_screenshot_tree, build_sv_tree, build_wow_tree, make_config, settle)
from wowtools.core.svfiles import SvScanWarning
from wowtools.tools import TOOLS
from wowtools.tools.screenshot_organizer.planner import PlanWarning
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.help_screen import HelpScreen
from wowtools.ui.suite_app import WowToolsApp
from wowtools.ui.warnings_view import WARNINGS_BUTTON_ID, WarningsScreen


def add_warnings(tool: str, review) -> None:
    """Give a review warnings the fixtures do not produce (the WTF Cleaner's garbage AddOns.txt line is a real one), then let it update its bottom line."""
    if tool == "screenshot-organizer":
        flavor = review.plan.flavors[0].flavor
        review.plan.warnings += [PlanWarning(flavor.display_name, "C:\\Shots\\2024", "[Errno 13] Permission denied"),
                                 PlanWarning(flavor.display_name, "C:\\Shots\\2025", "[Errno 13] Permission denied")]
    elif tool == "interface-backup":
        review.scans[0].parts["Interface"].errors.append("Interface/AddOns/Locked: access denied")
    elif tool == "ace3-profile-manager":
        review.scan.flavors[0].warnings.append(SvScanWarning(Path("/wow/WTF/Odd.lua"), "Odd.lua is not readable Lua"))
    elif tool == "sv-browser":
        review.scan.flavors[0].warnings.append(SvScanWarning(Path("/wow/WTF/x"), "skipped: under a link"))
    review._update_summary()


def leaves(tree: Tree) -> list:
    found, stack = [], list(tree.root.children)
    while stack:
        node = stack.pop()
        if node.children:
            stack.extend(node.children)
        else:
            found.append(node)
    return found


class WarningsViewToolsTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        tmp = Path(t.name)
        self.root = build_sv_tree(build_ace_tree(build_interface_tree(build_screenshot_tree(
            build_wow_tree(tmp / "World of Warcraft")))))
        self.config_dir = tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self):
        options = {"wtf-cleaner": {"wow_check": list, "locker_check": list},
                   "interface-backup": {"wow_check": list}, "ace3-profile-manager": {"wow_check": list},
                   "sv-browser": {"wow_check": list}}
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options=options)

    async def open_review(self, app, pilot, tool):
        await pilot.pause()
        app.open_tool(tool)
        await settle(app, pilot)
        if not isinstance(app.screen, FlavorScreen):
            app.screen._save()
            await settle(app, pilot)
        app.screen.dismiss(ALL_FLAVORS)
        await settle(app, pilot)
        await accept_disclaimer(app, pilot)
        return app.screen

    async def test_every_review_opens_its_warnings(self):
        for size in (BASE, TINY):
            for tool in TOOLS:
                with self.subTest(tool=tool, size=size):
                    app = self.make_app()
                    async with app.run_test(size=size) as pilot:
                        review = await self.open_review(app, pilot, tool)
                        add_warnings(tool, review)
                        await settle(app, pilot)
                        items = review.warning_items()
                        self.assertTrue(items)
                        button = review.query_one(f"#{WARNINGS_BUTTON_ID}")
                        self.assertTrue(button.display)
                        self.assertIn(f"⚠ {len(items)} ", button.label.plain)
                        self.assertTrue(button.label.plain.endswith("(!)"))
                        self.assertGreater(button.region.width, 0)
                        self.assertLessEqual(button.region.right, size[0])
                        self.assertNotIn("see the log", review.summary_text)
                        self.assertNotIn("see the tree", review.summary_text)
                        self.assertNotIn("scan warning", review.summary_text)  # on the button now
                        focused = review.focused
                        for how in ("key", "click"):
                            if how == "key":
                                await pilot.press("exclamation_mark")
                            else:
                                await pilot.click(f"#{WARNINGS_BUTTON_ID}")
                            await settle(app, pilot)
                            view = app.screen
                            self.assertIsInstance(view, WarningsScreen, how)
                            shown = [str(leaf.label) for leaf in leaves(view.query_one("#warnings", Tree))]
                            self.assertEqual(len(shown), len(items))
                            for item in items:
                                self.assertTrue(any(item.what in text for text in shown), item)
                            await pilot.press("escape")
                            await settle(app, pilot)
                            self.assertIs(app.screen, review)
                            self.assertIs(review.focused, focused)

    async def test_h_on_the_view_opens_the_tool_help_naming_its_buttons(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    review = await self.open_review(app, pilot, tool)
                    add_warnings(tool, review)
                    await settle(app, pilot)
                    review.action_show_warnings()
                    await settle(app, pilot)
                    view = app.screen
                    self.assertIsInstance(view, WarningsScreen)
                    await pilot.press("h")
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, HelpScreen)
                    text = TOOLS[tool].help()
                    self.assertEqual(app.screen.text, text)
                    for label in ("**Warnings**", "**Back**", "`!`"):
                        self.assertIn(label, text)
                    await pilot.press("escape")
                    await settle(app, pilot)
                    self.assertIs(app.screen, view)

    async def test_no_warnings_no_button(self):
        """The Screenshot Organizer reads every fixture folder: no warnings, no button, and `!` does nothing."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            app.open_tool("screenshot-organizer")
            await settle(app, pilot)
            if not isinstance(app.screen, FlavorScreen):
                app.screen._save()
                await settle(app, pilot)
            app.screen.dismiss(ALL_FLAVORS)
            await settle(app, pilot)
            review = app.screen
            self.assertEqual(review.warning_items(), [])
            self.assertFalse(review.query_one(f"#{WARNINGS_BUTTON_ID}").display)
            await pilot.press("exclamation_mark")
            await settle(app, pilot)
            self.assertIs(app.screen, review)


if __name__ == "__main__":
    import unittest
    unittest.main()
