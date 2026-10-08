"""The shared USE AT YOUR OWN RISK popup (spec 2026-10-07-feedback-bars-leftovers L4): the WTF Cleaner, the Ace3
Profile Manager and the Saved Variables Browser show it after the flavor pick (and the account pick) and before the
first scan, at most once per tool per app session. I understand (focused) goes on and is remembered on the app;
Back or Esc goes back to the flavor picker, logs the tool's declined event and is not remembered."""
from __future__ import annotations

import tempfile
from pathlib import Path

from textual.widgets import Button, Checkbox

from tests.fixtures import (BASE, TuiTestCase, assert_keys_on_buttons, build_ace_tree, build_wow_tree, make_config,
                            settle)
from wowtools.core.events import capture_events
from wowtools.tools.ace3_profile_manager.review_screen import ProfileReviewScreen
from wowtools.tools.sv_browser.review_screen import SvReviewScreen
from wowtools.tools.wtf_cleaner.review_screen import ReviewScreen
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.dialogs import CONFIRM_GUARD
from wowtools.ui.disclaimer import ACCEPT, BACK, DISCLAIMER_TITLE, DONT_SHOW, DONT_SHOW_LABEL, DisclaimerScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.settings_form import SHOW_RISK_WARNING_ID, SHOW_RISK_WARNING_LABEL
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


class DisclaimerTestBase(TuiTestCase):
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


class RiskDisclaimerTest(DisclaimerTestBase):

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


# L8: tool: (config file section, the registered event logged when the warning is turned off or on)
RISK_EVENTS = {"wtf-cleaner": ("wtf_cleaner", "clean.risk_warning_changed"),
               "ace3-profile-manager": ("ace3_profile_manager", "ace.risk_warning_changed"),
               "sv-browser": ("sv_browser", "svb.risk_warning_changed")}


class DontShowAgainTest(DisclaimerTestBase):
    """L8: the popup's "Don't show this warning again for this tool" box. Ticked and I understand saves
    skip_risk_warning = true in that tool's config section, and the popup is not shown in a later session; Back and
    Esc never save; the tool's settings form has a "Show the USE AT YOUR OWN RISK warning" box to turn it back on."""

    def tool_cfg(self, tool):
        from wowtools.core.config import Config, tool_config_path
        return Config(tool_config_path(tool, self.config_dir)).load()

    async def test_the_box_is_reached_with_tab_ticked_with_space_and_enter_still_accepts(self):
        for tool, (review, *_rest) in TOOLS.items():
            section, event = RISK_EVENTS[tool]
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    await pilot.pause()
                    await self.pick_all(app, pilot, tool)
                    popup = app.screen
                    self.assertIsInstance(popup, DisclaimerScreen)
                    box = popup.query_one(f"#{DONT_SHOW}", Checkbox)
                    self.assertEqual(box.label.plain, DONT_SHOW_LABEL)
                    self.assertFalse(box.value)
                    self.assertEqual(popup.focused.id, ACCEPT)  # Enter on the popup still presses I understand
                    self.assert_inside_popup(popup, box)
                    await pilot.press("tab")
                    self.assertIs(popup.focused, box)
                    await pilot.press("space")
                    self.assertTrue(box.value)
                    with capture_events() as events:
                        await pilot.press("enter")  # on the box: I understand, not a second tick
                        await settle(app, pilot)
                    self.assertIsInstance(app.screen, review)
                    names = [e["event"] for e in events]
                    self.assertIn(TOOLS[tool][1], names)
                    changed = [e for e in events if e["event"] == event]
                    self.assertEqual(len(changed), 1)
                    self.assertEqual(changed[0]["data"]["shown"], False)
                    self.assertTrue(self.tool_cfg(tool).get_bool(section, "skip_risk_warning", False))
                app = self.make_app()  # a later session: the review opens at once
                async with app.run_test(size=BASE) as pilot:
                    await pilot.pause()
                    await self.pick_all(app, pilot, tool)
                    self.assertIsInstance(app.screen, review)

    def assert_inside_popup(self, popup, widget):
        region = popup.query_one("#choice-box").region
        self.assertTrue(region.contains_region(widget.region), (widget.region, region))

    async def test_enter_on_i_understand_with_the_box_ticked_saves_too(self):
        tool = "sv-browser"
        section, _event = RISK_EVENTS[tool]
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            await self.pick_all(app, pilot, tool)
            popup = app.screen
            popup.query_one(f"#{DONT_SHOW}", Checkbox).value = True
            popup.query_one(f"#{ACCEPT}", Button).focus()
            await pilot.press("enter")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, SvReviewScreen)
        self.assertTrue(self.tool_cfg(tool).get_bool(section, "skip_risk_warning", False))

    async def test_back_and_esc_never_save_and_unticked_saves_nothing(self):
        for tool in TOOLS:
            section, event = RISK_EVENTS[tool]
            for answer in ("button", "escape", "accept-unticked"):
                with self.subTest(tool=tool, answer=answer):
                    app = self.make_app()
                    async with app.run_test(size=BASE) as pilot:
                        await pilot.pause()
                        await self.pick_all(app, pilot, tool)
                        popup = app.screen
                        box = popup.query_one(f"#{DONT_SHOW}", Checkbox)
                        box.value = answer != "accept-unticked"
                        with capture_events() as events:
                            if answer == "button":
                                await pilot.click("#back")
                            elif answer == "escape":
                                await pilot.press("escape")
                            else:
                                popup.choose(ACCEPT)
                            await settle(app, pilot)
                        self.assertNotIn(event, [e["event"] for e in events])
                    self.assertFalse(self.tool_cfg(tool).get_bool(section, "skip_risk_warning", False))
                    app = self.make_app()  # still asked in a later session
                    async with app.run_test(size=BASE) as pilot:
                        await pilot.pause()
                        await self.pick_all(app, pilot, tool)
                        self.assertIsInstance(app.screen, DisclaimerScreen)

    async def test_the_settings_form_turns_the_warning_back_on(self):
        for tool, (review, *_rest) in TOOLS.items():
            section, event = RISK_EVENTS[tool]
            with self.subTest(tool=tool):
                cfg = self.tool_cfg(tool)
                cfg.set(section, "skip_risk_warning", True)
                cfg.save()
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    await pilot.pause()
                    app.open_tool(tool)
                    await settle(app, pilot)
                    app.push_screen(app.flow.settings_screen("settings"))
                    await settle(app, pilot)
                    form = app.screen
                    box = form.query_one(f"#{SHOW_RISK_WARNING_ID}", Checkbox)
                    self.assertEqual(box.label.plain, SHOW_RISK_WARNING_LABEL)
                    self.assertFalse(box.value)  # turned off: not shown
                    box.value = True
                    with capture_events() as events:
                        form._save()
                        await settle(app, pilot)
                    changed = [e for e in events if e["event"] == event]
                    self.assertEqual(len(changed), 1)
                    self.assertEqual((changed[0]["data"]["shown"], changed[0]["data"]["source"]), (True, "settings"))
                    self.assertFalse(self.tool_cfg(tool).get_bool(section, "skip_risk_warning", True))
                    app.screen.dismiss(ALL_FLAVORS)  # the flavor picker under the form
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, DisclaimerScreen)  # shown again
                    app.screen.choose(ACCEPT)
                    await settle(app, pilot)
                    app.push_screen(app.flow.settings_screen("settings"))
                    await settle(app, pilot)
                    form = app.screen
                    box = form.query_one(f"#{SHOW_RISK_WARNING_ID}", Checkbox)
                    self.assertTrue(box.value)
                    box.value = False  # and off again from the form
                    with capture_events() as events:
                        form._save()
                        await settle(app, pilot)
                    changed = [e for e in events if e["event"] == event]
                    self.assertEqual([e["data"]["shown"] for e in changed], [False])
                    self.assertTrue(self.tool_cfg(tool).get_bool(section, "skip_risk_warning", False))
                    with capture_events() as events:  # saved unchanged: no event
                        app.push_screen(app.flow.settings_screen("settings"))
                        await settle(app, pilot)
                        app.screen._save()
                        await settle(app, pilot)
                    self.assertNotIn(event, [e["event"] for e in events])

    async def test_a_failed_save_is_said_and_the_review_still_opens(self):
        from unittest import mock

        from wowtools.core.config import Config
        tool = "ace3-profile-manager"
        section, event = RISK_EVENTS[tool]
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            await self.pick_all(app, pilot, tool)
            app.screen.query_one(f"#{DONT_SHOW}", Checkbox).value = True
            with capture_events() as events, mock.patch.object(Config, "save", side_effect=OSError("read-only")):
                app.screen.choose(ACCEPT)
                await settle(app, pilot)
            self.assertIsInstance(app.screen, ProfileReviewScreen)
            names = [e["event"] for e in events]
            self.assertIn("error", names)
            self.assertNotIn(event, names)
            self.assertNotIn("config.changed", names)  # the change was undone, not left in memory
            self.assertTrue(any("Could not save" in str(n.message) for n in app._notifications))
            self.assertFalse(app.flow.tool_cfg.get_bool(section, "skip_risk_warning", False))
            app.flow.tool_cfg.save()  # a later write of the same config (a flavor pick, a blacklist edit)
        self.assertFalse(self.tool_cfg(tool).get_bool(section, "skip_risk_warning", False))

    async def test_enter_on_the_box_waits_for_the_popup_guard(self):
        from unittest import mock

        from wowtools.ui import dialogs
        self.confirm_guard(CONFIRM_GUARD)
        now = [1000.0]
        patcher = mock.patch.object(dialogs, "monotonic", lambda: now[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        tool = "sv-browser"
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            await self.pick_all(app, pilot, tool)
            popup = app.screen
            self.assertIsInstance(popup, DisclaimerScreen)
            await pilot.press("tab")
            self.assertEqual(popup.focused.id, DONT_SHOW)
            await pilot.press("enter")  # at once: ignored, as on the buttons
            await pilot.pause()
            self.assertIs(app.screen, popup)
            now[0] += CONFIRM_GUARD
            await pilot.press("enter")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, SvReviewScreen)

    async def test_tools_without_the_warning_have_no_box_in_their_settings(self):
        for tool in ("screenshot-organizer", "interface-backup"):
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    await pilot.pause()
                    app.open_tool(tool)
                    await settle(app, pilot)
                    app.push_screen(app.flow.settings_screen("settings"))
                    await settle(app, pilot)
                    self.assertFalse(app.screen.query(f"#{SHOW_RISK_WARNING_ID}"))
