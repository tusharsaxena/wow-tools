"""L11 (STD-8.11): `t` goes back to the tool menu from any screen and popup, like `q` quits (L7). One app-level key
method (`WowToolsApp.key_t`), not one binding per screen: the flavor and account pickers, the USE AT YOUR OWN RISK
popup, every review, its help, settings and warnings, the Ace3 blacklist, a run's confirm, the result and Interface
Backup's restore screen; with no tool open, the changelog, the help, the settings, the update offer and popups over
popups. The screens that list `t` in their footer (pickers, reviews, results) keep their own binding, which leaves
the same way. A text box types the letter; while a run writes (`app.busy`) it is refused with a notice; with work
staged on a review it asks first, from the review or any screen over it; on the tool menu and the lock warning it
does nothing. ToolMenuBindingsTest reads every screen's and widget's BINDINGS: a `t` there may only go to the menu.

`app.exit` is replaced by a recorder (nothing may quit here)."""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
import tempfile
import unittest
from pathlib import Path

from textual.binding import Binding
from textual.dom import DOMNode
from textual.widgets import Input, Select

import wowtools
from tests.fixtures import (BASE, LARGE, TuiTestCase, accept_disclaimer, build_ace_tree, build_interface_tree,
                            build_screenshot_tree, build_wow_tree, make_config, settle, stage_sv_edit)
from wowtools.core.events import capture_events
from wowtools.core.lock import InstanceLock, LockInfo
from wowtools.core.updater import ReleaseInfo
from wowtools.tools import TOOLS
from wowtools.tools.ace3_profile_manager.popups import TargetScreen
from wowtools.tools.interface_backup.restore_screen import RestoreScreen
from wowtools.tools.sv_browser.popups import EditValueScreen
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.base import UpdateScreen
from wowtools.ui.changelog_screen import ChangelogScreen
from wowtools.ui.dialogs import ConfirmScreen, DiscardScreen
from wowtools.ui.disclaimer import DisclaimerScreen
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.help_screen import HelpScreen
from wowtools.ui.result_screen import ResultBase
from wowtools.ui.settings_form import ToolSettingsScreen
from wowtools.ui.setup_screen import SetupScreen
from wowtools.ui.suite_app import LockScreen, ToolMenuScreen, WowToolsApp
from wowtools.ui.warnings_view import WarningItem, WarningsScreen

ACCOUNT_TOOLS = ("wtf-cleaner", "ace3-profile-manager")
RUN_ACTION = {"wtf-cleaner": "dry_run", "screenshot-organizer": "dry_run", "interface-backup": "back_up",
              "ace3-profile-manager": "dry_run", "sv-browser": "dry_run"}
PREPARE = {"ace3-profile-manager": lambda review: (review.staging.everyone_to_default(list(review.staging.states)),
                                                   review.refresh_view()),
           "sv-browser": stage_sv_edit}
DISCARD_TITLES = ("Leave and discard the pending changes?", "Leave and discard the staged edits?")
BUSY_NOTICE = "A run is in progress. Wait for it to finish before going back to the tool menu."


class ToolMenuKeyTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        tmp = Path(t.name)
        wow = build_wow_tree(tmp / "World of Warcraft")
        self.root = build_ace_tree(build_interface_tree(build_screenshot_tree(wow)))
        self.config_dir = tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self, conflict=None):
        options = {"wtf-cleaner": {"wow_check": list, "locker_check": list},
                   "interface-backup": {"wow_check": list}, "ace3-profile-manager": {"wow_check": list},
                   "sv-browser": {"wow_check": list}}
        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                          tool_options=options, conflict=conflict,
                          lock=InstanceLock(self.config_dir.parent / "wow-tools.lock") if conflict else None)
        app.exits = []
        app.exit = lambda *args, **kwargs: app.exits.append(type(app.screen).__name__)
        return app

    def assert_on_menu(self, app):
        self.assertIs(app.screen, app.menu)
        self.assertIsNone(app.flow)
        self.assertEqual(app.sub_title, WowToolsApp.SUB_TITLE)
        self.assertFalse(any(isinstance(s, (ResultBase, FlavorScreen, HelpScreen)) for s in app.screen_stack))
        self.assertEqual(app.exits, [])

    async def assert_to_menu(self, app, pilot, kind: type):
        """`t` on the shown screen (an instance of `kind`) goes back to the tool menu, the tool closed."""
        self.assertIsInstance(app.screen, kind)
        await pilot.press("t")
        await settle(app, pilot)
        self.assert_on_menu(app)

    async def open_flavors(self, app, pilot, tool):
        await pilot.pause()
        app.open_tool(tool)
        await settle(app, pilot)
        if not isinstance(app.screen, FlavorScreen):
            app.screen._save()  # first open: the tool's settings, saved as they are
            await settle(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        return app.screen

    async def open_review(self, app, pilot, tool):
        picker = await self.open_flavors(app, pilot, tool)
        picker.dismiss(ALL_FLAVORS)
        await settle(app, pilot)
        await accept_disclaimer(app, pilot)
        self.assertNotIsInstance(app.screen, (FlavorScreen, DisclaimerScreen))
        return app.screen

    async def test_t_goes_back_from_the_changelog_help_settings_and_does_nothing_on_the_menu(self):
        for size in (BASE, LARGE):
            with self.subTest(size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    await settle(app, pilot)
                    stack = list(app.screen_stack)
                    await pilot.press("t")  # on the menu: nothing
                    await settle(app, pilot)
                    self.assertEqual(app.screen_stack, stack)
                    self.assert_on_menu(app)
                    await pilot.press("c")
                    await settle(app, pilot)
                    await self.assert_to_menu(app, pilot, ChangelogScreen)
                    await pilot.press("h")
                    await settle(app, pilot)
                    await self.assert_to_menu(app, pilot, HelpScreen)
                    await pilot.press("s")
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, SetupScreen)
                    field = app.screen.query_one("#wow_path", Input)
                    self.assertIs(app.screen.focused, field)
                    value = field.value
                    await pilot.press("end", "t")  # a text box types it
                    await settle(app, pilot)
                    self.assertEqual(field.value, value + "t")
                    self.assertIsInstance(app.screen, SetupScreen)
                    app.screen.query_one("#save").focus()
                    await pilot.pause()
                    await self.assert_to_menu(app, pilot, SetupScreen)
                    self.assertEqual(app.screen_stack, stack)

    async def test_t_goes_back_from_every_screen_of_every_tool(self):
        await self.walk_every_tool(BASE)

    async def test_t_goes_back_from_every_screen_of_every_tool_large(self):
        await self.walk_every_tool(LARGE)

    async def walk_every_tool(self, size):
        """The flavor and account pickers, the risk popup, the review (its filter box types t), the help, the
        tool's settings, the warnings, the Ace3 blacklist, the run's confirm, the result and the restore screen.
        Each `t` closes the tool, so the walk opens it again for the next screen."""
        for name in TOOLS:
            with self.subTest(tool=name, size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    await self.open_flavors(app, pilot, name)
                    await self.assert_to_menu(app, pilot, FlavorScreen)
                    if name in ACCOUNT_TOOLS:
                        picker = await self.open_flavors(app, pilot, name)
                        picker.dismiss(next(f for f in picker.flavors if f.folder == "_retail_"))
                        await settle(app, pilot)
                        await self.assert_to_menu(app, pilot, AccountScreen)
                    picker = await self.open_flavors(app, pilot, name)
                    picker.dismiss(ALL_FLAVORS)
                    await settle(app, pilot)
                    if isinstance(app.screen, DisclaimerScreen):  # t is not an answer: asked again next time
                        await self.assert_to_menu(app, pilot, DisclaimerScreen)
                        picker = await self.open_flavors(app, pilot, name)
                        picker.dismiss(ALL_FLAVORS)
                        await settle(app, pilot)
                        self.assertIsInstance(app.screen, DisclaimerScreen)
                        await accept_disclaimer(app, pilot)
                    review = app.screen
                    await pilot.press("slash", "t")  # the filter box types it
                    await settle(app, pilot)
                    self.assertIsInstance(app.focused, Input)
                    self.assertEqual(app.focused.value, "t")
                    self.assertIs(app.screen, review)
                    await pilot.press("escape")  # out of the filter box (cleared)
                    await settle(app, pilot)
                    await self.assert_to_menu(app, pilot, type(review))

                    await self.open_review(app, pilot, name)
                    await pilot.press("h")
                    await settle(app, pilot)
                    await self.assert_to_menu(app, pilot, HelpScreen)

                    await self.open_review(app, pilot, name)
                    app.push_screen(app.flow.settings_screen("settings"))
                    await settle(app, pilot)
                    app.screen.query_one("#save").focus()  # the first field has focus: t would type there
                    await pilot.pause()
                    await self.assert_to_menu(app, pilot, ToolSettingsScreen)

                    await self.open_review(app, pilot, name)
                    app.push_screen(WarningsScreen("Scan warnings", [WarningItem("Interface", "denied")]))
                    await settle(app, pilot)
                    app.push_screen(ConfirmScreen("Sure?", "Body"))  # a popup over a popup
                    await settle(app, pilot)
                    await self.assert_to_menu(app, pilot, ConfirmScreen)

                    if name == "ace3-profile-manager":
                        review = await self.open_review(app, pilot, name)
                        review.action_edit_blacklist()
                        await settle(app, pilot)
                        self.assertIsNot(app.screen, review)
                        await self.assert_to_menu(app, pilot, type(app.screen))

                    review = await self.open_review(app, pilot, name)
                    staged = name in PREPARE
                    PREPARE.get(name, lambda r: None)(review)
                    getattr(review, f"action_{RUN_ACTION[name]}")()
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmScreen)
                    if staged:  # work is staged: t asks first, even from a popup over the review
                        await pilot.press("t")
                        await settle(app, pilot)
                        self.assertIsInstance(app.screen, DiscardScreen)
                        self.assertIn(app.screen.title_text, DISCARD_TITLES)
                        app.screen.dismiss(True)
                        await settle(app, pilot)
                        self.assert_on_menu(app)
                    else:
                        await self.assert_to_menu(app, pilot, ConfirmScreen)

                    review = await self.open_review(app, pilot, name)
                    PREPARE.get(name, lambda r: None)(review)
                    getattr(review, f"action_{RUN_ACTION[name]}")()
                    await settle(app, pilot)
                    app.screen.dismiss(True)
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ResultBase)
                    if name == "interface-backup":  # Restore (e) on the result, then e on the backup just made
                        await pilot.press("e")
                        await settle(app, pilot)
                        await pilot.press("e")
                        await settle(app, pilot)
                        await self.assert_to_menu(app, pilot, RestoreScreen)
                    else:
                        await pilot.press("t")  # the result's own Tools (t)
                        await settle(app, pilot)
                        if staged:  # a dry run keeps the staged work: leaving asks first
                            self.assertIn(app.screen.title_text, DISCARD_TITLES)
                            app.screen.dismiss(True)
                            await settle(app, pilot)
                        self.assert_on_menu(app)
                    self.assertEqual(len(app.screen_stack), 2)  # Textual's default screen and the menu

    async def test_t_is_refused_while_a_run_writes(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "screenshot-organizer")
            app.busy = True
            for over in (False, True):  # the review's own t, then the app's under a popup
                if over:
                    app.push_screen(WarningsScreen("Scan warnings", [WarningItem("Interface", "denied")]))
                    await settle(app, pilot)
                top = app.screen
                with capture_events() as records:
                    await pilot.press("t")
                    await settle(app, pilot)
                self.assertIs(app.screen, top)
                self.assertIsNotNone(app.flow)
                self.assertIn("ui.tool_menu_refused", [r["event"] for r in records])
                self.assertIn(BUSY_NOTICE, [str(n.message) for n in app._notifications])
            app.busy = False
            await self.assert_to_menu(app, pilot, WarningsScreen)
            self.assertNotIn(review, app.screen_stack)

    async def test_staged_work_asks_first_and_no_keeps_it(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot, "sv-browser")
            stage_sv_edit(review)
            await settle(app, pilot)
            await pilot.press("h")  # from a screen over the review too
            await settle(app, pilot)
            self.assertIsInstance(app.screen, HelpScreen)
            await pilot.press("t")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, DiscardScreen)
            await pilot.press("t")  # a second t does not stack a second question
            await settle(app, pilot)
            self.assertEqual(sum(isinstance(s, ConfirmScreen) for s in app.screen_stack), 1)
            await pilot.press("q")  # nor does q
            await settle(app, pilot)
            self.assertEqual(sum(isinstance(s, ConfirmScreen) for s in app.screen_stack), 1)
            app.screen.dismiss(False)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, HelpScreen)
            self.assertIsNotNone(app.flow)
            self.assertTrue(review.pending)
            with capture_events() as records:
                await pilot.press("t")
                await settle(app, pilot)
                app.screen.dismiss(True)
                await settle(app, pilot)
            self.assert_on_menu(app)
            self.assertIn(("ui.selection", "tool_menu", "HelpScreen"),
                          [(r["event"], r["data"].get("control"), r["data"].get("value")) for r in records])

    async def test_a_tool_opens_again_after_t(self):
        """The flow is dropped cleanly: the same tool, then another, opens on its flavor picker."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_review(app, pilot, "wtf-cleaner")
            await pilot.press("h")
            await settle(app, pilot)
            await self.assert_to_menu(app, pilot, HelpScreen)
            await self.open_review(app, pilot, "wtf-cleaner")
            await pilot.press("t")
            await settle(app, pilot)
            self.assert_on_menu(app)
            await self.open_flavors(app, pilot, "screenshot-organizer")
            self.assertEqual(app.flow_name, "screenshot-organizer")

    async def test_t_goes_back_from_popups_and_closed_lists(self):
        """The update offer, and the Ace3 and SV Browser popups whose focus is on a closed list (NavSelect)."""
        for size in (BASE, LARGE):
            with self.subTest(size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    await settle(app, pilot)
                    app.push_screen(UpdateScreen(ReleaseInfo.from_version("9.9.9")))
                    await settle(app, pilot)
                    await self.assert_to_menu(app, pilot, UpdateScreen)
                    for popup, select in ((TargetScreen("Move to", "Body", ["Default", "Other"]), "#target"),
                                          (EditValueScreen("ElvDB › x", "1"), "#value-type")):
                        app.push_screen(popup)
                        await settle(app, pilot)
                        popup.query_one(select, Select).focus()
                        await pilot.pause()
                        await self.assert_to_menu(app, pilot, type(popup))
                    self.assertIsInstance(app.screen, ToolMenuScreen)

    async def test_t_does_nothing_on_the_lock_warning(self):
        app = self.make_app(conflict=LockInfo(12345, "other-pc", "2026-10-03T10:00:00", "windows", "abc"))
        async with app.run_test(size=BASE) as pilot:
            await settle(app, pilot)
            self.assertIsInstance(app.screen, LockScreen)
            await pilot.press("t")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, LockScreen)
            self.assertEqual(app.exits, [])


TOOL_MENU_ACTIONS = ("leave('tools')", "tool_menu", "choose('tools')")  # STD-8.11: what a `t` binding may do


class ToolMenuBindingsTest(unittest.TestCase):
    def test_no_screen_or_widget_binds_t_to_anything_but_the_tool_menu(self):
        for info in pkgutil.walk_packages(wowtools.__path__, "wowtools."):
            importlib.import_module(info.name)
        seen = 0
        for module_name, module in list(sys.modules.items()):
            if not module_name.startswith("wowtools."):
                continue
            for cls in vars(module).values():
                if not (inspect.isclass(cls) and issubclass(cls, DOMNode) and cls.__module__ == module_name):
                    continue
                seen += 1
                for binding in cls.__dict__.get("BINDINGS", []):
                    key, action = ((binding.key, binding.action) if isinstance(binding, Binding)
                                   else (binding[0], binding[1]))
                    if "t" in [k.strip() for k in key.split(",")]:
                        self.assertIn(action, TOOL_MENU_ACTIONS,
                                      f"{module_name}.{cls.__name__} binds t to {action}")
        self.assertGreater(seen, 50)
