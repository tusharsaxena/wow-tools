import asyncio
import contextlib
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.binding import Binding
from textual.screen import Screen
from textual.worker import WorkerCancelled
from textual.widgets import Input, Label, OptionList, Static

from tests.fixtures import TuiTestCase, build_wow_tree
from wowtools import __version__
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.updater import ReleaseInfo, UpdateError
from wowtools.ui.base import Ka0sApp, UpdateProgressScreen, UpdateScreen
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
        applied, options = [], []
        with patch("wowtools.ui.base.apply_update",
                   side_effect=lambda rel, **kw: applied.append(rel) or options.append(kw) or "Updated"):
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
        self.assertEqual(options, [{"allow_unverified": False}])  # [general] allow_unverified_updates (F-010)

    async def test_update_applies_in_worker(self):
        """F-005: the download and install run in a worker behind a progress popup; quitting is refused."""
        app = self.make_app()
        release = threading.Event()
        self.addCleanup(release.set)
        seen = []

        def slow_apply(rel, **kw):
            seen.append(threading.current_thread() is threading.main_thread())
            release.wait(5)
            return "Updated to 9.9.9"

        with patch("wowtools.ui.base.apply_update", side_effect=slow_apply):
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._update_found(ReleaseInfo.from_version("9.9.9"))
                await pilot.press("u")
                await pilot.pause()
                await pilot.click("#update-yes")
                await pilot.pause()
                self.assertTrue(app.busy)
                self.assertIsInstance(app.screen, UpdateProgressScreen)
                self.assertIn("9.9.9", str(app.screen.query_one(Label).render()))
                exits = []
                real_exit = app.exit
                app.exit = lambda *a, **k: (exits.append(k.get("message")), real_exit(*a, **k))
                release.set()
                with contextlib.suppress(WorkerCancelled):  # the app exits as the worker ends
                    await app.workers.wait_for_complete()
                deadline = time.monotonic() + 5
                while not exits and time.monotonic() < deadline:
                    await asyncio.sleep(0.02)
                self.assertFalse(app.busy)
        self.assertEqual(seen, [False])
        self.assertEqual(exits, ["Updated to 9.9.9"])

    async def test_update_failure_in_worker_is_shown(self):
        app = self.make_app()
        with patch("wowtools.ui.base.apply_update", side_effect=UpdateError("no network")):
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._update_found(ReleaseInfo.from_version("9.9.9"))
                await pilot.press("u")
                await pilot.pause()
                await pilot.click("#update-yes")
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertFalse(app.busy)
                self.assertIsInstance(app.screen, ToolMenuScreen)
                self.assertTrue(any("no network" in str(n.message) for n in app._notifications))

    async def test_update_blocked_while_busy(self):
        app = self.make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app._update_found(ReleaseInfo.from_version("9.9.9"))
            app.busy = True
            await pilot.press("u")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, UpdateScreen)


class BackgroundUpdateCheckTest(UiTestCase):
    async def test_background_check_persists_on_ui_thread(self):
        """The update check runs in a worker thread, but the config is changed and saved on the UI thread only."""
        self.cfg.save()
        threads = []
        real_save = Config.save

        def save(cfg):
            threads.append((threading.current_thread() is threading.main_thread(),
                            cfg.latest_seen_version))
            real_save(cfg)

        app = WowToolsApp(self.cfg, config_dir=self.tmp, check_updates=True, detect=lambda: [])
        with patch("wowtools.core.updater.fetch_latest", return_value=ReleaseInfo.from_version("9.9.9")), \
                patch.object(Config, "save", save):
            async with app.run_test(size=(120, 40)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertEqual(app.release.version, "9.9.9")
        self.assertEqual(threads, [(True, "9.9.9")])
        self.assertEqual(Config(self.cfg.path).load().latest_seen_version, "9.9.9")


class QuitWhileBusyTest(UiTestCase):
    async def test_ctrl_q_is_refused_while_busy(self):
        app = WowToolsApp(self.cfg, config_dir=self.tmp, check_updates=False, detect=lambda: [])
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.busy = True
            await pilot.press("ctrl+q")
            await pilot.pause()
            self.assertTrue(app.is_running)
            self.assertIsNone(app.return_code)
            self.assertTrue(any("A run is in progress" in n.message for n in app._notifications))
            app.busy = False
            await pilot.press("ctrl+q")
            await pilot.pause()
            self.assertEqual(app.return_code, 0)


class Boom(Screen):
    BINDINGS = [Binding("x", "boom", "Boom"), Binding("w", "boom_in_worker", "Boom in a worker")]

    def compose(self):
        yield Label("boom")

    def action_boom(self):
        raise RuntimeError("boom")

    def action_boom_in_worker(self):
        def work():
            raise RuntimeError("worker boom")

        self.run_worker(work, thread=True)


class CrashLoggingTest(UiTestCase):
    async def test_unhandled_ui_exception_is_logged(self):
        app = Host(self.cfg, Boom())
        with capture_events() as records:
            with self.assertRaises(RuntimeError):
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    await pilot.press("x")
                    await pilot.pause()
        errors = [r["data"] for r in records if r["event"] == "error"]
        self.assertEqual([(e["where"], e["type"], e["message"]) for e in errors], [("ui", "RuntimeError", "boom")])
        self.assertIn("action_boom", errors[0]["traceback"])
        self.assertEqual(app.return_code, 1)

    async def test_worker_exception_is_logged_unwrapped(self):
        app = Host(self.cfg, Boom())
        with capture_events() as records:
            with self.assertRaises(Exception):
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    await pilot.press("w")
                    await app.workers.wait_for_complete()
                    await pilot.pause()
        errors = [r["data"] for r in records if r["event"] == "error"]
        self.assertEqual([(e["where"], e["type"], e["message"]) for e in errors],
                         [("ui", "RuntimeError", "worker boom")])


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

    async def test_detects_installs_in_background(self):
        """F-005: the drive scan runs in a worker; the screen opens at once and fills in what it finds."""
        release = threading.Event()
        self.addCleanup(release.set)
        threads = []

        def slow_detect():
            threads.append(threading.current_thread() is threading.main_thread())
            release.wait(5)
            return [self.root]

        screen = SetupScreen(self.cfg, first_run=True, detect=slow_detect)
        app = Host(self.cfg, screen)
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.pause()
            hint = screen.query_one("#setup-hint", Static)
            self.assertNotIn("Found:", str(hint.render()))
            self.assertEqual(screen.query_one("#wow_path", Input).value, "")
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertTrue(str(hint.render()).startswith("Found:"))
            self.assertEqual(screen.query_one("#wow_path", Input).value, str(self.root))
        self.assertEqual(threads, [False])

    async def test_background_detection_keeps_a_typed_path(self):
        release = threading.Event()
        self.addCleanup(release.set)
        screen = SetupScreen(self.cfg, first_run=True, detect=lambda: (release.wait(5), [self.root])[1])
        app = Host(self.cfg, screen)
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.pause()
            screen.query_one("#wow_path", Input).value = "D:\\Games\\WoW"
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(screen.query_one("#wow_path", Input).value, "D:\\Games\\WoW")

    async def test_prefills_detected_install(self):
        screen = SetupScreen(self.cfg, first_run=True, detect=lambda: [self.root])
        app = Host(self.cfg, screen)
        async with app.run_test(size=(120, 50)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
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
