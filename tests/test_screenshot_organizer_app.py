from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, DataTable, Input, OptionList, Tree

from tests.fixtures import (BASE, TINY, TuiTestCase, assert_fits_or_keeps_minimum, assert_siblings_distinct,
                            build_screenshot_tree, build_wow_tree, make_config, settle, submit_filter)
from wowtools.core import activity
from wowtools.core.config import Config
from wowtools.core.events import capture_events
from wowtools.core.text import plural
from wowtools.tools.screenshot_organizer import planner as planner_module
from wowtools.tools.screenshot_organizer import review_screen as review_module
from wowtools.tools.screenshot_organizer.app import ScreenshotSettingsScreen
from wowtools.tools.screenshot_organizer.journal import latest_undoable
from wowtools.tools.screenshot_organizer.report import CONFLICT_MINIMUMS, FILE_MINIMUMS
from wowtools.tools.screenshot_organizer.review_screen import ShotResultScreen, ShotReviewScreen
from wowtools.tools.screenshot_organizer.settings import load_settings
from wowtools.ui.dialogs import ConfirmScreen
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
        tool_cfg = Config(self.config_dir / "screenshot-organizer.cfg")
        for key, value in values.items():
            tool_cfg.set("screenshot_organizer", key, value, log=False)
        tool_cfg.save()

    def make_app(self):
        return WowToolsApp(self.cfg, config_dir=self.config_dir, check_updates=False, detect=list)

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
        await settle(app, pilot)
        self.assertIsInstance(app.screen, ShotReviewScreen)
        return app.screen

    async def run_action(self, app, pilot, key, answer="y"):
        await pilot.press(key)
        await pilot.pause()
        self.assertIsInstance(app.screen, ConfirmScreen)
        await pilot.press(answer)
        await pilot.pause()
        await settle(app, pilot)

    async def test_first_open_asks_for_settings(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            self.assertIsInstance(app.screen, ScreenshotSettingsScreen)
            app.screen.query_one("#dest_dir", Input).value = str(self.dest)
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
            await settle(app, pilot)  # let the new screen finish mounting: on slow Windows CI, leaving run_test
            # straight away raced the Header's title update (NoMatches: HeaderTitle)
        self.assertEqual(load_settings(Config(self.config_dir / "screenshot-organizer.cfg").load()).dest_dir, self.dest)

    async def test_settings_refuse_destination_inside_screenshots(self):
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            app.screen.query_one("#dest_dir", Input).value = str(self.shots / "sorted")
            app.screen.query_one("#save", Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, ScreenshotSettingsScreen)
            self.assertIn("Screenshots", app.screen.error_text)
        self.assertFalse((self.config_dir / "screenshot-organizer.cfg").exists())

    async def test_settings_have_no_retention_inputs(self):
        """Feedback round 1: journals to keep is global ([general], the `s` screen)."""
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            self.assertIsInstance(app.screen, ScreenshotSettingsScreen)
            for box in ("#keep_journals", "#keep-journals"):
                self.assertFalse(app.screen.query(box), box)

    async def test_rescan_refuses_invalid_stored_dest(self):
        self.save_tool_cfg(dest_dir=str(self.root / "_retail_" / "WTF" / "shots"))
        scans = []
        real_scan = review_module.scan
        app = self.make_app()
        try:
            review_module.scan = lambda *args, **kwargs: scans.append(args) or real_scan(*args, **kwargs)
            async with app.run_test(size=SIZE) as pilot:
                review = await self.open_review(app, pilot)
                self.assertIsNone(review.plan)
                self.assertTrue(any("Fix the folder in settings" in n.message for n in app._notifications))
                await pilot.press("o")
                await pilot.pause()
                self.assertIs(app.screen, review)
        finally:
            review_module.scan = real_scan
        self.assertEqual(scans, [])
        self.assertFalse((self.root / "_retail_" / "WTF" / "shots").exists())

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
                await settle(app, pilot)
                self.assertIsInstance(app.screen, ShotReviewScreen)
                self.assertTrue(app.screen.query_one("#btn-organize", Button).disabled)
                self.assertIn("Nothing to file.", app.screen.summary_text)
                self.assertFalse(app.screen.query_one("#btn-undo", Button).disabled)
                await self.run_action(app, pilot, "z")
                self.assertIsInstance(app.screen, ShotResultScreen)
                self.assertTrue(app.screen.result.undo)
        self.assertTrue((self.shots / A).exists())
        self.assertIsNone(latest_undoable(self.root / "wow-tools" / "screenshot-organizer" / "journal"))
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
            await settle(app, pilot)
            await self.run_action(app, pilot, "z", answer="n")
            self.assertIsInstance(app.screen, ShotReviewScreen)
        self.assertFalse((self.shots / A).exists())
        self.assertIsNotNone(latest_undoable(self.root / "wow-tools" / "screenshot-organizer" / "journal"))

    async def test_torn_multibyte_journal_still_opens_and_undoes(self):
        self.save_tool_cfg(dest_dir=str(self.dest))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.run_action(app, pilot, "o")
            journal = latest_undoable(self.root / "wow-tools" / "screenshot-organizer" / "journal")
            with journal.open("ab") as handle:
                handle.write(b'{"action": "moved", "src": "C:\\\\Jeux\\\\\xc3')
            await pilot.press("f")  # result screen -> another flavor: a fresh review screen reads the journal
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
            await pilot.press("enter")
            await pilot.pause()
            await settle(app, pilot)
            review = app.screen
            self.assertIsInstance(review, ShotReviewScreen)
            self.assertFalse(review.query_one("#btn-undo", Button).disabled)
            await pilot.press("z")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertRegex(app.screen.title_text, r"^Undo the run from \d{4}-\d\d-\d\d \d\d:\d\d\?$")
            self.assertIn("Put back 6 files?", app.screen.body_text)
            await pilot.press("y")
            await pilot.pause()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ShotResultScreen)
            self.assertTrue(app.screen.result.undo)
        self.assertTrue((self.shots / A).exists())

    async def test_undo_is_blocked_while_scanning(self):
        self.save_tool_cfg(dest_dir=str(self.dest))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.run_action(app, pilot, "o")
            await pilot.press("r")
            await pilot.pause()
            await settle(app, pilot)
            review = app.screen
            self.assertFalse(review.query_one("#btn-undo", Button).disabled)
            review.action_rescan()  # the scan result can only arrive once the event loop runs again
            self.assertTrue(review.query_one("#btn-undo", Button).disabled)
            review.action_undo()
            await pilot.pause()
            self.assertIs(app.screen, review)
            await settle(app, pilot)
            self.assertFalse(review.query_one("#btn-undo", Button).disabled)

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

    async def test_runs_happen_inside_activity_running(self):
        self.save_tool_cfg(dest_dir=str(self.dest))
        seen = []
        real = review_module.execute

        def execute(*args, **kwargs):
            seen.append(activity.wait_idle(0))
            return real(*args, **kwargs)

        review_module.execute = execute
        self.addCleanup(setattr, review_module, "execute", real)
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_review(app, pilot)
            await self.run_action(app, pilot, "y")
            self.assertTrue(app.screen.result.dry_run)
        self.assertEqual(seen, [False])
        self.assertTrue(activity.wait_idle(0))

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
            self.assertIn("Skipped  2 items", str(skipped[0].label))
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
            await settle(app, pilot)
            review = app.screen
            self.assertIsInstance(review, ShotReviewScreen)
            self.assertEqual(len(review.flavors), 1)
            await pilot.press("f")  # back to the flavor screen: the single flavor is highlighted
            await pilot.pause()
            self.assertIsInstance(app.screen, FlavorScreen)
            self.assertEqual(app.screen.last, review.flavors[0].folder)
        saved = load_settings(Config(self.config_dir / "screenshot-organizer.cfg").load())
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
            await settle(app, pilot)
            # Decided before the picker opens (opening and dismissing it at once raced its Header).
            self.assertIsInstance(app.screen, ToolMenuScreen)
            self.assertFalse(any(isinstance(s, FlavorScreen) for s in app.screen_stack))


    async def test_flavor_counts_fill_in_after_mount(self):
        """F-005: the picker opens at once; the waiting counts are filled in by a worker."""
        self.save_tool_cfg()
        release = threading.Event()
        self.addCleanup(release.set)
        real = planner_module.waiting_count
        threads = []

        def slow_count(flavor, *args, **kwargs):
            threads.append(threading.current_thread() is threading.main_thread())
            release.wait(5)
            return real(flavor, *args, **kwargs)

        app = self.make_app()
        with patch.object(planner_module, "waiting_count", slow_count):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_tool(app, pilot)
                picker = app.screen
                self.assertIsInstance(picker, FlavorScreen)
                options = picker.query_one("#flavors", OptionList)
                labels = [str(options.get_option_at_index(n).prompt) for n in range(options.option_count)]
                self.assertTrue(all("counting" in label for label in labels), labels)
                release.set()
                await settle(app, pilot)
                ids = [options.get_option_at_index(i).id for i in range(options.option_count)]
                labels = {i: str(options.get_option_at_index(n).prompt) for n, i in enumerate(ids)}
                self.assertIn("4 screenshots to file", labels["_retail_"])
                self.assertIn("6 screenshots to file", labels[ids[0]])
                self.assertEqual(options.highlighted, 0)
        self.assertTrue(threads)
        self.assertFalse(any(threads))

    async def test_flavor_counts_arrive_while_settings_cover_the_picker(self):
        self.save_tool_cfg()
        release = threading.Event()
        self.addCleanup(release.set)
        real = planner_module.waiting_count

        def slow_count(flavor, *args, **kwargs):
            release.wait(5)
            return real(flavor, *args, **kwargs)

        app = self.make_app()
        with patch.object(planner_module, "waiting_count", slow_count):
            async with app.run_test(size=SIZE) as pilot:
                await self.open_tool(app, pilot)
                picker = app.screen
                self.assertIsInstance(picker, FlavorScreen)
                await pilot.press("s")  # the WoW folder, then the tool's settings, cover the picker
                await pilot.pause()
                release.set()
                await settle(app, pilot)
                await pilot.press("escape")
                await settle(app, pilot)
                await pilot.press("escape")
                await settle(app, pilot)
                self.assertIs(app.screen, picker)
                options = picker.query_one("#flavors", OptionList)
                labels = [str(options.get_option_at_index(n).prompt) for n in range(options.option_count)]
                self.assertFalse(any("counting" in label for label in labels), labels)

    async def test_settings_labels_wrap_at_base(self):
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            await pilot.pause()
            screen = ScreenshotSettingsScreen(Config(self.config_dir / "screenshot-organizer.cfg"), None,
                                              source="settings")
            app.push_screen(screen)
            await pilot.pause()
            for label in screen.query("Label"):
                text = str(label.render())
                self.assertLessEqual(label.region.right, BASE[0], text)
                self.assertGreaterEqual(label.region.width * label.region.height, len(text), text)

    async def test_copy_mode_filed_copies_are_not_waiting(self):
        """F-027: copy mode in place: screenshots already copied are not counted, show as already filed and
        start unticked."""
        from wowtools.core.install import WowInstall
        from wowtools.tools.screenshot_organizer.organizer import execute
        from wowtools.tools.screenshot_organizer.planner import scan
        self.save_tool_cfg(copy_mode=True)
        install = WowInstall(self.root)
        plan = scan(install.flavors(), None, copy=True)
        execute(plan.selectable, dest_dir=None, copy=True, dry_run=False, journal_dir=None, keep_journals=10)
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            await settle(app, pilot)
            options = app.screen.query_one("#flavors", OptionList)
            ids = [options.get_option_at_index(i).id for i in range(options.option_count)]
            labels = {i: str(options.get_option_at_index(n).prompt) for n, i in enumerate(ids)}
            self.assertIn("nothing to file", labels["_retail_"])
            self.assertIn("nothing to file", labels[ids[0]])
            await pilot.press("enter")
            await pilot.pause()
            await settle(app, pilot)
            review = app.screen
            self.assertIsInstance(review, ShotReviewScreen)
            self.assertEqual(review.selection(), [])
            self.assertIn("Nothing to file", review.summary_text)
            self.assertIn("6 already filed", review.summary_text)
            tree = review.query_one("#shots", Tree)
            groups = [n for n in _walk(tree.root) if n.data and n.data[0] == "filed"]
            self.assertEqual(len(groups), 2)
            retail = next(g for g in groups if g.data[1].flavor.folder == "_retail_")
            self.assertIn("Already filed  4 items", str(retail.label))
            self.assertFalse([n for n in _walk(tree.root) if n.data and n.data[0] == "day"])
            tree.focus()
            tree.move_cursor(retail)
            await pilot.press("space")  # tickable by hand
            await pilot.pause()
            self.assertEqual(len(review.selection()), 4)
            await pilot.press("a")  # ticks everything to file; leaves the already-filed choice alone
            await pilot.pause()
            self.assertEqual(len(review.selection()), 4)
            await pilot.press("n")
            await pilot.pause()
            self.assertEqual(review.selection(), [])

    async def test_every_flavor_is_listed_and_empty_ones_are_marked(self):
        self.save_tool_cfg()
        (self.root / "_classic_beta_").mkdir()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            await self.open_tool(app, pilot)
            await settle(app, pilot)  # the counts come from a worker
            picker = app.screen
            self.assertIsInstance(picker, FlavorScreen)
            options = picker.query_one("#flavors", OptionList)
            ids = [options.get_option_at_index(i).id for i in range(options.option_count)]
            self.assertEqual(ids[1:], ["_anniversary_", "_classic_beta_", "_classic_era_", "_retail_"])
            labels = {i: str(options.get_option_at_index(n).prompt) for n, i in enumerate(ids)}
            self.assertIn("no Screenshots folder", labels["_anniversary_"])
            self.assertIn("4 screenshots to file", labels["_retail_"])
            self.assertIn("2 screenshots to file", labels["_classic_era_"])
            self.assertIn("6 screenshots to file", labels[ids[0]])
            self.assertIn("(4 flavors)", labels[ids[0]])
            # three aligned columns: every folder and every remark starts in the same place
            plain = [labels[i] for i in ids]
            self.assertEqual(len({p.index("(") for p in plain}), 1)
            remarks = [p.index(r) for p, r in zip(plain, ["6 screenshots", "no Screenshots", "no Screenshots",
                                                           "2 screenshots", "4 screenshots"])]
            self.assertEqual(len(set(remarks)), 1)
            await pilot.press("down", "enter")  # Anniversary: no Screenshots folder
            await pilot.pause()
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ShotReviewScreen)
            self.assertIn("Nothing to file (no Screenshots folder)", app.screen.summary_text)
            self.assertTrue(app.screen.query_one("#btn-organize", Button).disabled)


    async def test_tree_lists_every_chosen_flavor(self):
        self.save_tool_cfg()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)  # All flavors
            tree = review.query_one("#shots", Tree)
            flavors = {n.data[1].flavor.folder: str(n.label) for n in tree.root.children}
            self.assertEqual(sorted(flavors), ["_anniversary_", "_classic_era_", "_retail_"])
            self.assertIn("no Screenshots folder", flavors["_anniversary_"])
            self.assertIn("4 items", flavors["_retail_"])

    async def test_action_buttons_share_the_suite_colours(self):
        from tests.fixtures import action_kind
        self.save_tool_cfg()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            kinds = {i: action_kind(review.query_one(f"#{i}", Button))
                     for i in ("btn-organize", "btn-dry", "btn-rescan", "btn-undo")}
        self.assertEqual(kinds, {"btn-organize": "overwrite", "btn-dry": "simulate", "btn-rescan": "refresh",
                                 "btn-undo": "revert"})

    # --- the tree filter (spec D7/D8): it matches the plan (a day's files load on expand), a / n act on what it
    #     shows, hidden ticks stay and are said in the summary and the confirm; Esc clears it ----------------
    def shown_files(self, review) -> list[str]:
        return sorted(n.data[1].src.name for n in _walk(review.query_one("#shots", Tree).root)
                      if n.data and n.data[0] == "file")

    async def test_filter_narrows_and_keeps_hidden_ticks(self):
        self.save_tool_cfg(dest_dir=str(self.dest))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            await pilot.press("slash")
            await pilot.pause()
            await pilot.press(*"2019-07", "enter")
            await settle(app, pilot)
            tree = review.query_one("#shots", Tree)
            days = [n for n in _walk(tree.root) if n.data and n.data[0] == "day"]
            self.assertEqual([n.data[2].isoformat() for n in days], ["2019-07-31"])
            self.assertTrue(days[0].is_expanded)  # it matches: open, its files loaded
            await settle(app, pilot)
            self.assertEqual(len(self.shown_files(review)), 2)
            self.assertEqual({n.data[1].flavor.display_name for n in tree.root.children}, {"Retail"})
            self.assertIs(review.focused, tree)  # Enter filtered and went back to the tree
            await pilot.press("n")
            self.assertEqual(len(review.selection()), 4)  # the two shown unticked, the hidden four kept
            self.assertIn("4 selected shots are hidden by the filter", review.summary_text)
            await pilot.press("y")
            await settle(app, pilot)
            self.assertIsInstance(app.screen, ConfirmScreen)
            self.assertIn("4 selected shots are hidden by the filter: they are simulated too.",
                          app.screen.body_text)
            app.screen.dismiss(False)
            await settle(app, pilot)
            await pilot.press("a")
            self.assertEqual(len(review.selection()), 6)
            await pilot.press("slash")
            await pilot.pause()
            await pilot.press("escape")
            await settle(app, pilot)
            self.assertIs(app.screen, review)
            self.assertGreater(len(tree.root.children), 1)  # every flavor again
            self.assertNotIn("hidden by the filter", review.summary_text)

    async def test_filter_on_a_file_name_opens_its_day(self):
        self.save_tool_cfg(dest_dir=str(self.dest))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            submit_filter(review, A[:-4].upper())
            await settle(app, pilot)
            self.assertEqual(self.shown_files(review), [A])
            self.assertEqual(review.filter_keys(review.all_tick_keys()), [self.shots / A])


    # --- leaf counts and columns (feedback round 2 R2 / R4, STD-7.27 / STD-7.28): the leaf is a screenshot the
    #     run can file (to file, or already filed); every node with children counts the ones below it the tree
    #     shows, a day before it is opened too; Conflicts and Skipped count their own rows; file and conflict rows
    #     are aligned columns fitted to the pane -------------------------------------------------------------
    def expected_count(self, review, data) -> int:
        """The leaves below a node, worked out from the plan (under the filter, those it shows)."""
        kind, plan = data[0], review.plan
        if kind == "root":
            items = plan.selectable
        elif kind == "flavor":
            items = data[1].selectable
        elif kind == "filed":
            items = data[1].filed
        else:
            fp = data[1]
            if kind == "day":
                items = [i for i in fp.to_file if i.day == data[2]]
            elif kind == "month":
                items = [i for i in fp.to_file if f"{i.day.year:04d}" == data[2] and f"{i.day.month:02d}" == data[3]]
            else:
                items = [i for i in fp.to_file if f"{i.day.year:04d}" == data[2]]
        shown = set(review.filter_keys([i.src for i in items]))
        return sum(1 for i in items if i.src in shown)

    def assert_counts(self, review) -> None:
        tree = review.query_one("#shots", Tree)
        for node in _walk(tree.root):
            kind = node.data[0] if node.data else None
            if kind not in ("root", "flavor", "year", "month", "day", "filed", "conflicts", "skipped"):
                continue
            if kind == "flavor" and not node.allow_expand:
                continue  # nothing under it: it says why instead (test_tree_lists_every_chosen_flavor)
            if kind in ("conflicts", "skipped"):  # read-only rows, no filter keys: the rows the tree shows below
                expected = len(node.children)
            else:
                expected = self.expected_count(review, node.data)
            count = plural(expected, "item")
            plain = str(node.label)
            with self.subTest(node=plain):
                self.assertIn(f"  {count}", plain)
                spans = {plain[s.start:s.end].strip(): str(s.style) for s in node.label.spans}
                self.assertEqual(spans.get(count), "dim", plain)
                self.assertNotRegex(plain, r"\d+ shots?|\(\d+\)")  # the old counts are gone

    async def test_every_node_counts_the_screenshots_below_it(self):
        self.save_tool_cfg()
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#shots", Tree)
            self.assertTrue(str(tree.root.label).endswith("  6 items"), str(tree.root.label))
            retail = next(n for n in tree.root.children if n.data[1].flavor.folder == "_retail_")
            self.assertTrue(str(retail.label).endswith("  4 items"), str(retail.label))
            day = next(n for n in _walk(tree.root) if n.data and n.data[0] == "day"
                       and n.data[2].isoformat() == "2019-07-31")
            self.assertEqual(len(day.children), 0)  # not opened yet: counted from the plan
            self.assertTrue(str(day.label).endswith("  2 items"), str(day.label))
            skipped = next(n for n in _walk(tree.root) if n.data and n.data[0] == "skipped")
            self.assertTrue(str(skipped.label).startswith("Skipped  2 items"), str(skipped.label))
            self.assert_counts(review)

    async def test_counts_follow_the_filter(self):
        self.save_tool_cfg(dest_dir=str(self.dest))
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            submit_filter(review, "2019-07")
            await settle(app, pilot)
            tree = review.query_one("#shots", Tree)
            self.assertTrue(str(tree.root.label).endswith("  2 items"), str(tree.root.label))
            self.assert_counts(review)
            submit_filter(review, A[:-4])
            await settle(app, pilot)
            self.assertTrue(str(tree.root.label).endswith("  1 item"), str(tree.root.label))
            self.assert_counts(review)

    async def test_conflict_and_skipped_counts_follow_the_filter(self):
        self.save_tool_cfg()  # in place
        target = self.shots / "2019" / "07" / "31"
        target.mkdir(parents=True)
        (target / A).write_bytes(b"another size")  # a conflict
        (self.shots / "2019" / "08" / "01").mkdir(parents=True)
        (self.shots / "2019" / "08" / "01" / "WoWScrnShot_080119_101010.PNG").write_bytes(b"other size")  # a conflict
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#shots", Tree)

            def group(kind):
                return next(n for n in _walk(tree.root) if n.data and n.data[0] == kind)

            self.assertTrue(str(group("conflicts").label).startswith("Conflicts  2 items"))
            self.assertTrue(str(group("skipped").label).startswith("Skipped  2 items"))
            submit_filter(review, "notes")  # 1 of the 2 skipped rows (notes.txt)
            await settle(app, pilot)
            skipped = group("skipped")
            self.assertEqual(len(skipped.children), 1)
            self.assertTrue(str(skipped.label).startswith("Skipped  1 item  "), str(skipped.label))
            self.assert_counts(review)
            submit_filter(review, "080119")  # 1 of the 2 conflict rows
            await settle(app, pilot)
            conflicts = group("conflicts")
            self.assertEqual(len(conflicts.children), 1)
            self.assertTrue(str(conflicts.label).startswith("Conflicts  1 item  "), str(conflicts.label))
            self.assert_counts(review)

    async def test_conflicts_and_duplicates_are_aligned_columns(self):
        self.save_tool_cfg()  # in place
        target = self.shots / "2019" / "07" / "31"
        target.mkdir(parents=True)
        (target / A).write_bytes(b"another size")  # a conflict
        (target / "WoWScrnShot_073119_232800.jpg").write_bytes(b"shot-b")  # same size: a possible duplicate
        (self.shots / "2019" / "08" / "01").mkdir(parents=True)
        (self.shots / "2019" / "08" / "01" / "WoWScrnShot_080119_101010.PNG").write_bytes(b"other size")  # a conflict
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#shots", Tree)
            conflicts = next(n for n in _walk(tree.root) if n.data and n.data[0] == "conflicts")
            self.assertTrue(str(conflicts.label).startswith("Conflicts  2 items"), str(conflicts.label))
            conflicts.expand()
            await settle(app, pilot)
            rows = list(conflicts.children)
            self.assertEqual(len(rows), 2)
            starts = {str(n.label).index("→") for n in rows}
            self.assertEqual(len(starts), 1, [str(n.label) for n in rows])  # the target column lines up
            for node in rows:
                plain = str(node.label)
                self.assertNotIn("  →", plain[:plain.index(node.data[1].src.name)])
            day = next(n for n in _walk(tree.root) if n.data and n.data[0] == "day"
                       and n.data[2].isoformat() == "2019-07-31")
            self.assertTrue(str(day.label).endswith("  1 item"), str(day.label))
            day.expand()
            await settle(app, pilot)
            (row,) = day.children
            plain = str(row.label)
            spans = {plain[s.start:s.end].strip(): str(s.style) for s in row.label.spans}
            self.assertEqual(spans.get("possible duplicate"), "dim", plain)
            self.assert_counts(review)

    async def test_rows_are_cut_to_fit_the_pane(self):
        """At 120x30 every file and conflict row fits the pane; at 80x24 a day's guides leave a file row 4 cells,
        so its name keeps its 12-cell minimum and the row scrolls sideways (STD-7.28, user decision U1: it read
        `✔ Wo…g` on every row before), and the files of a day still read apart."""
        self.save_tool_cfg()
        target = self.shots / "2019" / "07" / "31"
        target.mkdir(parents=True)
        (target / A).write_bytes(b"another size")  # a conflict: its target is a long path
        app = self.make_app()
        async with app.run_test(size=BASE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#shots", Tree)
            conflicts = next(n for n in _walk(tree.root) if n.data and n.data[0] == "conflicts")
            conflicts.expand()
            await pilot.press("x")  # every line open: the day files load
            await settle(app, pilot)
            for size in (BASE, TINY):
                await pilot.resize_terminal(*size)
                await settle(app, pilot)
                room = tree.size.width - tree.styles.scrollbar_size_vertical
                rows = [n for n in _walk(tree.root) if n.data and n.data[0] in ("file", "conflict")]
                self.assertTrue(any(n.data[0] == "file" for n in rows))
                for node in rows:
                    with self.subTest(size=size, row=str(node.label)):
                        if size == BASE:
                            self.assertLessEqual(_indent(node) + node.label.cell_len, room)
                        minimum = (FILE_MINIMUMS if node.data[0] == "file" else CONFLICT_MINIMUMS)[0]
                        assert_fits_or_keeps_minimum(self, node, _indent(node), room, node.data[1].src.name, minimum)
                assert_siblings_distinct(self, rows)
                (row,) = conflicts.children
                self.assertIn("…", str(row.label))
                if size == TINY:
                    files = [n for n in rows if n.data[0] == "file"]
                    self.assertNotIn("✔ Wo…g", [str(n.label) for n in files])
                    self.assertTrue(all(_indent(n) + n.label.cell_len > room for n in files))  # they scroll
                    continue  # 80 columns: a day's guides alone take most of the pane, so its row scrolls (G4d)
                for node in _walk(tree.root):  # a count is never pushed off by a note after it
                    if node.data and node.data[0] in ("day", "filed", "conflicts", "skipped"):
                        self.assertLessEqual(_indent(node) + str(node.label).index(" item") + 6, room, str(node.label))

    async def test_copy_mode_flavor_counts_its_filed_copies(self):
        from wowtools.core.install import WowInstall
        from wowtools.tools.screenshot_organizer.organizer import execute
        from wowtools.tools.screenshot_organizer.planner import scan
        self.save_tool_cfg(copy_mode=True)
        plan = scan(WowInstall(self.root).flavors(), None, copy=True)
        execute(plan.selectable, dest_dir=None, copy=True, dry_run=False, journal_dir=None, keep_journals=10)
        app = self.make_app()
        async with app.run_test(size=SIZE) as pilot:
            review = await self.open_review(app, pilot)
            tree = review.query_one("#shots", Tree)
            retail = next(n for n in tree.root.children if n.data[1].flavor.folder == "_retail_")
            self.assertTrue(str(retail.label).endswith("  4 items"), str(retail.label))
            self.assertTrue(str(retail.label).startswith("  "))  # nothing to file: no tick mark
            filed = next(n for n in retail.children if n.data[0] == "filed")
            self.assertTrue(str(filed.label).endswith("an identical copy is already in its date folder"))
            self.assert_counts(review)


def _indent(node) -> int:
    """The cells in front of a node's label: the tree guides, and the ▶ / ▼ of a node that opens."""
    depth, parent = 0, node.parent
    while parent is not None:
        depth, parent = depth + 1, parent.parent
    return depth * node.tree.guide_depth + (2 if node.allow_expand else 0)


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)
