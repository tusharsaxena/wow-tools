import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Input, OptionList

from tests.fixtures import TuiTestCase, build_wow_tree
from wowtools import __version__
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.updater import ReleaseInfo
from wowtools.ui.base import Ka0sApp, UpdateScreen
from wowtools.ui.branding import BrandBar
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.setup_screen import SetupScreen
from wowtools.tools import TOOLS
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp
from wowtools.ui.widgets import ButtonRow, NavHint


class Host(Ka0sApp):
    """Pushes one screen and records what it dismisses with."""

    def __init__(self, cfg, screen):
        super().__init__(cfg, check_updates=False)
        self._screen = screen
        self.results = []

    def after_mount(self):
        self.push_screen(self._screen, self.results.append)


class UiTestCase(TuiTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.cfg = Config(self.tmp / "wow-tools.cfg")


class SuiteAppBaseTest(UiTestCase):
    def make_app(self):
        return WowToolsApp(self.cfg, config_dir=self.tmp, check_updates=False, detect=lambda: [])

    async def test_theme_branding_and_menu_first(self):
        app = self.make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            self.assertEqual(app.theme, "ka0s")
            self.assertEqual(app.title, "Ka0s · WoW Tools")
            self.assertIsInstance(app.screen, ToolMenuScreen)
            self.assertIn(f"Ka0s WoW Tools v{__version__}", app.screen.query_one(BrandBar).text)
            options = app.screen.query_one("#tools", OptionList)
            self.assertEqual([options.get_option_at_index(i).id for i in range(options.option_count)],
                             list(TOOLS))

    async def test_update_badge_and_prompt(self):
        app = self.make_app()
        applied = []
        with patch("wowtools.ui.base.apply_update", side_effect=lambda rel: applied.append(rel) or "Updated"):
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._update_found(ReleaseInfo.from_version("9.9.9"))
                await pilot.pause()
                self.assertIn("v9.9.9 available", app.screen.query_one(BrandBar).text)
                await pilot.press("u")
                await pilot.pause()
                self.assertIsInstance(app.screen, UpdateScreen)
                await pilot.click("#update-yes")
                await pilot.pause()
        self.assertEqual([r.version for r in applied], ["9.9.9"])

    async def test_update_blocked_while_busy(self):
        app = self.make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app._update_found(ReleaseInfo.from_version("9.9.9"))
            app.busy = True
            await pilot.press("u")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, UpdateScreen)


class SetupScreenTest(UiTestCase):
    async def test_rejects_invalid_folder_then_saves(self):
        screen = SetupScreen(self.cfg, first_run=True, detect=lambda: [])
        app = Host(self.cfg, screen)
        with capture_events() as records:
            async with app.run_test(size=(120, 50)) as pilot:
                screen.query_one("#wow_path", Input).value = str(self.tmp / "nothing-here")
                await pilot.click("#save")
                await pilot.pause()
                self.assertIn("No WoW flavor folders", screen.error_text)
                self.assertEqual(app.results, [])
                screen.query_one("#wow_path", Input).value = str(self.root)
                await pilot.pause(0.3)  # Textual ignores a second press during the button's active effect
                await pilot.click("#save")
                await pilot.pause()
        self.assertEqual(app.results, [True])
        saved = Config(self.cfg.path).load()
        self.assertEqual(saved.wow_path, self.root)
        changed = [r for r in records if r["event"] == "config.changed"]
        self.assertEqual(changed[0]["data"]["source"], "wizard")

    async def test_prefills_detected_install(self):
        screen = SetupScreen(self.cfg, first_run=True, detect=lambda: [self.root])
        app = Host(self.cfg, screen)
        async with app.run_test(size=(120, 50)):
            self.assertEqual(screen.query_one("#wow_path", Input).value, str(self.root))
            self.assertEqual(len(screen.query("#backup_dir")), 0)


class UpdateScreenKeyboardTest(UiTestCase):
    async def test_update_screen_keyboard(self):
        screen = UpdateScreen(ReleaseInfo.from_version("9.9.9"))
        app = Host(self.cfg, screen)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            self.assertEqual(screen.focused.id, "update-yes")
            self.assertTrue(screen.query(ButtonRow))
            self.assertTrue(screen.query(NavHint))
            await pilot.press("right")
            self.assertEqual(screen.focused.id, "update-no")
            await pilot.press("enter")
            await pilot.pause()
        self.assertEqual(app.results, [False])


class FlavorScreenTest(UiTestCase):
    async def test_escape_goes_back_and_hint_shown(self):
        app = Host(self.cfg, FlavorScreen(self.cfg, WowInstall(self.root)))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen.focused, OptionList)
            self.assertTrue(app.screen.query(NavHint))
            await pilot.press("escape")
            await pilot.pause()
        self.assertEqual(app.results, [None])

    async def test_last_flavor_preselected_and_logged(self):
        self.cfg.set("general", "last_flavor", "_classic_era_")
        app = Host(self.cfg, FlavorScreen(self.cfg, WowInstall(self.root)))
        with capture_events() as records:
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
        self.assertEqual(app.results[0].folder, "_classic_era_")
        selections = [r["data"] for r in records if r["event"] == "ui.selection"]
        self.assertIn({"screen": "flavor", "control": "flavor", "value": "_classic_era_"}, selections)


class AccountScreenTest(UiTestCase):
    def retail(self):
        return WowInstall(self.root).flavor("retail")

    async def test_lists_all_then_accounts_and_preselects_last(self):
        app = Host(self.cfg, AccountScreen(self.cfg, self.retail(), last="acct2"))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            options = app.screen.query_one(OptionList)
            self.assertIs(app.screen.focused, options)
            self.assertTrue(app.screen.query(NavHint))
            self.assertEqual([options.get_option_at_index(i).id for i in range(options.option_count)],
                             ["__all__", "ACCT1", "ACCT2"])
            await pilot.press("enter")
            await pilot.pause()
        self.assertEqual(app.results, ["ACCT2"])

    async def test_all_accounts_is_empty_string_and_escape_is_none(self):
        app = Host(self.cfg, AccountScreen(self.cfg, self.retail(), last=None))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
        self.assertEqual(app.results, [""])
        app = Host(self.cfg, AccountScreen(self.cfg, self.retail(), last=None))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
        self.assertEqual(app.results, [None])
