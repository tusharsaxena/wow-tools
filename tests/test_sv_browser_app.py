"""Saved Variables Browser flow (spec D1, D3): first-run settings, flavor picker with All flavors, the review (a
placeholder until the M3 screens) and back."""
from __future__ import annotations

import tempfile
from pathlib import Path

from tests.fixtures import BASE, TuiTestCase, build_sv_tree, make_config, settle
from wowtools.core.config import Config
from wowtools.tools.sv_browser.app import SvBrowserSettingsScreen
from wowtools.tools.sv_browser.review_screen import SvReviewScreen
from wowtools.tools.sv_browser.settings import load_settings
from wowtools.ui.flavor_screen import ALL_FLAVORS, FlavorScreen
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp

TOOL = "sv-browser"


class SvBrowserFlowTest(TuiTestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)
        self.root = build_sv_tree(self.tmp / "World of Warcraft")
        self.config_dir = self.tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)

    def make_app(self):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list)

    def tool_cfg(self) -> Config:
        return Config(self.config_dir / "sv-browser.cfg").load()

    async def open_picker(self, app, pilot):
        await pilot.pause()
        app.open_tool(TOOL)
        await settle(app, pilot)
        if isinstance(app.screen, SvBrowserSettingsScreen):  # first open: the tool's settings
            app.screen._save()
            await settle(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        return app.screen

    async def test_first_open_asks_settings_then_all_flavors_reaches_the_review(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            app.open_tool(TOOL)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, SvBrowserSettingsScreen)
            app.screen._save()
            await settle(app, pilot)
            picker = app.screen
            self.assertIsInstance(picker, FlavorScreen)
            self.assertTrue(picker.include_all)
            self.assertEqual(sorted(f.folder for f in picker.flavors), ["_classic_era_", "_retail_"])
            picker.dismiss(ALL_FLAVORS)
            await settle(app, pilot)
            review = app.screen
            self.assertIsInstance(review, SvReviewScreen)
            self.assertEqual(len(review.flavors), 2)
            self.assertTrue(review.sub_title.startswith("Saved Variables Browser · All flavors"), review.sub_title)
            self.assertEqual(load_settings(self.tool_cfg()).last_flavor_choice, "")
            await pilot.press("escape")  # Esc: back to the flavor picker
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
            self.assertEqual(app.screen.last, "")  # All flavors highlighted again

    async def test_one_flavor_has_no_account_picker_and_t_goes_to_the_menu(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            picker = await self.open_picker(app, pilot)
            retail = next(f for f in picker.flavors if f.folder == "_retail_")
            picker.dismiss(retail)  # two accounts, still no account picker (spec D3)
            await settle(app, pilot)
            self.assertIsInstance(app.screen, SvReviewScreen)
            self.assertEqual(app.screen.flavors, [retail])
            self.assertEqual(load_settings(self.tool_cfg()).last_flavor_choice, "_retail_")
            await pilot.press("t")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ToolMenuScreen)
            self.assertIsNone(app.flow)

    async def test_back_button_goes_to_the_flavor_picker_and_esc_there_to_the_menu(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            picker = await self.open_picker(app, pilot)
            picker.dismiss(ALL_FLAVORS)
            await settle(app, pilot)
            await pilot.click("#btn-back")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ToolMenuScreen)
