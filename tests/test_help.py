"""The help screen (spec D18): h on the tool menu shows the suite's help, h on any screen of a tool shows that tool's,
never over a popup; Esc, q or h goes back to the screen as it was. Every tool has help that names each button of its
screens and links to a guide that exists in the repo."""
from __future__ import annotations

import re
import tempfile
import threading
import unittest
from pathlib import Path

from textual.widgets import Markdown
from textual.widgets._footer import FooterKey

from tests.fixtures import (BASE, TINY, TuiTestCase, build_ace_tree, build_interface_tree, build_screenshot_tree,
                            build_wow_tree, make_config, settle)
from wowtools import __version__
from wowtools.core.install import WowInstall
from wowtools.tools import TOOLS
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.branding import BottomBar
from wowtools.ui.changelog_screen import ChangelogScreen
from wowtools.ui.dialogs import ConfirmScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.help_screen import README_URL, HelpScreen, suite_help
from wowtools.ui.result_screen import ResultBase
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp
from wowtools.ui.tree_filter import FilterInput
from wowtools.ui.widgets import ActionButton

REPO = Path(__file__).resolve().parent.parent
GITHUB = "https://github.com/tusharsaxena/wow-tools"
URL = re.compile(r"https://[^\s)\]>]+")
# The action that leads to a result screen without a running-WoW popup in between, and what it needs first.
RUN_ACTION = {"wtf-cleaner": "dry_run", "screenshot-organizer": "dry_run", "interface-backup": "back_up",
              "ace3-profile-manager": "dry_run"}
PREPARE = {"ace3-profile-manager": lambda review: (review.staging.everyone_to_default(list(review.staging.states)),
                                                   review.refresh_view())}


def url_target(url: str) -> Path:
    """The file in this repo a GitHub URL of this project points at."""
    if url in (README_URL, GITHUB):
        return REPO / "README.md"
    prefix = f"{GITHUB}/blob/master/"
    if not url.startswith(prefix):
        raise AssertionError(f"not a link into this repo: {url}")
    return REPO / url.removeprefix(prefix).split("#")[0]


class HelpTextTest(unittest.TestCase):
    def test_every_tool_has_help_with_its_guide(self):
        for tool in TOOLS.values():
            with self.subTest(tool=tool.name):
                text = tool.help()
                self.assertGreater(len(text), 500)
                guide = f"{GITHUB}/blob/master/docs/{tool.name}.md"
                self.assertIn(guide, text)
                self.assertTrue(url_target(guide).is_file(), guide)

    def test_suite_help_names_every_tool_and_links_the_readme(self):
        text = suite_help()
        for tool in TOOLS.values():
            self.assertIn(tool.title, text)
            self.assertIn(tool.description, text)
        self.assertIn(README_URL, text)
        for key in ("`s`", "`h`", "`u`", "`c`", "`q`", "`/`", "at once", "Terms of use"):
            self.assertIn(key, text)

    def test_every_help_link_points_at_a_file_in_the_repo(self):
        for name, text in [("suite", suite_help()), *((t.name, t.help()) for t in TOOLS.values())]:
            urls = URL.findall(text)
            self.assertTrue(urls, name)
            for url in urls:
                with self.subTest(help=name, url=url):
                    self.assertTrue(url_target(url).is_file(), url)


class HelpScreenTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        tmp = Path(t.name)
        self.root = build_ace_tree(build_interface_tree(build_screenshot_tree(build_wow_tree(tmp / "World of Warcraft"))))
        self.config_dir = tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self):
        options = {"wtf-cleaner": {"wow_check": list, "locker_check": list},
                   "interface-backup": {"wow_check": list}, "ace3-profile-manager": {"wow_check": list}}
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options=options)

    async def open_flavors(self, app, pilot, tool):
        await pilot.pause()
        app.open_tool(tool)
        await settle(app, pilot)
        if not isinstance(app.screen, FlavorScreen):
            app.screen._save()  # first open: the tool's settings, saved as they are
            await settle(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        return app.screen

    async def assert_help(self, app, pilot, text, *, close="escape"):
        """h opens the help showing `text`, with Help nowhere in its footer; `close` goes back to the same screen,
        with the same widget focused."""
        before, focused = app.screen, app.screen.focused
        await pilot.press("h")
        await settle(app, pilot)
        self.assertIsInstance(app.screen, HelpScreen, before)
        self.assertEqual(app.screen.text, text)
        self.assertEqual(app.screen.query_one(Markdown).source, text)
        footer = {key.key for key in app.screen.query(FooterKey)}
        self.assertNotIn("h", footer)
        self.assertNotIn("s", footer)  # no settings over the help
        await pilot.press(close)
        await settle(app, pilot)
        self.assertIs(app.screen, before)
        self.assertIs(app.screen.focused, focused)

    async def test_h_on_the_menu_and_the_changelog_opens_the_suite_help(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen, ToolMenuScreen)
            self.assertIn("h", {key.key for key in app.screen.query(FooterKey)})  # "h Help" in the footer
            for close in ("escape", "q", "h"):
                await self.assert_help(app, pilot, suite_help(), close=close)
            self.assertIsInstance(app.screen, ToolMenuScreen)  # q closed the help, it did not quit
            app.push_screen(ChangelogScreen())
            await settle(app, pilot)
            await self.assert_help(app, pilot, suite_help())

    async def test_h_on_every_screen_of_a_tool_opens_its_help(self):
        """The flavor picker, the review, the tool's settings, the result; the Ace3 blacklist. The help names every
        button those screens show."""
        for name, tool in TOOLS.items():
            with self.subTest(tool=name):
                text = tool.help()
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    picker = await self.open_flavors(app, pilot, name)
                    await self.assert_help(app, pilot, text)
                    picker.dismiss(ALL_FLAVORS)
                    await settle(app, pilot)
                    review = app.screen
                    labels = {b.label_text for b in review.query(ActionButton)}
                    self.assertTrue(labels)
                    await self.assert_help(app, pilot, text)
                    app.push_screen(app.flow.settings_screen("settings"))
                    await settle(app, pilot)
                    labels |= {b.label_text for b in app.screen.query(ActionButton)}
                    app.screen.query_one("#save").focus()  # the first field has focus: h would type there
                    await pilot.pause()
                    await self.assert_help(app, pilot, text)
                    app.screen.dismiss(False)
                    await settle(app, pilot)
                    self.assertIs(app.screen, review)
                    if name == "ace3-profile-manager":
                        review.action_edit_blacklist()
                        await settle(app, pilot)
                        labels |= {b.label_text for b in app.screen.query(ActionButton)}
                        await self.assert_help(app, pilot, text)
                        app.screen.dismiss(None)
                        await settle(app, pilot)
                    PREPARE.get(name, lambda r: None)(review)
                    getattr(review, f"action_{RUN_ACTION[name]}")()
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmScreen)
                    await pilot.press("h")  # never over a popup
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmScreen)
                    self.assertNotIn("h", {key.key for key in app.screen.query(FooterKey)})
                    app.screen.dismiss(True)
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ResultBase)
                    labels |= {b.label_text for b in app.screen.query(ActionButton)}
                    await self.assert_help(app, pilot, text)
                    for label in sorted(labels - {"Save", "Cancel"}):  # the forms' own buttons
                        self.assertIn(f"**{label}**", text)

    async def test_h_on_the_account_picker_opens_the_tool_help(self):
        """The account picker (a game version with two accounts) is a tool screen too."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_flavors(app, pilot, "ace3-profile-manager")
            retail = next(f for f in WowInstall(self.root).flavors() if f.folder == "_retail_")
            self.assertGreater(len(retail.accounts()), 1)
            app.flow.pick_account(retail, lambda _account: None)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, AccountScreen)
            await self.assert_help(app, pilot, TOOLS["ace3-profile-manager"].help())

    async def test_h_and_s_wait_for_the_running_programs_check(self):
        """While a review's running-programs check runs, h and s do nothing (and leave the footer): leaving the
        screen then would drop the confirm the check leads to. Once it is done the confirm opens."""
        release = threading.Event()

        def slow_check():
            release.wait(10)
            return []

        app = self.make_app()
        app.tool_options["wtf-cleaner"] = {"wow_check": slow_check, "locker_check": list}
        async with app.run_test(size=BASE) as pilot:
            picker = await self.open_flavors(app, pilot, "wtf-cleaner")
            picker.dismiss(ALL_FLAVORS)
            await settle(app, pilot)
            review = app.screen
            review.action_clean()
            await pilot.pause()
            self.assertTrue(review._checking)
            await pilot.press("h", "s")
            await pilot.pause()
            self.assertIs(app.screen, review)
            footer = {key.key for key in review.query(FooterKey)}
            self.assertFalse(footer & {"h", "s"}, footer)
            release.set()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            app.screen.dismiss(False)
            await settle(app, pilot)
            self.assertIn("h", {key.key for key in review.query(FooterKey)})

    async def test_every_footer_key_shows_at_tiny(self):
        """At 80 columns a review's keys don't fit one row: the footer wraps into two, so h Help (and s, q) stay on
        screen, with the version still beside them."""
        for name in TOOLS:
            with self.subTest(tool=name):
                app = self.make_app()
                async with app.run_test(size=TINY) as pilot:
                    picker = await self.open_flavors(app, pilot, name)
                    picker.dismiss(ALL_FLAVORS)
                    await settle(app, pilot)
                    keys = list(app.screen.query(FooterKey))
                    self.assertTrue({"h", "s", "q"} <= {key.key for key in keys})
                    for key in keys:
                        self.assertLessEqual(key.region.right, TINY[0], key)
                        self.assertGreater(key.region.width, 0, key)
                    self.assertEqual(app.screen.query_one(BottomBar).region.height, 2)
                    self.assertIn(f"v{__version__}", "".join(strip.text for strip in
                                                            app.screen._compositor.render_strips()))

    async def test_h_types_in_a_text_box(self):
        """h is not a priority key: in the filter box it is a letter of the filter."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            picker = await self.open_flavors(app, pilot, "wtf-cleaner")
            picker.dismiss(ALL_FLAVORS)
            await settle(app, pilot)
            review = app.screen
            await pilot.press("slash", "h")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertEqual(review.query_one(FilterInput).value, "h")

    async def test_help_fits_and_scrolls_at_tiny(self):
        app = self.make_app()
        async with app.run_test(size=TINY) as pilot:
            await pilot.pause()
            await pilot.press("h")
            await settle(app, pilot)
            body = app.screen.query_one("#help-body")
            self.assertIs(app.screen.focused, body)
            self.assertGreater(body.max_scroll_y, 0)
            await pilot.press("pagedown")
            await settle(app, pilot)
            self.assertGreater(body.scroll_y, 0)


if __name__ == "__main__":
    unittest.main()
