from __future__ import annotations

import asyncio
import contextlib
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from textual.binding import Binding
from textual.screen import ModalScreen, Screen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets._header import HeaderTitle
from textual.worker import WorkerCancelled, WorkerFailed

from tests.fixtures import TuiTestCase, build_wow_tree
from wowtools import __version__
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.install import WowInstall
from wowtools.core.updater import ReleaseInfo, UpdateError
from wowtools.tools import TOOLS
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.base import Ka0sApp, UpdateProgressScreen, UpdateScreen
from wowtools.ui.branding import (BottomBar, BrandBar, VersionLine, brand_texts, update_key_free, update_notice,
                                  version_text)
from wowtools.ui.dialogs import CONFIRM_GUARD, InfoScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.setup_screen import SetupScreen
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp
from wowtools.ui.theme import TITLE_GOLD, TITLE_TEXT, TITLE_TOOL
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
        # `u` asks GitHub again before it offers an update (D16): tests answer for GitHub, never the network.
        self.published = ReleaseInfo.from_version("9.9.9")
        fetch = patch("wowtools.core.updater.fetch_latest", side_effect=lambda: self.published)
        self.fetch = fetch.start()
        self.addCleanup(fetch.stop)

    async def press_update(self, app, pilot):
        """Press `u` and wait for its fresh update check to answer."""
        await pilot.press("u")
        await app.workers.wait_for_complete()
        await pilot.pause()


class SuiteAppBaseTest(UiTestCase):
    def make_app(self):
        return WowToolsApp(self.cfg, config_dir=self.tmp, check_updates=False, detect=list)

    async def test_theme_branding_and_menu_first(self):
        app = self.make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            self.assertEqual(app.theme, "ka0s")
            self.assertEqual(app.title, "Ka0s WoW Tools")
            self.assertIsInstance(app.screen, ToolMenuScreen)
            self.assertIn(f"Ka0s WoW Tools v{__version__}", app.screen.query_one(BrandBar).text)
            options = app.screen.query_one("#tools", OptionList)
            self.assertEqual([options.get_option_at_index(i).id for i in range(options.option_count)],
                             list(TOOLS))

    async def test_title_bar_is_gold_then_near_white_all_bold(self):
        """Spec D41: "Ka0s WoW Tools" in gold, the tool, flavor and view in near-white, all bold (the app formats
        every screen's title bar), at 120x30 and 80x24."""
        for size in ((120, 30), (80, 24)):
            app = self.make_app()
            async with app.run_test(size=size) as pilot:
                await pilot.pause()
                header = app.screen.query_one(HeaderTitle)
                content = app.format_title(app.title, app.screen.sub_title)  # the menu: no tool name
                self.assertEqual([(content.plain[s.start:s.end], str(s.style)) for s in content.spans],
                                 [("Ka0s WoW Tools", f"bold {TITLE_GOLD}"),
                                  (f" — {app.screen.sub_title}", f"bold {TITLE_TEXT}")], size)
                for tool, rest in (("WTF Cleaner", " · Retail · review"), ("Saved Variables Browser", " · Retail"),
                                   ("Ace3 Profile Manager", "")):
                    sub_title = tool + rest
                    content = app.format_title(app.title, sub_title)
                    self.assertEqual(content.plain, f"Ka0s WoW Tools — {sub_title}")
                    spans = [(content.plain[s.start:s.end], str(s.style)) for s in content.spans]
                    expected = [("Ka0s WoW Tools", f"bold {TITLE_GOLD}"), (" — ", f"bold {TITLE_TEXT}"),
                                (tool, f"bold {TITLE_TOOL}")] + ([(rest, f"bold {TITLE_TEXT}")] if rest else [])
                    self.assertEqual(spans, expected, size)
                self.assertEqual([(s.plain[x.start:x.end], str(x.style)) for s in
                                  [app.format_title(app.title, "WTF Cleaner settings")] for x in s.spans][2],
                                 ("WTF Cleaner", f"bold {TITLE_TOOL}"))
                strip = header.render_line(0)
                segments = [(seg.text, seg.style) for seg in strip if seg.text.strip()]
                gold = [seg for seg in segments if "Ka0s" in seg[0]]
                self.assertTrue(gold and gold[0][1].bold, segments)
                self.assertEqual(gold[0][1].color.triplet.hex.upper(), TITLE_GOLD.upper())

    def test_version_text_names_the_new_version(self):
        """Spec D4: the menu's line under the banner is the version, plus the update notice once one is found."""
        self.assertEqual(version_text("0.1.0", None), "v0.1.0")
        self.assertEqual(version_text("0.1.0", "9.9.9"), "v0.1.0 · v9.9.9 available, press u to update")

    async def test_menu_version_line_follows_the_update_check(self):
        app = self.make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            line = app.screen.query_one(VersionLine)
            self.assertEqual(line.text, f"v{__version__}")
            self.assertFalse(line.has_class("-update"))
            app._update_found(ReleaseInfo.from_version("9.9.9"))
            await pilot.pause()
            self.assertEqual(line.text, f"v{__version__} · v9.9.9 available, press u to update")
            self.assertTrue(line.has_class("-update"))

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
                await self.press_update(app, pilot)
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
                await self.press_update(app, pilot)
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
                await self.press_update(app, pilot)
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
            self.fetch.assert_not_called()


    async def test_update_of_a_vanished_release_says_no_update_and_clears_the_notice(self):
        """D16: the notice came from the cache, but the release was deleted since. `u` re-checks, installs nothing,
        says there is no update and drops the notice from the bar and the menu."""
        self.cfg.set("general", "latest_seen_version", "9.9.9", log=False)
        self.cfg.save()
        self.published = None
        app = self.make_app()
        with patch("wowtools.ui.base.apply_update", side_effect=AssertionError("must not install")) as apply:
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._update_found(ReleaseInfo.from_version("9.9.9"))
                await pilot.pause()
                await self.press_update(app, pilot)
                self.assertNotIsInstance(app.screen, UpdateScreen)
                self.assertIsNone(app.release)
                self.assertNotIn("9.9.9", app.screen.query_one(BrandBar).text)
                self.assertEqual(app.screen.query_one(VersionLine).text, f"v{__version__}")
                self.assertTrue(any("No update available" in str(n.message) for n in app._notifications))
                await pilot.press("u")  # nothing to offer now: no second check
                await pilot.pause()
        apply.assert_not_called()
        self.fetch.assert_called_once()
        self.assertIsNone(Config(self.cfg.path).load().latest_seen_version)

    async def test_update_offers_what_the_fresh_check_finds(self):
        """The cached notice said 9.9.9 but GitHub now has 9.9.10: that is the one offered and installed."""
        self.published = ReleaseInfo.from_version("9.9.10")
        app = self.make_app()
        applied = []
        with patch("wowtools.ui.base.apply_update", side_effect=lambda rel, **kw: applied.append(rel) or "Updated"):
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._update_found(ReleaseInfo.from_version("9.9.9"))
                await self.press_update(app, pilot)
                self.assertIsInstance(app.screen, UpdateScreen)
                self.assertEqual(app.release.version, "9.9.10")
                await pilot.click("#update-yes")
                await pilot.pause()
        self.assertEqual([r.version for r in applied], ["9.9.10"])

    async def test_update_check_failure_on_u_keeps_the_notice(self):
        def offline():
            raise OSError("offline")
        self.fetch.side_effect = offline
        app = self.make_app()
        with patch("wowtools.ui.base.apply_update", side_effect=AssertionError("must not install")):
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._update_found(ReleaseInfo.from_version("9.9.9"))
                await self.press_update(app, pilot)
                self.assertNotIsInstance(app.screen, UpdateScreen)
                self.assertEqual(app.release.version, "9.9.9")
                self.assertTrue(any("Could not check for updates" in str(n.message) for n in app._notifications))

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

        app = WowToolsApp(self.cfg, config_dir=self.tmp, check_updates=True, detect=list)
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
        app = WowToolsApp(self.cfg, config_dir=self.tmp, check_updates=False, detect=list)
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
    BINDINGS: ClassVar[list[Binding]] = [Binding("x", "boom", "Boom"),
                                         Binding("w", "boom_in_worker", "Boom in a worker")]

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
        with capture_events() as records, self.assertRaises(RuntimeError):
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
        with capture_events() as records, self.assertRaises(WorkerFailed):
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
        screen = SetupScreen(self.cfg, first_run=True, detect=list)
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

    async def test_saves_retention_to_general(self):
        """Feedback round 1: backups and journals to keep are global, edited here."""
        self.cfg.set("general", "wow_path", str(self.root), log=False)
        screen = SetupScreen(self.cfg, first_run=False, detect=list)
        app = Host(self.cfg, screen)
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.pause()
            self.assertEqual(screen.query_one("#keep-backups", Input).value, "10")
            self.assertEqual(screen.query_one("#keep-journals", Input).value, "10")
            self.assertEqual(screen.query_one("#parallelism", Input).value, "2")
            screen.query_one("#keep-backups", Input).value = "0"
            screen.query_one("#keep-journals", Input).value = "4"
            screen.query_one("#parallelism", Input).value = "1"
            await pilot.click("#save")
            await pilot.pause()
        self.assertEqual(app.results, [True])
        saved = Config(self.cfg.path).load()
        self.assertEqual((saved.keep_backups, saved.keep_journals, saved.parallelism), (0, 4, 1))
        self.assertEqual(saved.get("general", "keep_backups"), "0")
        self.assertEqual(saved.get("general", "parallelism"), "1")

    async def test_down_reaches_every_field_at_80x24(self):
        """Feedback round 1 review: at 80x24 the form is taller than the screen; ↓ still moves focus field by field
        (it used to scroll the form instead, so the retention fields were reachable only with Tab)."""
        self.cfg.set("general", "wow_path", str(self.root), log=False)
        screen = SetupScreen(self.cfg, first_run=False, detect=list)
        app = Host(self.cfg, screen)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            self.assertEqual(screen.focused.id, "wow_path")
            for expected in ("keep-backups", "keep-journals", "parallelism", "save"):
                await pilot.press("down")
                await pilot.pause()
                self.assertEqual(screen.focused.id, expected)
            await pilot.press("up")
            await pilot.pause()
            self.assertEqual(screen.focused.id, "parallelism")

    async def test_rejects_bad_retention_values(self):
        self.cfg.set("general", "wow_path", str(self.root), log=False)
        screen = SetupScreen(self.cfg, first_run=False, detect=list)
        app = Host(self.cfg, screen)
        cases = (("keep-backups", "lots"), ("keep-backups", "-1"), ("keep-journals", "x"), ("keep-journals", "0"),
                 ("parallelism", "0"), ("parallelism", "9"), ("parallelism", "many"))
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.pause()
            for box, value in cases:
                screen.error_text = ""
                screen.query_one("#keep-backups", Input).value = "10"
                screen.query_one("#keep-journals", Input).value = "10"
                screen.query_one("#parallelism", Input).value = "2"
                screen.query_one(f"#{box}", Input).value = value
                screen._save()
                await pilot.pause()
                self.assertTrue(screen.error_text, (box, value))
                self.assertEqual(app.results, [], (box, value))
        self.assertIsNone(Config(self.cfg.path).load().get("general", "keep_backups"))
        self.assertIsNone(Config(self.cfg.path).load().get("general", "keep_journals"))
        self.assertIsNone(Config(self.cfg.path).load().get("general", "parallelism"))

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

    async def test_update_now_waits_for_the_enter_guard(self):
        self.confirm_guard(CONFIRM_GUARD)
        with patch("wowtools.ui.dialogs.monotonic", lambda: 1000.0):  # time stands still: always within the guard
            screen = UpdateScreen(ReleaseInfo.from_version("9.9.9"))
            app = Host(self.cfg, screen)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                self.assertEqual(screen.focused.id, "update-yes")
                await pilot.press("enter")
                await pilot.pause()
                self.assertIs(app.screen, screen)
                await pilot.press("escape")
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


class U(Screen):
    BINDINGS: ClassVar[list[Binding]] = [Binding("u", "unlock", "Unlock", show=False)]


class BrandTextTest(UiTestCase):
    def test_wordings_longest_first_and_the_key_named_right(self):
        """brand_texts gives the brand bar its wordings longest first; each update wording keeps the new
        version, and where u is the screen's own key (spec D15) none says "press u" without the tool menu."""
        self.assertEqual(brand_texts("1.0.0", None, True), ["Ka0s WoW Tools v1.0.0", "v1.0.0"])
        for key_free in (True, False):
            texts = brand_texts("1.0.0", "2.0.0", key_free)
            self.assertEqual(texts[0], f"⬆ {update_notice('2.0.0', key_free)} · Ka0s WoW Tools v1.0.0")
            self.assertEqual([len(t) for t in texts], sorted((len(t) for t in texts), reverse=True))
            self.assertTrue(all(t.startswith("⬆ v2.0.0") for t in texts), texts)
            if not key_free:
                self.assertFalse([t for t in texts if "press u" in t and "tool menu" not in t], texts)
        self.assertEqual(update_notice("2.0.0", True), "v2.0.0 available, press u to update")
        self.assertEqual(update_notice("2.0.0", False), "v2.0.0 available, press u on the tool menu to update")

    async def test_a_screen_binding_u_is_not_key_free_and_the_toast_says_so(self):
        app = Host(self.cfg, U())
        notes = []
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            self.assertFalse(update_key_free(app.screen))
            self.assertTrue(update_key_free(app.screen_stack[0]))
            with patch.object(app, "notify", side_effect=lambda message, **kw: notes.append(message)):
                app._update_found(ReleaseInfo.from_version("9.9.9"))
        self.assertEqual(notes, ["Ka0s WoW Tools v9.9.9 available, press u on the tool menu to update."])

    async def test_a_focused_text_box_is_not_key_free_and_the_bar_follows_the_focus(self):
        """A focused Input types the `u`, so the bar names the tool menu while it has focus, and says "press u"
        again once the focus leaves it."""
        class Form(Screen):
            def compose(self):
                yield Input(id="field")
                yield Static("x", id="other")
                yield BottomBar()

        app = Host(self.cfg, Form())
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            app.screen.query_one("#field").focus()
            app.release = ReleaseInfo.from_version("9.9.9")
            await pilot.pause()
            self.assertFalse(update_key_free(app.screen))
            bar = app.screen.query_one(BrandBar)
            self.assertIn("press u on the tool menu", bar.text)
            app.screen.set_focus(None)
            await pilot.pause()
            self.assertTrue(update_key_free(app.screen))
            self.assertIn("press u to update", bar.text)

    async def test_a_popup_is_judged_by_the_screen_under_it(self):
        """The toast for a release found while a popup sits over a screen binding u names the tool menu."""
        app = Host(self.cfg, U())
        notes = []
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            app.push_screen(InfoScreen("Title", {}))
            await pilot.pause()
            self.assertIsInstance(app.screen, ModalScreen)
            self.assertFalse(update_key_free(app.screen))
            with patch.object(app, "notify", side_effect=lambda message, **kw: notes.append(message)):
                app._update_found(ReleaseInfo.from_version("9.9.9"))
        self.assertEqual(notes, ["Ka0s WoW Tools v9.9.9 available, press u on the tool menu to update."])


class WrapItemsTest(unittest.TestCase):
    def test_breaks_only_between_items_and_counts_the_mark(self):
        from wowtools.ui.widgets import wrap_items
        text = "a all · n none · r rescan · c collapse all"
        self.assertEqual(wrap_items(text, 0), text)  # width not known yet
        self.assertEqual(wrap_items(text, 80), text)
        self.assertEqual(wrap_items(text, 18), "a all · n none ·\nr rescan ·\nc collapse all")
        for line in wrap_items(text, 18).splitlines():
            self.assertLessEqual(len(line), 18)
        self.assertEqual(wrap_items("1 a → 2 b → 3 c", 8, " → "), "1 a →\n2 b →\n3 c")


class ActionColoursTest(unittest.TestCase):
    def test_every_kind_has_a_readable_colour_and_a_variant(self):
        from wowtools.ui.theme import ACTION_COLOURS, KA0S_THEME, action_text, contrast
        from wowtools.ui.widgets import ACTION_CSS, ACTION_VARIANTS
        self.assertEqual(list(ACTION_COLOURS), list(ACTION_VARIANTS))
        self.assertEqual(len(ACTION_COLOURS), 9)
        for kind, (background, _) in ACTION_COLOURS.items():
            with self.subTest(kind=kind):
                self.assertGreaterEqual(contrast(background, action_text(kind)), 4.5)
                self.assertIn(f"-act-{kind}", ACTION_CSS)
                self.assertEqual(KA0S_THEME.variables[f"act-{kind}"], background)
        backgrounds = [background for background, _ in ACTION_COLOURS.values()]
        self.assertEqual(len(set(backgrounds)), 9)  # nine kinds, nine colours

    def test_button_colours_keep_clear_of_the_wtf_criterion_colours(self):
        """The WTF review shows its criteria in colour next to its Clean (red), Dry run (cyan), Rescan (lime) and
        Undo (violet) buttons: only red is shared (not installed means deleted); the others are other hues."""
        from textual.color import Color
        from wowtools.tools.wtf_cleaner.report import CRITERION_COLORS
        from wowtools.ui.theme import ACTION_COLOURS
        self.assertEqual(ACTION_COLOURS["destructive"][0], CRITERION_COLORS["not_installed"])

        def hue(colour):
            return Color.parse(colour).hsl[0] * 360

        for kind in ("simulate", "revert", "refresh"):
            for criterion, colour in CRITERION_COLORS.items():
                with self.subTest(kind=kind, criterion=criterion):
                    gap = abs(hue(ACTION_COLOURS[kind][0]) - hue(colour)) % 360
                    self.assertGreaterEqual(min(gap, 360 - gap), 25)

    def test_action_button_kinds(self):
        from wowtools.ui.widgets import action_button, action_kind
        cases = {"destructive": "error", "overwrite": "warning", "create": "success", "revert": "warning",
                 "refresh": "success",
                 "simulate": "primary", "confirm": "primary", "navigate": "default", "cancel": "default"}
        for kind, variant in cases.items():
            button = action_button("Go", kind, id="go", classes="extra")
            self.assertEqual((button.variant, action_kind(button)), (variant, kind))
            self.assertTrue(button.has_class("extra"))
        with self.assertRaises(ValueError):
            action_button("Go", "apply")
