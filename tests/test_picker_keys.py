"""L5: `t` on the flavor and account pickers goes back to the tool menu, as it does on every review and result
screen. Esc keeps doing what it did: the flavor picker's goes back to the tool menu too, the account picker's to the
flavor picker. The footer lists both keys and the hint names t."""
from __future__ import annotations

import tempfile
from pathlib import Path

from textual.widgets._footer import FooterKey

from tests.fixtures import (BASE, TuiTestCase, build_ace_tree, build_interface_tree, build_screenshot_tree,
                            build_wow_tree, footer_keys, make_config, settle)
from wowtools.tools import TOOLS
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp
from wowtools.ui.widgets import NavHint

ACCOUNT_TOOLS = ("wtf-cleaner", "ace3-profile-manager")  # the tools with an account picker


class PickerKeysTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        tmp = Path(t.name)
        wow = build_wow_tree(tmp / "World of Warcraft")
        self.root = build_ace_tree(build_interface_tree(build_screenshot_tree(wow)))
        self.config_dir = tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self):
        options = {"wtf-cleaner": {"wow_check": list, "locker_check": list},
                   "interface-backup": {"wow_check": list}, "ace3-profile-manager": {"wow_check": list},
                   "sv-browser": {"wow_check": list}}
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

    async def open_accounts(self, app, pilot, tool):
        picker = await self.open_flavors(app, pilot, tool)
        retail = next(f for f in picker.flavors if f.folder == "_retail_")
        self.assertGreater(len(retail.accounts()), 1)
        picker.dismiss(retail)
        await settle(app, pilot)
        self.assertIsInstance(app.screen, AccountScreen)
        return app.screen

    async def assert_tool_menu(self, app, pilot):
        await settle(app, pilot)
        self.assertIsInstance(app.screen, ToolMenuScreen)
        self.assertIsNone(app.flow)

    async def test_t_on_the_flavor_picker_goes_back_to_the_tool_menu(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    await self.open_flavors(app, pilot, tool)
                    await pilot.press("t")
                    await self.assert_tool_menu(app, pilot)

    async def test_esc_on_the_flavor_picker_still_goes_back_to_the_tool_menu(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    await self.open_flavors(app, pilot, tool)
                    await pilot.press("escape")
                    await self.assert_tool_menu(app, pilot)

    async def test_t_on_the_account_picker_goes_back_to_the_tool_menu(self):
        for tool in ACCOUNT_TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    await self.open_accounts(app, pilot, tool)
                    await pilot.press("t")
                    await self.assert_tool_menu(app, pilot)

    async def test_esc_on_the_account_picker_still_goes_back_to_the_flavor_picker(self):
        for tool in ACCOUNT_TOOLS:
            with self.subTest(tool=tool):
                app = self.make_app()
                async with app.run_test(size=BASE) as pilot:
                    await self.open_accounts(app, pilot, tool)
                    await pilot.press("escape")
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, FlavorScreen)
                    self.assertIsNotNone(app.flow)

    async def test_footer_and_hint_name_t_on_both_pickers(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            picker = await self.open_flavors(app, pilot, "wtf-cleaner")
            keys = await footer_keys(picker, pilot, {"t", "escape"})
            self.assertLessEqual({"t", "escape"}, keys, keys)
            labels = {key.key: key.description for key in picker.query(FooterKey)}
            self.assertEqual(labels["t"], "Tools")
            # t and Esc both go to the tool menu here: the hint names them once, together
            self.assertEqual(picker.query_one(NavHint).hint, "↑↓ choose · Enter select · t/Esc tools")
            picker.dismiss(next(f for f in picker.flavors if f.folder == "_retail_"))
            await settle(app, pilot)
            accounts = app.screen
            self.assertIsInstance(accounts, AccountScreen)
            keys = await footer_keys(accounts, pilot, {"t", "escape"})
            self.assertLessEqual({"t", "escape"}, keys, keys)
            labels = {key.key: key.description for key in accounts.query(FooterKey)}
            self.assertEqual(labels["t"], "Tools")
            self.assertIn("t tools", accounts.query_one(NavHint).hint)
