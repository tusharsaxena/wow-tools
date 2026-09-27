import tempfile
import unittest
from pathlib import Path

from textual.widgets import Input, Tree

from tests.fixtures import build_wow_tree, make_config
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.tools.wtf_cleaner.app import CleanerSettingsScreen, WtfCleanerApp
from wowtools.tools.wtf_cleaner.review_screen import ConfirmScreen, ResultScreen, ReviewScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.setup_screen import SetupScreen

SIZE = (140, 50)


class AppTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_wow_tree(self.tmp / "World of Warcraft")
        self.sv = self.root / "_retail_" / "WTF" / "Account" / "ACCT1" / "SavedVariables"
        self.backup_dir = self.tmp / "bk"
        self.cfg = make_config(self.tmp, self.root, backup_dir=str(self.backup_dir))

    def make_app(self, cfg=None, running=()):
        return WtfCleanerApp(cfg or self.cfg, check_updates=False, wow_check=lambda: list(running),
                             detect=lambda: [])

    async def open_review(self, app, pilot):
        await pilot.pause()
        self.assertIsInstance(app.screen, FlavorScreen)
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        review = app.screen
        self.assertIsInstance(review, ReviewScreen)
        self.assertIsNotNone(review.proposal)
        return review


class ReviewFlowTest(AppTestCase):
    async def test_dry_run_flow_changes_nothing(self):
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                self.assertEqual(len(review.proposal.items), 6)
                await pilot.press("d")
                self.assertTrue(review.dry_run)
                await pilot.press("c")
                await pilot.pause()
                self.assertIsInstance(app.screen, ConfirmScreen)
                await pilot.press("y")
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertIsInstance(app.screen, ResultScreen)
                self.assertTrue(app.screen.result.dry_run)
                self.assertEqual(len(app.screen.result.would_delete), 8)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())
        self.assertFalse(self.backup_dir.exists())
        names = [r["event"] for r in records]
        self.assertIn("sv.would_delete", names)
        self.assertIn({"screen": "review", "control": "dry_run", "value": True},
                      [r["data"] for r in records if r["event"] == "ui.selection"])

    async def test_real_clean_backs_up_and_deletes(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertIsInstance(app.screen, ResultScreen)
            self.assertEqual(len(app.screen.result.deleted), 8)
        self.assertFalse((self.sv / "Uninstalled.lua").exists())
        self.assertTrue((self.sv / "Auctionator.lua").exists())
        self.assertEqual(len(list(self.backup_dir.glob("*.zip"))), 1)

    async def test_declining_confirm_changes_nothing(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            self.assertIs(app.screen, review)
        self.assertTrue((self.sv / "Uninstalled.lua").exists())

    async def test_toggle_excludes_item_and_criterion_keys_rebuild(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one(Tree)
            node = next(n for n in _walk(tree.root)
                        if n.data and n.data[0] == "item" and n.data[1].addon == "DisabledAddon")
            tree.focus()
            tree.move_cursor(node)
            await pilot.press("space")
            self.assertNotIn("DisabledAddon", {i.addon for i in review._selection()})
            self.assertIn("5 items", review.summary_text)
            await pilot.press("1")
            await pilot.pause()
            self.assertNotIn("Uninstalled", {i.addon for i in review.proposal.items})
            self.assertFalse(review.criteria.not_installed)

    async def test_wow_running_warning_is_shown_and_logged(self):
        app = self.make_app(running=["Wow.exe"])
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                await self.open_review(app, pilot)
                await pilot.press("c")
                await pilot.pause()
                self.assertIsInstance(app.screen, ConfirmScreen)
                self.assertIn("Wow.exe", app.screen.body_text)
                await pilot.press("n")
        self.assertIn("wow.running_warning", [r["event"] for r in records])

    async def test_odd_names_render_without_markup(self):
        (self.sv / "[Weird] Addon.lua").write_text("x")
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            labels = [str(n.label) for n in _walk(review.query_one(Tree).root)]
            self.assertTrue(any("[Weird] Addon" in label for label in labels))


class FirstRunTest(AppTestCase):
    async def test_setup_then_settings_then_flavor(self):
        cfg = Config(self.tmp / "fresh.cfg")
        app = self.make_app(cfg=cfg)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen, SetupScreen)
            app.screen.query_one("#wow_path", Input).value = str(self.root)
            await pilot.click("#save")
            await pilot.pause()
            self.assertIsInstance(app.screen, CleanerSettingsScreen)
            app.screen.query_one("#max_age", Input).value = "30"
            await pilot.click("#save")
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
        saved = Config(cfg.path).load()
        self.assertEqual(saved.wow_path, self.root)
        self.assertEqual(saved.get("wtf_cleaner", "max_age_days"), "30")

    async def test_settings_rejects_bad_max_age(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            screen = CleanerSettingsScreen(self.cfg, source="settings")
            app.push_screen(screen)
            await pilot.pause()
            screen.query_one("#max_age", Input).value = "0"
            await pilot.click("#save")
            await pilot.pause()
            self.assertIs(app.screen, screen)
            self.assertIn("whole number", screen.error_text)


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)
