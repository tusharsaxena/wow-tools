"""The shared USE AT YOUR OWN RISK popup (spec 2026-10-07-feedback-bars-leftovers L4): the WTF Cleaner, the Ace3
Profile Manager and the Saved Variables Browser show it after the flavor pick (and the account pick) and before the
first scan, at most once per tool per app session. I understand (focused) goes on and is remembered on the app;
Back or Esc goes back to the flavor picker, logs the tool's declined event and is not remembered."""
from __future__ import annotations

import tempfile
from pathlib import Path

from textual.widgets import Button

from tests.fixtures import (BASE, TuiTestCase, assert_keys_on_buttons, build_ace_tree, build_wow_tree, make_config,
                            settle)
from wowtools.core.events import capture_events
from wowtools.tools.ace3_profile_manager.review_screen import ProfileReviewScreen
from wowtools.tools.sv_browser.review_screen import SvReviewScreen
from wowtools.tools.wtf_cleaner.review_screen import ReviewScreen
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.disclaimer import ACCEPT, BACK, DISCLAIMER_TITLE, DisclaimerScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp
from wowtools.ui.widgets import action_kind

# tool: (review screen, accepted event, declined event, words its text must hold)
TOOLS = {
    "wtf-cleaner": (ReviewScreen, "clean.disclaimer_accepted", "clean.disclaimer_declined",
                    ("deletes", "backup", "Undo", "responsible", "Close WoW")),
    "ace3-profile-manager": (ProfileReviewScreen, "ace.disclaimer_accepted", "ace.disclaimer_declined",
                             ("profile", "backed up", "Undo", "responsible", "Close WoW")),
    "sv-browser": (SvReviewScreen, "svb.disclaimer_accepted", "svb.disclaimer_declined",
                   ("you are responsible for what you change", "Close WoW")),
}


class RiskDisclaimerTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)
        self.root = build_ace_tree(build_wow_tree(self.tmp / "World of Warcraft"))
        self.config_dir = self.tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self):
        options = {"wtf-cleaner": {"wow_check": list, "locker_check": list},
                   "ace3-profile-manager": {"wow_check": list}, "sv-browser": {"wow_check": list}}
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                           tool_options=options)

    async def pick_all(self, app, pilot, tool):
        """Open `tool` from the menu (saving its first-run settings) and pick All flavors."""
        if not isinstance(app.screen, FlavorScreen):
            if app.flow is not None:
                app.close_tool()
                await settle(app, pilot)
            app.open_tool(tool)
            await settle(app, pilot)
            if not isinstance(app.screen, FlavorScreen):
                app.screen._save()  # first open: the tool's settings, saved as they are
                await settle(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        app.screen.dismiss(ALL_FLAVORS)
        await settle(app, pilot)

    async def test_shown_on_the_first_open_of_each_tool_with_its_own_text(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            for tool, (review, accepted, _declined, words) in TOOLS.items():
                with self.subTest(tool=tool):
                    await self.pick_all(app, pilot, tool)
                    popup = app.screen
                    self.assertIsInstance(popup, DisclaimerScreen)
                    self.assertEqual(popup.title_text, DISCLAIMER_TITLE)
                    self.assertEqual(DISCLAIMER_TITLE, "USE AT YOUR OWN RISK")
                    for word in words:
                        self.assertIn(word, popup.message_text)
                    self.assertEqual(popup.message_text.count("\n\n"), 1)  # two short paragraphs
                    self.assertEqual(popup.focused.id, ACCEPT)
                    buttons = {b.id: b for b in popup.query(Button)}
                    self.assertEqual((buttons[ACCEPT].label_text, action_kind(buttons[ACCEPT])),
                                     ("I understand", "confirm"))
                    self.assertEqual((buttons[BACK].label_text, action_kind(buttons[BACK]),
                                      buttons[BACK].shortcut), ("Back", "cancel", "escape"))
                    assert_keys_on_buttons(self, popup)
                    with capture_events() as events:
                        popup.choose(ACCEPT)
                        await settle(app, pilot)
                    self.assertIn(accepted, [e["event"] for e in events])
                    self.assertIsInstance(app.screen, review)

    async def test_not_shown_again_in_the_same_session_once_accepted(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            for tool, (review, *_rest) in TOOLS.items():
                with self.subTest(tool=tool):
                    await self.pick_all(app, pilot, tool)
                    app.screen.choose(ACCEPT)
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, review)
                    app.screen.action_leave("tools")
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ToolMenuScreen)
                    await self.pick_all(app, pilot, tool)  # opened again from the menu
                    self.assertIsInstance(app.screen, review)
                    app.screen.action_leave("flavors")  # and back to the flavor picker
                    await settle(app, pilot)
                    await self.pick_all(app, pilot, tool)
                    self.assertIsInstance(app.screen, review)
                    app.screen.action_leave("tools")
                    await settle(app, pilot)

    async def test_back_or_esc_goes_back_to_the_flavors_and_does_not_count(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            for tool, (review, accepted, declined, _words) in TOOLS.items():
                for answer in ("button", "escape"):
                    with self.subTest(tool=tool, answer=answer):
                        await self.pick_all(app, pilot, tool)
                        self.assertIsInstance(app.screen, DisclaimerScreen)
                        with capture_events() as events:
                            if answer == "button":
                                await pilot.click("#back")
                            else:
                                await pilot.press("escape")
                            await settle(app, pilot)
                        names = [e["event"] for e in events]
                        self.assertIn(declined, names)
                        self.assertNotIn(accepted, names)
                        self.assertIsInstance(app.screen, FlavorScreen)
                        await self.pick_all(app, pilot, tool)  # asked again: Back did not count
                        self.assertIsInstance(app.screen, DisclaimerScreen)
                        app.screen.dismiss(None)
                        await settle(app, pilot)
                        app.close_tool()
                        await settle(app, pilot)
                        await self.pick_all(app, pilot, tool)  # and after reopening the tool
                        self.assertIsInstance(app.screen, DisclaimerScreen)
                        app.screen.dismiss(None)
                        await settle(app, pilot)
                        app.close_tool()
                        await settle(app, pilot)

    async def test_each_tool_asks_on_its_own(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            await self.pick_all(app, pilot, "wtf-cleaner")
            app.screen.choose(ACCEPT)
            await settle(app, pilot)
            app.screen.action_leave("tools")
            await settle(app, pilot)
            for tool in ("ace3-profile-manager", "sv-browser"):
                with self.subTest(tool=tool):
                    await self.pick_all(app, pilot, tool)
                    self.assertIsInstance(app.screen, DisclaimerScreen)
                    app.screen.dismiss(None)
                    await settle(app, pilot)
                    app.close_tool()
                    await settle(app, pilot)
            await self.pick_all(app, pilot, "wtf-cleaner")
            self.assertIsInstance(app.screen, ReviewScreen)

    async def test_wtf_cleaner_asks_after_the_account_pick(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            app.open_tool("wtf-cleaner")
            await settle(app, pilot)
            if not isinstance(app.screen, FlavorScreen):
                app.screen._save()
                await settle(app, pilot)
            picker = app.screen
            picker.dismiss(next(f for f in picker.flavors if f.folder == "_retail_"))  # two accounts
            await settle(app, pilot)
            self.assertIsInstance(app.screen, AccountScreen)
            app.screen.dismiss("")  # All accounts
            await settle(app, pilot)
            self.assertIsInstance(app.screen, DisclaimerScreen)
            with capture_events() as events:
                app.screen.choose(ACCEPT)
                await settle(app, pilot)
            accepted = [e for e in events if e["event"] == "clean.disclaimer_accepted"]
            self.assertEqual(len(accepted), 1)
            self.assertEqual(accepted[0]["data"]["flavors"], ["_retail_"])
            self.assertIsInstance(app.screen, ReviewScreen)
