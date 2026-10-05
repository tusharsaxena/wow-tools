"""The shared progress popup (ui/dialogs.py ProgressScreen) and the board it draws (core/progress.py ProgressBoard):
a box of one size from open to close, one row per running unit, rows reused as units finish, and reports from
worker threads that never wait for the UI thread."""
from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar

from textual.app import App
from textual.widgets import ProgressBar, Static
from textual.widgets._progress_bar import Bar

from tests.fixtures import BASE, TINY, TuiTestCase
from wowtools.core.install import Flavor
from wowtools.core.progress import ProgressBoard
from wowtools.tools.ace3_profile_manager.review_screen import ProfileProgressScreen
from wowtools.tools.interface_backup.review_screen import BackupProgressScreen
from wowtools.tools.screenshot_organizer.review_screen import ShotProgressScreen
from wowtools.tools.wtf_cleaner.review_screen import CleanProgressScreen
from wowtools.ui.dialogs import PROGRESS_LABEL_WIDTH, ProgressScreen

LONG = "Classic Era Experimental PTR (2/3): Checking the result against the WTF backup, " * 3
FLAVORS = ("Retail", "Classic", "Classic Era", "Retail PTR", "Classic Era PTR", "Retail Beta")


class Demo(ProgressScreen):
    ID_PREFIX = "demo"
    STAGE_TITLES: ClassVar[dict[str, str]] = {"work": "Working", "undo": "Undoing"}
    SIMULATED_STAGE = "work"


class Workers:
    """Named worker threads that live for the whole test, like a run's pool threads (a thread that ended can hand
    its ident to the next one, and the board tells workers apart by thread)."""

    def __init__(self, case: unittest.TestCase) -> None:
        self.pools: dict[str, ThreadPoolExecutor] = {}
        case.addCleanup(lambda: [pool.shutdown() for pool in self.pools.values()])

    def on(self, name: str, fn) -> None:
        self.pools.setdefault(name, ThreadPoolExecutor(1)).submit(fn).result(5)


class ProgressBoardTest(unittest.TestCase):
    def test_a_serial_run_reuses_its_one_row_and_counts_finished_units(self):
        board = ProgressBoard(1, 3)
        board.start("Retail", 0, 3)
        board.report("backup", 5, 10, "a.lua")
        _, view = board.snapshot()
        self.assertEqual((view.rows[0].label, view.rows[0].stage, view.rows[0].current), ("Retail", "backup", 5))
        self.assertEqual((view.done, view.units, view.detail, view.detail_label), (0, 3, "a.lua", "Retail"))
        board.start("Classic", 1, 3)  # the same thread starting the next unit ends the one before
        board.report("verify", 1, 2)
        _, view = board.snapshot()
        self.assertEqual((view.rows[0].label, view.rows[0].stage, view.done), ("Classic", "verify", 1))
        self.assertEqual(view.detail, "a.lua")  # a report without a detail keeps the last one
        board.finish()
        _, view = board.snapshot()
        self.assertTrue(view.rows[0].finished)
        self.assertEqual(view.done, 2)

    def test_rows_are_reused_as_units_finish(self):
        board = ProgressBoard(2, 4, label=str.upper)
        workers = Workers(self)
        workers.on("1", lambda: board.report_unit("a", "zip", 1, 4))
        workers.on("2", lambda: board.report_unit("b", "zip", 2, 4))
        _, view = board.snapshot()
        self.assertEqual([r.label for r in view.rows], ["A", "B"])
        board.finish("b")
        board.finish("a")
        workers.on("2", lambda: board.start("c"))  # b finished first: its row goes first
        workers.on("1", lambda: board.start("d"))
        _, view = board.snapshot()
        self.assertEqual([r.label for r in view.rows], ["D", "C"])
        self.assertEqual(view.done, 2)

    def test_parallel_units_keep_their_own_rows(self):
        board = ProgressBoard(4, 4)
        barrier = threading.Barrier(4)

        def unit(name: str) -> None:
            board.start(name)
            barrier.wait(5)
            for i in range(200):
                board.report("zip", i + 1, 200, f"{name}/{i}")
            board.finish()

        threads = [threading.Thread(target=unit, args=(n,)) for n in "abcd"]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        _, view = board.snapshot()
        self.assertEqual(sorted(r.label for r in view.rows), list("abcd"))
        self.assertTrue(all(r.finished and r.current == 200 for r in view.rows))
        self.assertEqual((view.done, view.units), (4, 4))

    def test_the_placeholder_holds_the_first_stage_until_a_unit_starts(self):
        board = ProgressBoard(2, 2, first_stage="check")
        _, view = board.snapshot()
        self.assertEqual((view.rows[0].used, view.rows[0].stage, view.rows[0].label), (True, "check", ""))
        board.start("Retail")
        _, view = board.snapshot()
        self.assertEqual(view.rows[0].label, "Retail")
        self.assertFalse(view.rows[1].used)
        self.assertEqual(view.done, 0)  # the placeholder is replaced, not counted

    def test_a_thread_starting_a_unit_finishes_its_previous_one(self):
        board = ProgressBoard(2, 3)
        workers = Workers(self)
        workers.on("1", lambda: board.report_unit("a", "zip", 1, 4))
        workers.on("2", lambda: board.report_unit("b", "zip", 1, 4))
        workers.on("1", lambda: board.report_unit("c", "zip", 1, 4))
        _, view = board.snapshot()
        self.assertEqual(([r.label for r in view.rows], view.done), (["c", "b"], 1))

    def test_a_late_report_of_a_finished_unit_is_dropped(self):
        board = ProgressBoard(1, 2)
        board.report_unit("a", "zip", 1, 2)
        board.finish("a")
        version, _ = board.snapshot()
        board.report_unit("a", "zip", 2, 2)
        self.assertEqual(board.snapshot()[0], version)

    def test_untagged_reports_without_a_unit_go_to_one_unnamed_row(self):
        board = ProgressBoard()
        board.report("undo", 1, 0, "x")
        version, view = board.snapshot()
        self.assertEqual((view.rows[0].label, view.rows[0].stage, view.rows[0].total, view.units), ("", "undo", 0, 1))
        board.report("undo", 2, 0)
        self.assertGreater(board.snapshot()[0], version)


class Host(App):
    pass


class ProgressScreenTest(TuiTestCase):
    def test_stage_titles(self):
        self.assertEqual(Demo(first_stage="work").stage_title("work"), "Working")
        dry = Demo(dry_run=True, first_stage="work")
        self.assertEqual((dry.stage_title("work"), dry.stage_title("undo"), dry.stage_title("x")),
                         ("Simulating", "Undoing", "x"))

    def test_rows_are_min_of_parallelism_and_units(self):
        self.assertEqual(Demo().rows, 1)
        self.assertEqual(Demo(units=FLAVORS, parallelism=1).rows, 1)
        self.assertEqual(Demo(units=FLAVORS, parallelism=4).rows, 4)
        self.assertEqual(Demo(units=FLAVORS[:2], parallelism=4).rows, 2)
        self.assertEqual(Demo(units=("Retail Experimental PTR",)).label_width, PROGRESS_LABEL_WIDTH)
        self.assertEqual(Demo().label_width, 0)

    async def _box_regions(self, size, screen: Demo, feed) -> tuple:
        app = Host()
        async with app.run_test(size=size) as pilot:
            await app.push_screen(screen)
            await pilot.pause()
            box = screen.query_one("#demo-box")
            before = box.region
            heights = {w.id: w.region.height for w in screen.query(Static) if (w.id or "").startswith("demo-")}
            feed(screen)
            screen.refresh_progress()
            await pilot.pause()
            after = box.region
            self.assertEqual({w.id: w.region.height for w in screen.query(Static) if (w.id or "").startswith("demo-")}, heights)
            self.assertTrue(all(h <= 1 for h in heights.values()), heights)  # a hidden label column is 0
            self.assertEqual((heights["demo-title"], heights["demo-detail"]), (1, 1))
            rows = [screen.query_one(f"#demo-row-{i}") for i in range(screen.rows)]
            self.assertTrue(all(box.region.contains_region(r.region) for r in rows), [r.region for r in rows])
            detail = screen.query_one("#demo-detail").region
            self.assertTrue(box.region.contains_region(detail))
            return before, after, box.region, screen

    async def test_the_box_never_changes_size(self):
        def feed(screen: Demo) -> None:
            workers = Workers(self)
            for n in range(60):
                flavor = FLAVORS[n % len(FLAVORS)]
                workers.on(str(n % screen.rows), lambda f=flavor, n=n: screen.report_unit(
                    f, "work" if n % 2 else LONG, n, 0 if n % 3 else 60, LONG + str(n)))
                if n % 5 == 0:
                    screen.finish_unit(flavor)

        for size in (BASE, TINY):
            for parallelism in (1, 4, 8):
                with self.subTest(size=size, parallelism=parallelism):
                    screen = Demo(LONG, units=FLAVORS, parallelism=parallelism, first_stage="work")
                    before, after, region, _ = await self._box_regions(size, screen, feed)
                    self.assertEqual(before, after)
                    self.assertEqual(region.height, screen.box_height())
                    self.assertLessEqual(region.bottom, size[1])

    async def test_a_serial_run_without_units_has_the_same_box(self):
        def feed(screen: Demo) -> None:
            for n in range(30):
                screen.report(LONG if n % 2 else "undo", n, 30, LONG)

        for size in (BASE, TINY):
            with self.subTest(size=size):
                screen = Demo("Undoing the last run", first_stage="undo")
                before, after, _, screen = await self._box_regions(size, screen, feed)
                self.assertEqual(before, after)
                self.assertEqual(screen.rows, 1)

    async def test_four_rows_fit_at_tiny_and_bars_fill_their_row(self):
        app = Host()
        async with app.run_test(size=TINY) as pilot:
            screen = Demo("Backing up", units=FLAVORS, parallelism=4)
            await app.push_screen(screen)
            workers = Workers(self)
            for flavor in FLAVORS[:4]:
                workers.on(flavor, lambda f=flavor: screen.report_unit(f, "work", 3, 10, "Interface/AddOns/x.lua"))
            screen.refresh_progress()
            await pilot.pause()
            box = screen.query_one("#demo-box").region
            self.assertTrue(box.y >= 0 and box.bottom <= TINY[1], box)
            for i in range(4):
                label = screen.query_one(f"#demo-row-{i}-label", Static)
                self.assertEqual(str(label.render()), FLAVORS[i])
                bar = screen.query_one(f"#demo-row-{i}-bar", ProgressBar)
                self.assertEqual(bar.query_one(Bar).region.width, bar.region.width - 5)  # the bar, then "nn%"
                self.assertTrue(box.contains_region(bar.region))
            self.assertIn("Retail PTR: Interface/AddOns/x.lua", str(screen.query_one("#demo-detail", Static).render()))
            self.assertEqual(str(screen.query_one("#demo-overall-label", Static).render()), "0 of 6 game versions")
        app = Host()
        async with app.run_test(size=BASE) as pilot:  # Textual's Bar is 32 wide unless told to fill its row
            screen = Demo("Backing up", first_stage="work")
            await app.push_screen(screen)
            await pilot.pause()
            for bar_id in ("#demo-row-0-bar", "#demo-overall"):
                bar = screen.query_one(bar_id, ProgressBar)
                self.assertEqual(bar.query_one(Bar).region.width, bar.region.width - 5)

    async def test_rows_are_reused_as_units_finish(self):
        app = Host()
        async with app.run_test(size=BASE) as pilot:
            screen = Demo("Backing up", units=FLAVORS[:3], parallelism=2)
            await app.push_screen(screen)
            workers = Workers(self)
            workers.on("1", lambda: screen.report_unit("Retail", "work", 1, 2))
            workers.on("2", lambda: screen.report_unit("Classic", "work", 1, 2))
            screen.finish_unit("Retail")
            screen.refresh_progress()
            await pilot.pause()
            self.assertEqual(str(screen.query_one("#demo-row-0-stage", Static).render()), "Done")
            workers.on("1", lambda: screen.start_unit("Classic Era", 2, 3))
            screen.refresh_progress()
            await pilot.pause()
            labels = [str(screen.query_one(f"#demo-row-{i}-label", Static).render()) for i in range(2)]
            self.assertEqual(labels, ["Classic Era", "Classic"])
            self.assertEqual(str(screen.query_one("#demo-overall-label", Static).render()), "1 of 3 game versions")

    async def test_reports_from_threads_are_drawn_on_the_timer(self):
        app = Host()
        async with app.run_test(size=BASE) as pilot:
            screen = Demo("Undoing")
            await app.push_screen(screen)
            await pilot.pause()
            Workers(self).on("1", lambda: screen.report("undo", 1, 0, "a/b.lua"))  # no call_from_thread: never waits
            await pilot.pause(0.3)
            self.assertEqual(str(screen.query_one("#demo-row-0-stage", Static).render()), "Undoing")
            self.assertEqual(str(screen.query_one("#demo-detail", Static).render()), "a/b.lua")
            self.assertIsNone(screen.query_one("#demo-row-0-bar", ProgressBar).total)  # total 0: indeterminate

    async def test_every_tools_popup_is_the_shared_box(self):
        flavors = [Flavor(f"_{name}_", Path(name)) for name in ("retail", "classic", "classic_era")]
        makers = (lambda: CleanProgressScreen(False, flavors=flavors), lambda: CleanProgressScreen(True),
                  lambda: CleanProgressScreen(False, first_stage="undo"), ShotProgressScreen,
                  lambda: ShotProgressScreen(first_stage="undo"),
                  lambda: BackupProgressScreen("Backing up", "backup", [f.display_name for f in flavors]),
                  lambda: BackupProgressScreen("Undoing", "verify"),
                  lambda: ProfileProgressScreen("Applying", flavors=flavors),
                  lambda: ProfileProgressScreen("Undoing", first_stage="undo"))
        for size in (BASE, TINY):
            app = Host()
            async with app.run_test(size=size) as pilot:
                for make in makers:
                    screen = make()
                    with self.subTest(size=size, screen=type(screen).__name__, title=screen.title_text):
                        await app.push_screen(screen)
                        await pilot.pause()
                        box = screen.query_one(f"#{screen.ID_PREFIX}-box").region
                        self.assertEqual(screen.rows, 1)  # every tool's runs are serial for now
                        self.assertTrue(screen.title_text)
                        screen.report_unit(flavors[0], LONG, 1, 2, LONG)
                        screen.refresh_progress()
                        await pilot.pause()
                        self.assertEqual(screen.query_one(f"#{screen.ID_PREFIX}-box").region, box)
                        self.assertEqual(box.height, screen.box_height())
                        self.assertTrue(box.y >= 0 and box.bottom <= size[1], box)
                        screen.dismiss(None)
                        await pilot.pause()
