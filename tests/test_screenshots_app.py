import tempfile
from pathlib import Path

from textual.widgets import Button, DataTable, Input, Static, Tree

from tests.fixtures import TuiTestCase, build_screenshot_tree, build_wow_tree, make_config
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.tools.screenshots.app import ScreenshotSettingsScreen
from wowtools.tools.screenshots.journal import latest_undoable
from wowtools.tools.screenshots.review_screen import ShotResultScreen, ShotReviewScreen
from wowtools.tools.screenshots.settings import load_settings
from wowtools.tools.wtf_cleaner.review_screen import ConfirmScreen
from wowtools.ui.flavor_screen import FlavorScreen
from wowtools.ui.suite_app import ToolMenuScreen, WowToolsApp

SIZE = (140, 50)
A = "WoWScrnShot_073119_232713.jpg"


class ShotsAppTest(TuiTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = build_screenshot_tree(build_wow_tree(self.tmp / "World of Warcraft"))
        self.shots = self.root / "_retail_" / "Screenshots"
        self.config_dir = self.tmp / "config"
        self.cfg = make_config(self.config_dir, self.root)
        self.dest = self.tmp / "arch"

    def save_tool_cfg(self, **values):
        tool_cfg = Config(self.config_dir / "screenshots.cfg")
        for key, value in values.items():
            tool_cfg.set("screenshots", key, value, log=False)
        tool_cfg.save()

    def make_app(self):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=lambda: [])

    async def open_tool(self, app, pilot):
        await pilot.pause()
        self.assertIsInstance(app.screen, ToolMenuScreen)
        await pilot.press("down", "enter")  # second tool in the menu
        await pilot.pause()

    async def open_review(self, app, pilot):
        await self.open_tool(app, pilot)
        self.assertIsInstance(app.screen, FlavorScreen)
        await pilot.press("enter")  # "All flavors" is highlighted by default
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        self.assertIsInstance(app.screen, ShotReviewScreen)
        return app.screen

    async def run_action(self, app, pilot, key, answer="y"):
        await pilot.press(key)
        await pilot.pause()
        self.assertIsInstance(app.screen, ConfirmScreen)
        await pilot.press(answer)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def test_first_open_asks_for_settings(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            self.assertIsInstance(app.screen, ScreenshotSettingsScreen)
            app.screen.query_one("#dest_dir", Input).value = str(self.dest)
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
        self.assertEqual(load_settings(Config(self.config_dir / "screenshots.cfg").load()).dest_dir, self.dest)

    async def test_settings_refuse_destination_inside_screenshots(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            app.screen.query_one("#dest_dir", Input).value = str(self.shots / "sorted")
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, ScreenshotSettingsScreen)
            self.assertIn("Screenshots", app.screen.error_text)
            app.screen.query_one("#dest_dir", Input).value = ""
            app.screen.query_one("#keep_journals", Input).value = "0"
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, ScreenshotSettingsScreen)
            self.assertIn("at least 1", app.screen.error_text)
        self.assertFalse((self.config_dir / "screenshots.cfg").exists())

    async def test_all_flavors_organize_then_undo(self):
        self.save_tool_cfg(dest_dir=str(self.dest))
        app = self.make_app()
        with capture_events() as records:
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                self.assertEqual(len(review.plan.selectable), 6)
                self.assertTrue(review.query_one("#btn-undo", Button).disabled)
                await self.run_action(app, pilot, "o")
                self.assertIsInstance(app.screen, ShotResultScreen)
                self.assertEqual(app.screen.result.count("moved"), 6)
                self.assertEqual(app.screen.query_one("#result-files", DataTable).row_count, 6)
                await pilot.press("r")  # back to the review: rescans
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()
                self.assertIsInstance(app.screen, ShotReviewScreen)
                self.assertTrue(app.screen.query_one("#btn-organize", Button).disabled)
                self.assertIn("Nothing to file.", app.screen.summary_text)
                self.assertFalse(app.screen.query_one("#btn-undo", Button).disabled)
                await self.run_action(app, pilot, "z")
                self.assertIsInstance(app.screen, ShotResultScreen)
                self.assertTrue(app.screen.result.undo)
        self.assertTrue((self.shots / A).exists())
        self.assertIsNone(latest_undoable(self.root / "wow-tools" / "screenshots" / "journal"))
        names = [r["event"] for r in records]
        self.assertIn("shots.moved", names)
        self.assertIn("shots.undo_completed", names)

    async def test_undo_confirm_no_changes_nothing(self):
        self.save_tool_cfg(dest_dir=str(self.dest))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.run_action(app, pilot, "o")
            await pilot.press("r")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await self.run_action(app, pilot, "z", answer="n")
            self.assertIsInstance(app.screen, ShotReviewScreen)
        self.assertFalse((self.shots / A).exists())
        self.assertIsNotNone(latest_undoable(self.root / "wow-tools" / "screenshots" / "journal"))

    async def test_dry_run_changes_nothing(self):
        self.save_tool_cfg(dest_dir=str(self.dest))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.run_action(app, pilot, "y")
            self.assertTrue(app.screen.result.dry_run)
            self.assertEqual(app.screen.result.count("would_move"), 6)
        self.assertFalse(self.dest.exists())
        self.assertTrue((self.shots / A).exists())

    async def test_unticking_a_day_excludes_it(self):
        self.save_tool_cfg()  # in place
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#shots", Tree)
            day = next(n for n in _walk(tree.root) if n.data and n.data[0] == "day"
                       and n.data[2].isoformat() == "2019-07-31")
            tree.focus()
            tree.move_cursor(day)
            await pilot.press("space")
            await pilot.pause()
            self.assertEqual(len(review.selection()), 4)
            self.assertIn("Selected: 4 shots", review.summary_text)
            await self.run_action(app, pilot, "o")
        self.assertTrue((self.shots / A).exists())
        self.assertTrue((self.shots / "2019" / "08" / "01" / "WoWScrnShot_080119_101010.PNG").exists())

    async def test_day_nodes_load_files_and_skipped_node(self):
        self.save_tool_cfg()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#shots", Tree)
            day = next(n for n in _walk(tree.root) if n.data and n.data[0] == "day"
                       and n.data[2].isoformat() == "2019-07-31")
            self.assertEqual(len(day.children), 0)
            day.expand()
            await pilot.pause()
            self.assertEqual(sorted(c.data[1].src.name for c in day.children),
                             ["WoWScrnShot_073119_232713.jpg", "WoWScrnShot_073119_232800.jpg"])
            skipped = [n for n in _walk(tree.root) if n.data and n.data[0] == "skipped"]
            self.assertEqual(len(skipped), 1)  # _retail_ only: bad date + notes.txt
            self.assertIn("Skipped (2)", str(skipped[0].label))
            tree.focus()
            tree.move_cursor(skipped[0])
            await pilot.press("space")  # read-only: nothing changes
            await pilot.pause()
            self.assertEqual(len(review.selection()), 6)
            await pilot.press("n")
            await pilot.pause()
            self.assertEqual(review.selection(), [])
            await pilot.press("o")
            await pilot.pause()
            self.assertIsInstance(app.screen, ShotReviewScreen)  # "Nothing is selected."
            await pilot.press("a")
            await pilot.pause()
            self.assertEqual(len(review.selection()), 6)

    async def test_single_flavor_and_choice_remembered(self):
        self.save_tool_cfg()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            await pilot.press("down", "enter")  # first real flavor after "All flavors"
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            review = app.screen
            self.assertIsInstance(review, ShotReviewScreen)
            self.assertEqual(len(review.flavors), 1)
            await pilot.press("f")  # back to the flavor screen: the single flavor is highlighted
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
            self.assertEqual(app.screen.last, review.flavors[0].folder)
        saved = load_settings(Config(self.config_dir / "screenshots.cfg").load())
        self.assertEqual(saved.last_flavor_choice, review.flavors[0].folder)
        self.assertEqual(self.cfg.last_flavor, review.flavors[0].folder)

    async def test_tools_key_returns_to_menu(self):
        self.save_tool_cfg()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await pilot.press("t")
            await pilot.pause()
            self.assertIsInstance(app.screen, ToolMenuScreen)

    async def test_no_screenshots_folders_returns_to_menu(self):
        self.save_tool_cfg()
        for flavor in ("_retail_", "_classic_era_"):
            for path in sorted((self.root / flavor / "Screenshots").rglob("*"), reverse=True):
                path.rmdir() if path.is_dir() else path.unlink()
            (self.root / flavor / "Screenshots").rmdir()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            await pilot.pause()
            self.assertIsInstance(app.screen, ToolMenuScreen)


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)
