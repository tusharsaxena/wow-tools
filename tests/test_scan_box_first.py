"""L6 (STD-7.20): a review shows its scan box before any disk access. The checks that touch the disk (the
Screenshot Organizer's destination check, every review's Undo lookup, the WTF Cleaner's crash-marker read) run in a
worker: each test holds one on a gate and checks the review is already drawn, its scan box shown, while it waits."""
from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, Static, Tree

from tests.fixtures import TuiTestCase, build_screenshot_tree, build_wow_tree, make_config, settle
from wowtools.core.config import Config
from wowtools.core.journal import new_journal_path
from wowtools.tools.screenshot_organizer import journal as shots_journal
from wowtools.tools.screenshot_organizer import review_screen as shots_module
from wowtools.tools.screenshot_organizer.review_screen import ShotReviewScreen
from wowtools.tools.wtf_cleaner import journal as wtf_journal
from wowtools.tools.wtf_cleaner import review_screen as wtf_module
from wowtools.tools.wtf_cleaner.review_screen import RecoveryScreen, ReviewScreen
from wowtools.tools.wtf_cleaner.safety import MARKER_NAME
from wowtools.tools.wtf_cleaner.settings import SECTION as WTF_SECTION
from wowtools.ui.account_screen import AccountScreen
from wowtools.ui.dialogs import ConfirmScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.help_screen import HelpScreen
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp

SIZE = (140, 50)
HOLD = 5.0  # a check run on the UI thread would freeze the test this long, then fail it


def held(real, gate: threading.Event, entered: threading.Event, left: threading.Event | None = None):
    """real(), once the gate opens (entered is set as soon as it is called, left once the wait is over)."""
    def wrapper(*args, **kwargs):
        entered.set()
        gate.wait(HOLD)
        if left is not None:
            left.set()
        return real(*args, **kwargs)
    return wrapper


async def wait_for(pilot, condition, what: str, tries: int = 200) -> None:
    """Pause until condition() holds: the UI thread runs meanwhile (a held worker never blocks it)."""
    for _ in range(tries):
        if condition():
            return
        await pilot.pause(0.02)
    raise AssertionError(f"never happened: {what}")


class ShotsScanBoxFirstTest(TuiTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_screenshot_tree(build_wow_tree(self.tmp / "World of Warcraft"))
        self.config_dir = self.tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)
        self.save_dest(self.tmp / "arch")
        self.gate, self.entered = threading.Event(), threading.Event()
        self.addCleanup(self.gate.set)  # a failed check never leaves a worker waiting

    def save_dest(self, dest: Path) -> None:
        tool_cfg = Config(self.config_dir / "screenshot-organizer.cfg")
        tool_cfg.set("screenshot_organizer", "dest_dir", str(dest), log=False)
        tool_cfg.save()

    async def pick_all_flavors(self, app, pilot) -> ShotReviewScreen:
        """The tool menu → the Screenshot Organizer → All flavors; returns the review as soon as it is pushed."""
        await pilot.pause()
        self.assertIsInstance(app.screen, ToolMenuScreen)
        await pilot.press("down", "enter")
        await pilot.pause()
        self.assertIsInstance(app.screen, FlavorScreen)
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, ShotReviewScreen) and self.entered.is_set(),
                       "the review opened and the held check started")
        return app.screen

    def assert_scanning(self, review: ShotReviewScreen, label: str | None) -> None:
        self.assertTrue(review.query_one("#scan-box").display, "the scan box is not shown")
        self.assertFalse(review.query_one("#shots", Tree).display)
        if label is not None:
            self.assertEqual(str(review.query_one("#scan-label", Static).render()), label)
        for button_id in ("#btn-organize", "#btn-dry", "#btn-undo"):
            self.assertTrue(review.query_one(button_id, Button).disabled, button_id)

    def assert_tree_shown(self, review: ShotReviewScreen) -> None:
        self.assertFalse(review.query_one("#scan-box").display)
        self.assertTrue(review.query_one("#shots", Tree).display)

    async def test_destination_check_runs_behind_the_scan_box(self):
        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list)
        with patch.object(shots_module, "validate_dest", held(shots_module.validate_dest, self.gate, self.entered)):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.pick_all_flavors(app, pilot)
                await pilot.pause()
                self.assert_scanning(review, "Checking the destination folder")
                self.assertIsNone(review.plan)
                self.gate.set()
                await settle(app, pilot)
                self.assert_tree_shown(review)
                self.assertEqual(len(review.plan.selectable), 6)
                self.assertTrue(review.query_one("#shots", Tree).root.children)
                self.assertFalse(review.query_one("#btn-organize", Button).disabled)

    async def test_undo_lookup_runs_behind_the_scan_box(self):
        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list)
        with patch.object(shots_module, "latest_undoable",
                          held(shots_module.latest_undoable, self.gate, self.entered)):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.pick_all_flavors(app, pilot)
                await pilot.pause()
                self.assert_scanning(review, None)
                self.gate.set()
                await settle(app, pilot)
                self.assert_tree_shown(review)
                self.assertEqual(len(review.plan.selectable), 6)
                self.assertTrue(review.query_one("#btn-undo", Button).disabled)  # no run yet: nothing to undo

    def write_journal(self) -> Path:
        """An undoable run journal from an earlier session: one screenshot moved."""
        writer = shots_journal.JournalWriter(
            new_journal_path(shots_journal.resolve_journal_dir(self.root)), {"tool": "shots"})
        writer.open()
        writer.add(shots_journal.A_MOVED, self.root / "_retail_" / "Screenshots" / "x.jpg", self.tmp / "arch" / "x.jpg",
                   3)
        writer.finish()
        writer.close()
        return writer.path

    async def test_an_undoable_run_is_offered_once_the_worker_ends(self):
        path = self.write_journal()
        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list)
        with patch.object(shots_module, "latest_undoable",
                          held(shots_module.latest_undoable, self.gate, self.entered)):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.pick_all_flavors(app, pilot)
                await pilot.pause()
                self.assert_scanning(review, None)
                self.gate.set()
                await settle(app, pilot)
                self.assertEqual(review.undoable, path)
                self.assertFalse(review.query_one("#btn-undo", Button).disabled)
                await pilot.press("z")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen)

    async def test_a_failed_scan_still_offers_the_undo(self):
        """A scan that raises after the Undo lookup keeps what the lookup found (as before L6, and as the WTF
        Cleaner does)."""
        path = self.write_journal()

        def broken(*_args, **_kwargs):
            raise OSError("the Screenshots folder is unreadable")

        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list)
        with patch.object(shots_module, "scan", broken):
            async with app.run_test(size=SIZE) as pilot:
                self.entered.set()  # nothing is held
                review = await self.pick_all_flavors(app, pilot)
                await settle(app, pilot)
                self.assertIn("The scan failed", review.summary_text)
                self.assertEqual(review.undoable, path)
                self.assertFalse(review.query_one("#btn-undo", Button).disabled)

    async def test_rescan_is_refused_while_the_destination_is_checked(self):
        """One scan at a time (as the WTF Cleaner): r during the check starts no second worker, so no stale answer
        can replace a newer one and a refused destination gives one toast."""
        self.save_dest(self.root / "_retail_" / "WTF" / "shots")
        calls = []
        real_check = held(shots_module.validate_dest, self.gate, self.entered)
        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list)
        with patch.object(shots_module, "validate_dest", lambda *a: calls.append(a) or real_check(*a)):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.pick_all_flavors(app, pilot)
                await pilot.press("r", "r")
                await pilot.pause()
                self.assert_scanning(review, "Checking the destination folder")
                self.gate.set()
                await settle(app, pilot)
                self.assert_tree_shown(review)
                notes = [n for n in app._notifications if n.title == "Destination not allowed"]
                self.assertEqual(len(notes), 1)
        self.assertEqual(len(calls), 1)

    async def test_a_refused_destination_still_shows_the_error_state(self):
        self.save_dest(self.root / "_retail_" / "WTF" / "shots")
        scans = []
        real_scan = shots_module.scan
        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list)
        with patch.object(shots_module, "validate_dest", held(shots_module.validate_dest, self.gate, self.entered)), \
                patch.object(shots_module, "scan", lambda *a, **k: scans.append(a) or real_scan(*a, **k)):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.pick_all_flavors(app, pilot)
                await pilot.pause()
                self.assert_scanning(review, "Checking the destination folder")
                self.gate.set()
                await settle(app, pilot)
                self.assert_tree_shown(review)
                self.assertIsNone(review.plan)
                self.assertFalse(review.query_one("#shots", Tree).root.children)
                self.assertIn("Fix the folder in settings (s).", review.summary_text)
                self.assertIn("WTF", review.summary_text)
                for button_id in ("#btn-organize", "#btn-dry"):
                    self.assertTrue(review.query_one(button_id, Button).disabled, button_id)
                notes = [n for n in app._notifications if n.title == "Destination not allowed"]
                self.assertEqual(len(notes), 1)
                self.assertEqual(notes[0].severity, "error")
                self.assertEqual(notes[0].message, review.summary_text)
        self.assertEqual(scans, [])
        self.assertFalse((self.root / "_retail_" / "WTF" / "shots").exists())


class WtfScanBoxFirstTest(TuiTestCase):
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
        self.gate, self.entered = threading.Event(), threading.Event()
        self.addCleanup(self.gate.set)

    def make_app(self) -> WowToolsApp:
        app = WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list,
                          tool_options={"wtf-cleaner": {"wow_check": list, "locker_check": list}})
        app.disclaimers_accepted.add(WTF_SECTION)  # accepted earlier in the session: the review opens at once
        return app

    async def pick_retail(self, app, pilot) -> ReviewScreen:
        await pilot.pause()
        self.assertIsInstance(app.screen, ToolMenuScreen)
        await pilot.press("enter")
        await pilot.pause()
        self.assertIsInstance(app.screen, FlavorScreen)
        await pilot.press("enter")
        await pilot.pause()
        self.assertIsInstance(app.screen, AccountScreen)
        await pilot.press("enter")  # all accounts
        await wait_for(pilot, lambda: isinstance(app.screen, ReviewScreen) and self.entered.is_set(),
                       "the review opened and the held check started")
        return app.screen

    async def test_undo_lookup_runs_behind_the_scan_box(self):
        app = self.make_app()
        with patch.object(wtf_module, "latest_undoable", held(wtf_module.latest_undoable, self.gate, self.entered)):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.pick_retail(app, pilot)
                await pilot.pause()
                self.assertTrue(review.query_one("#scan-box").display, "the scan box is not shown")
                self.assertTrue(review.query_one("#btn-undo", Button).disabled)
                self.assertIsNone(review.proposal)
                self.gate.set()
                await settle(app, pilot)
                self.assertFalse(review.query_one("#scan-box").display)
                self.assertIsNotNone(review.proposal)
                self.assertTrue(review.query_one("#btn-undo", Button).disabled)  # no clean yet: nothing to undo

    def write_journal(self) -> Path:
        """An undoable clean journal from an earlier session: one file deleted from Retail."""
        folder = wtf_journal.resolve_journal_dir(self.root)
        writer = wtf_journal.CleanJournal(new_journal_path(folder), {"tool": "wtf", "flavors": ["_retail_"]})
        writer.open()
        writer.add_deleted(flavor="_retail_", path=self.root / "_retail_" / "WTF" / "gone.lua", rel="WTF/gone.lua",
                           size=1, mtime=0.0, zip_path=None, snapshot=None)
        writer.finish()
        writer.close()
        return writer.path

    def write_marker(self) -> None:
        backup_dir = self.tmp / "bk"
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / MARKER_NAME).write_text(json.dumps({
            "snapshot": str(backup_dir / "backup" / "x.zip"), "flavor": "_retail_",
            "flavor_path": str(self.root / "_retail_"), "started": "2026-01-01T00:00:00", "pid": 1,
            "suite_version": "0.1.0", "files": ["WTF/x.lua"]}), encoding="utf-8")

    async def test_an_undoable_clean_is_offered_once_the_worker_ends(self):
        path = self.write_journal()
        app = self.make_app()
        with patch.object(wtf_module, "latest_undoable", held(wtf_module.latest_undoable, self.gate, self.entered)):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.pick_retail(app, pilot)
                await pilot.pause()
                self.assertTrue(review.query_one("#btn-undo", Button).disabled)
                self.gate.set()
                await settle(app, pilot)
                self.assertEqual(review.undoable, path)
                self.assertFalse(review.query_one("#btn-undo", Button).disabled)
                await pilot.press("z")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ConfirmScreen)
                await pilot.press("escape")
                await settle(app, pilot)
                # A later failed scan whose lookup found nothing undoable (undone elsewhere) drops the stale run
                review._scan_failed("The scan failed: x", None)
                self.assertIsNone(review.undoable)
                self.assertTrue(review.query_one("#btn-undo", Button).disabled)

    async def test_recovery_notice_waits_until_the_review_is_shown(self):
        """The marker read ends while another screen (here the help) is on top: the notice opens once the review
        is shown again, never over that screen (nor over a confirm or a run's progress popup)."""
        self.write_marker()
        app = self.make_app()
        with patch.object(wtf_module, "read_marker", held(wtf_module.read_marker, self.gate, self.entered)):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.pick_retail(app, pilot)
                await wait_for(pilot, lambda: review.proposal is not None, "the scan ended")
                await pilot.press("h")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, HelpScreen)
                self.gate.set()
                await settle(app, pilot)
                self.assertIsInstance(app.screen, HelpScreen)
                await pilot.press("escape")
                await settle(app, pilot)
                self.assertIsInstance(app.screen, RecoveryScreen)
                self.assertIs(app.screen_stack[-2], review)

    async def test_recovery_check_never_holds_the_review(self):
        """The crash-marker read runs in its own worker: the scan ends and the tree is drawn while it waits."""
        app, left = self.make_app(), threading.Event()
        with patch.object(wtf_module, "read_marker", held(wtf_module.read_marker, self.gate, self.entered, left)):
            async with app.run_test(size=SIZE) as pilot:
                review = await self.pick_retail(app, pilot)
                await wait_for(pilot, lambda: review.proposal is not None, "the scan ended")
                self.assertFalse(left.is_set(), "the marker read held the UI thread")
                self.assertFalse(review.query_one("#scan-box").display)
                self.assertIs(app.screen, review)
                self.gate.set()
                await settle(app, pilot)
                self.assertIs(app.screen, review)
                self.assertNotIsInstance(app.screen, RecoveryScreen)
