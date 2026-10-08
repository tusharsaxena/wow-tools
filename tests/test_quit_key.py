"""L7 (STD-8.11): `q` quits from any screen. One app-level binding (`Ka0sApp`), not one per screen: the tool menu,
the changelog, the help, the settings, every tool's flavor and account pickers, its USE AT YOUR OWN RISK popup,
review, warnings, Ace3 blacklist, run confirm, result and Interface Backup's restore screen. A text box keeps the
letter (the filter, a settings field); while a run writes (`app.busy`) it is refused with the notice reviews gave;
with work staged on a review (Ace3, SV Browser) it asks first, from the review or from any screen over it, and q
while that question (or the review's own on leaving) is open asks nothing more. QuitBindingsTest reads every
screen's and widget's BINDINGS: a `q` there may only quit.

`app.exit` is replaced by a recorder, so one app walks every screen of a tool; the real exit path is the same call
(suite.run logs session.end and releases the lock once the app has returned)."""
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

ACCOUNT_TOOLS = ("wtf-cleaner", "ace3-profile-manager")  # the tools with an account picker
# The action that leads to a result screen without a running-WoW popup in between, and what it needs first.
RUN_ACTION = {"wtf-cleaner": "dry_run", "screenshot-organizer": "dry_run", "interface-backup": "back_up",
              "ace3-profile-manager": "dry_run", "sv-browser": "dry_run"}
PREPARE = {"ace3-profile-manager": lambda review: (review.staging.everyone_to_default(list(review.staging.states)),
                                                   review.refresh_view()),
           "sv-browser": stage_sv_edit}
DISCARD_TITLES = ("Leave and discard the pending changes?", "Leave and discard the staged edits?")


class QuitKeyTest(TuiTestCase):
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

    async def assert_quits(self, app, pilot, kind: type):
        """`q` on the shown screen (an instance of `kind`) quits: exit is called once, nothing else opens."""
        self.assertIsInstance(app.screen, kind)
        before = len(app.exits)
        screen = app.screen
        await pilot.press("q")
        await settle(app, pilot)
        self.assertEqual(len(app.exits), before + 1, kind.__name__)
        self.assertIs(app.screen, screen)

    async def open_flavors(self, app, pilot, tool):
        await pilot.pause()
        app.open_tool(tool)
        await settle(app, pilot)
        if not isinstance(app.screen, FlavorScreen):
            app.screen._save()  # first open: the tool's settings, saved as they are
            await settle(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        return app.screen

    async def test_q_quits_from_the_menu_changelog_help_and_settings(self):
        for size in (BASE, LARGE):
            with self.subTest(size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    await settle(app, pilot)
                    await self.assert_quits(app, pilot, ToolMenuScreen)
                    await pilot.press("c")
                    await settle(app, pilot)
                    await self.assert_quits(app, pilot, ChangelogScreen)
                    await pilot.press("h")
                    await settle(app, pilot)
                    await self.assert_quits(app, pilot, HelpScreen)
                    await pilot.press("escape", "escape")
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ToolMenuScreen)
                    await pilot.press("s")
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, SetupScreen)
                    field = app.screen.query_one("#wow_path", Input)
                    self.assertIs(app.screen.focused, field)
                    value = field.value
                    await pilot.press("end", "q")  # a text box types it
                    await settle(app, pilot)
                    self.assertEqual(field.value, value + "q")
                    self.assertEqual(app.exits, ["ToolMenuScreen", "ChangelogScreen", "HelpScreen"])
                    app.screen.query_one("#save").focus()
                    await pilot.pause()
                    await self.assert_quits(app, pilot, SetupScreen)

    async def test_q_quits_from_every_screen_of_every_tool(self):
        await self.walk_every_tool(BASE)

    async def test_q_quits_from_every_screen_of_every_tool_large(self):
        await self.walk_every_tool(LARGE)

    async def walk_every_tool(self, size):
        """The flavor and account pickers, the risk popup, the review (its filter box types q), the help, the
        tool's settings, the warnings, the Ace3 blacklist, the run's confirm and the result."""
        for name in TOOLS:
            with self.subTest(tool=name, size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    picker = await self.open_flavors(app, pilot, name)
                    await self.assert_quits(app, pilot, FlavorScreen)
                    if name in ACCOUNT_TOOLS:
                        picker.dismiss(next(f for f in picker.flavors if f.folder == "_retail_"))
                        await settle(app, pilot)
                        await self.assert_quits(app, pilot, AccountScreen)
                        await pilot.press("escape")  # back to the flavor picker
                        await settle(app, pilot)
                        picker = app.screen
                        self.assertIsInstance(picker, FlavorScreen)
                    picker.dismiss(ALL_FLAVORS)
                    await settle(app, pilot)
                    if isinstance(app.screen, DisclaimerScreen):
                        await self.assert_quits(app, pilot, DisclaimerScreen)
                        await accept_disclaimer(app, pilot)
                    review = app.screen
                    await self.assert_quits(app, pilot, type(review))
                    await pilot.press("slash", "q")  # the filter box types it
                    await settle(app, pilot)
                    self.assertIsInstance(app.focused, Input)
                    self.assertEqual(app.focused.value, "q")
                    self.assertIs(app.screen, review)
                    await pilot.press("escape")  # out of the filter box (cleared)
                    await settle(app, pilot)
                    await pilot.press("h")
                    await settle(app, pilot)
                    await self.assert_quits(app, pilot, HelpScreen)
                    await pilot.press("escape")
                    await settle(app, pilot)
                    app.push_screen(app.flow.settings_screen("settings"))
                    await settle(app, pilot)
                    app.screen.query_one("#save").focus()  # the first field has focus: q would type there
                    await pilot.pause()
                    await self.assert_quits(app, pilot, ToolSettingsScreen)
                    app.screen.dismiss(False)
                    await settle(app, pilot)
                    app.push_screen(WarningsScreen("Scan warnings", [WarningItem("Interface", "denied")]))
                    await settle(app, pilot)
                    await self.assert_quits(app, pilot, WarningsScreen)
                    app.pop_screen()
                    await settle(app, pilot)
                    if name == "ace3-profile-manager":
                        review.action_edit_blacklist()
                        await settle(app, pilot)
                        await self.assert_quits(app, pilot, type(app.screen))
                        self.assertIsNot(app.screen, review)
                        app.screen.dismiss(None)
                        await settle(app, pilot)
                    self.assertIs(app.screen, review)
                    staged = name in PREPARE
                    PREPARE.get(name, lambda r: None)(review)
                    getattr(review, f"action_{RUN_ACTION[name]}")()
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmScreen)
                    if staged:  # work is staged: q asks first, even from a popup over the review
                        confirm, before = app.screen, len(app.exits)
                        await pilot.press("q")
                        await settle(app, pilot)
                        self.assertIsInstance(app.screen, ConfirmScreen)
                        self.assertIn(app.screen.title_text, DISCARD_TITLES)
                        app.screen.dismiss(True)
                        await settle(app, pilot)
                        self.assertIs(app.screen, confirm)
                        self.assertEqual(len(app.exits), before + 1)
                    else:
                        await self.assert_quits(app, pilot, ConfirmScreen)
                    app.screen.dismiss(True)
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ResultBase)
                    if name == "interface-backup":  # Restore (e) on the result, then e on the backup just made
                        await pilot.press("e")
                        await settle(app, pilot)
                        await pilot.press("e")
                        await settle(app, pilot)
                        await self.assert_quits(app, pilot, RestoreScreen)
                    else:
                        before = len(app.exits)
                        await pilot.press("q")  # the result's own Quit (q): it dismisses, then the app exits
                        await settle(app, pilot)
                        if staged:  # a dry run keeps the staged work: leaving asks first, as before L7
                            self.assertIn(app.screen.title_text, DISCARD_TITLES)
                            app.screen.dismiss(True)
                            await settle(app, pilot)
                        self.assertEqual(len(app.exits), before + 1)

    async def test_q_is_refused_while_a_run_writes(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            picker = await self.open_flavors(app, pilot, "screenshot-organizer")
            picker.dismiss(ALL_FLAVORS)
            await settle(app, pilot)
            review = app.screen
            app.busy = True
            with capture_events() as records:
                await pilot.press("q")
                await settle(app, pilot)
            self.assertEqual(app.exits, [])
            self.assertIs(app.screen, review)
            self.assertIn("ui.quit_refused", [r["event"] for r in records])
            self.assertIn("A run is in progress. Wait for it to finish before quitting.",
                          [str(n.message) for n in app._notifications])
            app.busy = False
            await self.assert_quits(app, pilot, type(review))

    async def test_staged_work_asks_before_quitting_and_no_keeps_it(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            picker = await self.open_flavors(app, pilot, "sv-browser")
            picker.dismiss(ALL_FLAVORS)
            await settle(app, pilot)
            await accept_disclaimer(app, pilot)
            review = app.screen
            stage_sv_edit(review)
            await settle(app, pilot)
            await pilot.press("h")  # from a screen over the review too
            await settle(app, pilot)
            self.assertIsInstance(app.screen, HelpScreen)
            await pilot.press("q")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("q")  # a second q does not stack a second question
            await settle(app, pilot)
            self.assertEqual(sum(isinstance(s, ConfirmScreen) for s in app.screen_stack), 1)
            app.screen.dismiss(False)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, HelpScreen)
            self.assertEqual(app.exits, [])
            self.assertTrue(review.pending)

    async def open_staged_review(self, app, pilot, name):
        picker = await self.open_flavors(app, pilot, name)
        picker.dismiss(ALL_FLAVORS)
        await settle(app, pilot)
        await accept_disclaimer(app, pilot)
        review = app.screen
        PREPARE[name](review)
        await settle(app, pilot)
        self.assertIsNotNone(review.discard_question())
        return review

    async def test_q_over_the_leave_question_asks_nothing_more(self):
        """f, t, Esc and a result's Quit after a dry run open the review's own "Leave and discard ...?" question
        (action_leave); q while it is open neither quits nor stacks a second copy of it. No keeps the work."""
        for name in PREPARE:
            for keys in (("f",), ("t",), ("escape",), ("y", "result")):
                with self.subTest(tool=name, keys=keys):
                    app = self.make_app()
                    async with app.run_test(size=BASE) as pilot:
                        review = await self.open_staged_review(app, pilot, name)
                        if keys[-1] == "result":  # a dry run, then the result's Quit (q)
                            await pilot.press("y")
                            await settle(app, pilot)
                            app.screen.dismiss(True)
                            await settle(app, pilot)
                            self.assertIsInstance(app.screen, ResultBase)
                        await pilot.press(keys[0] if keys[-1] != "result" else "q")
                        await settle(app, pilot)
                        self.assertIsInstance(app.screen, DiscardScreen)
                        self.assertIn(app.screen.title_text, DISCARD_TITLES)
                        await pilot.press("q")
                        await settle(app, pilot)
                        self.assertEqual(sum(isinstance(s, ConfirmScreen) for s in app.screen_stack), 1)
                        self.assertEqual(app.exits, [])
                        await pilot.press("n")
                        await settle(app, pilot)
                        self.assertIs(app.screen, review)
                        self.assertIsNotNone(review.discard_question())
                        await pilot.press("q")  # and q asks again once that question is answered
                        await settle(app, pilot)
                        self.assertIsInstance(app.screen, DiscardScreen)

    async def test_a_quit_question_closed_without_an_answer_leaves_q_working(self):
        """No flag to clear: a quit question removed by pop_screen (not dismissed) does not make q silent."""
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await self.open_staged_review(app, pilot, "sv-browser")
            await pilot.press("q")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, DiscardScreen)
            app.pop_screen()
            await settle(app, pilot)
            await pilot.press("q")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, DiscardScreen)
            app.screen.dismiss(True)
            await settle(app, pilot)
            self.assertEqual(len(app.exits), 1)

    async def test_q_quits_from_popups_over_popups_and_closed_lists(self):
        """A confirm over the warnings and over the help, the update offer, and the Ace3 and SV Browser popups
        whose focus is on a closed list (NavSelect), at both standard sizes."""
        for size in (BASE, LARGE):
            with self.subTest(size=size):
                app = self.make_app()
                async with app.run_test(size=size) as pilot:
                    await settle(app, pilot)
                    app.push_screen(WarningsScreen("Scan warnings", [WarningItem("Interface", "denied")]))
                    await settle(app, pilot)
                    app.push_screen(ConfirmScreen("Sure?", "Body"))
                    await settle(app, pilot)
                    await self.assert_quits(app, pilot, ConfirmScreen)
                    app.pop_screen()
                    app.pop_screen()
                    await pilot.press("h")
                    await settle(app, pilot)
                    app.push_screen(ConfirmScreen("Sure?", "Body"))
                    await settle(app, pilot)
                    await self.assert_quits(app, pilot, ConfirmScreen)
                    app.pop_screen()
                    app.pop_screen()
                    await settle(app, pilot)
                    app.push_screen(UpdateScreen(ReleaseInfo.from_version("9.9.9")))
                    await settle(app, pilot)
                    await self.assert_quits(app, pilot, UpdateScreen)
                    app.pop_screen()
                    for popup, select in ((TargetScreen("Move to", "Body", ["Default", "Other"]), "#target"),
                                          (EditValueScreen("ElvDB › x", "1"), "#value-type")):
                        app.push_screen(popup)
                        await settle(app, pilot)
                        popup.query_one(select, Select).focus()
                        await pilot.pause()
                        await self.assert_quits(app, pilot, type(popup))
                        self.assertFalse(popup.query_one(select, Select).expanded)
                        app.pop_screen()
                        await settle(app, pilot)
                    self.assertIsInstance(app.screen, ToolMenuScreen)

    async def test_q_quits_from_the_lock_warning(self):
        app = self.make_app(conflict=LockInfo(12345, "other-pc", "2026-10-03T10:00:00", "windows", "abc"))
        async with app.run_test(size=BASE) as pilot:
            await settle(app, pilot)
            self.assertIsInstance(app.screen, LockScreen)
            await pilot.press("q")
            await settle(app, pilot)
            self.assertEqual(len(app.exits), 1)


QUIT_ACTIONS = ("app.quit", "choose('quit')", "choose('lock-quit')")  # STD-8.11: what a `q` binding may do


class QuitBindingsTest(unittest.TestCase):
    def test_no_screen_or_widget_binds_q_to_anything_but_quitting(self):
        """Every screen and widget class in wowtools/, walked or not by the tests above: a `q` in its own
        BINDINGS quits (the menu's and the reviews' app.quit, a result's Quit, the lock warning's Quit)."""
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
                    if "q" in [k.strip() for k in key.split(",")]:
                        self.assertIn(action, QUIT_ACTIONS, f"{module_name}.{cls.__name__} binds q to {action}")
        self.assertGreater(seen, 50)
