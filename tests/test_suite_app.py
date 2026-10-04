from __future__ import annotations

import json
import os
import socket
import tempfile
import unittest
from pathlib import Path

from textual.widgets import Button

from tests.fixtures import TuiTestCase, settle, build_wow_tree, make_config
from wowtools.core.config import Config
from wowtools.core.events import capture_events, get_event_log
from wowtools.core.lock import InstanceLock, LockInfo
from wowtools.tools.wtf_cleaner.review_screen import ReviewScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.setup_screen import SetupScreen
from wowtools.ui.suite_app import LockScreen, ToolMenuScreen, WowToolsApp

SIZE = (140, 50)


class SuiteAppTest(TuiTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.config_dir = self.tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)
        tool_cfg = Config(self.config_dir / "wtf-cleaner.cfg")
        tool_cfg.set("wtf_cleaner", "backup_dir", str(self.tmp / "bk"), log=False)
        tool_cfg.save()
        self.lock = InstanceLock(self.tmp / "wow-tools.lock")
        self.addCleanup(get_event_log().set_context, tool="suite")

    def make_app(self, conflict=None):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=lambda: [],
                           lock=self.lock, conflict=conflict,
                           tool_options={"wtf-cleaner": {"wow_check": lambda: [], "locker_check": lambda: []}})

    async def open_cleaner(self, app, pilot):
        await pilot.pause()
        self.assertIsInstance(app.screen, ToolMenuScreen)
        await pilot.press("enter")
        await pilot.pause()

    async def test_tool_opens_in_the_same_app_and_esc_returns_to_menu(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_cleaner(app, pilot)
            self.assertIsInstance(app.screen, FlavorScreen)
            self.assertIsNotNone(app.flow)
            self.assertEqual(get_event_log().tool, "wtf-cleaner")
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(app.screen, ToolMenuScreen)
            self.assertIsNone(app.flow)
            self.assertEqual(get_event_log().tool, "suite")
            await pilot.press("enter")  # and in again
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)

    async def test_t_on_review_goes_back_to_the_menu(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_cleaner(app, pilot)
            await pilot.press("enter", "enter")  # flavor, all accounts
            await pilot.pause()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ReviewScreen)
            await pilot.press("t")
            await pilot.pause()
            self.assertIsInstance(app.screen, ToolMenuScreen)
            self.assertEqual(len(app.screen_stack), 2)  # Textual's default screen + the menu

    async def test_s_on_menu_opens_general_settings_only(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            self.assertIsInstance(app.screen, SetupScreen)
            await pilot.press("escape")
            await pilot.pause()
            self.assertIsInstance(app.screen, ToolMenuScreen)

    async def test_lock_conflict_quit(self):
        holder = LockInfo(12345, "other-pc", "2026-10-03T10:00:00", "windows", "abc")
        app = self.make_app(conflict=holder)
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                await pilot.pause()
                self.assertIsInstance(app.screen, LockScreen)
                self.assertIn("other-pc", str(app.screen.query_one("#lock-body").render()))
                self.assertEqual(app.screen.focused.id, "lock-quit")  # not known to be stale: Quit first
                await pilot.press("q")
                await pilot.pause()
            self.assertFalse(self.lock.held)
        self.assertIn({"screen": "lock", "control": "lock", "value": "quit"},
                      [r["data"] for r in records if r["event"] == "ui.selection"])

    async def test_lock_conflict_override_takes_the_lock(self):
        self.lock.path.write_text(json.dumps({"pid": 1, "host": "x", "started": "", "platform": "", "token": "t"}))
        holder = self.lock.read()
        app = self.make_app(conflict=holder)
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                await pilot.pause()
                await pilot.click("#lock-override")
                await pilot.pause()
                self.assertIsInstance(app.screen, ToolMenuScreen)
        self.assertTrue(self.lock.held)
        self.assertEqual(self.lock.read().token, self.lock.info.token)
        self.assertIn("lock.overridden", [r["event"] for r in records])

    async def test_stale_lock_defaults_to_override(self):
        stale = LockInfo(2 ** 22 + 12345, socket.gethostname(), "", self.lock.info.platform, "t")
        if os.name != "posix" or stale.stale is not True:
            self.skipTest("stale detection needs POSIX")
        app = self.make_app(conflict=stale)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            self.assertEqual(app.screen.focused.id, "lock-override")
            self.assertIn("left over from a crash", str(app.screen.query_one("#lock-body").render()))


class InstanceLockTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "wow-tools.lock"

    def test_first_acquires_second_sees_holder(self):
        first, second = InstanceLock(self.path), InstanceLock(self.path)
        self.assertIsNone(first.acquire())
        holder = second.acquire()
        self.assertEqual(holder.token, first.info.token)
        self.assertEqual(holder.pid, os.getpid())
        self.assertFalse(second.held)
        second.release()  # not ours: nothing happens
        self.assertTrue(self.path.exists())
        first.release()
        self.assertFalse(self.path.exists())

    def test_take_over_then_original_release_keeps_new_lock(self):
        first, second = InstanceLock(self.path), InstanceLock(self.path)
        first.acquire()
        second.acquire()
        second.take_over()
        first.release()  # the file is no longer first's
        self.assertEqual(second.read().token, second.info.token)
        second.release()
        self.assertFalse(self.path.exists())

    def test_unreadable_lock_is_still_a_conflict(self):
        self.path.write_text("garbage")
        holder = InstanceLock(self.path).acquire()
        self.assertIsNotNone(holder)
        self.assertIsNone(holder.pid)
        self.assertIn("unknown", holder.describe())

    def test_own_live_process_is_not_stale(self):
        lock = InstanceLock(self.path)
        if os.name != "posix":
            self.skipTest("POSIX only")
        self.assertIs(lock.info.stale, False)


class ToolMenuLabelTest(unittest.TestCase):
    def test_names_line_up_and_are_coloured(self):
        from wowtools.tools import TOOLS
        from wowtools.ui.suite_app import TOOL_NAME_STYLE, tool_label

        width = max(len(t.title) for t in TOOLS.values()) + 3
        labels = [tool_label(t.title, t.description, width) for t in TOOLS.values()]
        starts = {label.plain.index(tool.description) for label, tool in zip(labels, TOOLS.values())}
        self.assertEqual(starts, {width})  # every description starts in the same column
        for label, tool in zip(labels, TOOLS.values()):
            self.assertEqual(str(label.spans[0].style), TOOL_NAME_STYLE)
            self.assertEqual(label.spans[0].end, width)
