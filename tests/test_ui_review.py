"""The review screens' shared machinery in wowtools/ui/review.py (spec D9): the tick model of either polarity, and a
toy review screen driving Space, select all / none over the shown keys, buttons by id, the running-programs check,
the debounced rebuild, leaving and the scan box. The tools' own TUI tests drive the same code on real screens."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, ProgressBar, Static, Tree

from tests.fixtures import TuiTestCase, build_wow_tree, settle
from wowtools.core import activity
from wowtools.core.events import capture_events, register_events
from wowtools.core.sv_events import SvTool, sv_events
from wowtools.ui.dialogs import ProgressScreen, relabel_branch, tick_mark, two_pane_css
from wowtools.ui.review import NotTicked, ReviewBase, ReviewTree, RunActions, TickModel
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, action_button

KEYS = ("a1", "a2", "b1")  # two groups: a (a1, a2) and b (b1)
RUN_TOOL = SvTool("test-ui-run", "tur")
register_events(RUN_TOOL.name, sv_events(RUN_TOOL.prefix))


class TickModelTest(unittest.TestCase):
    def test_both_polarities_agree(self):
        for model in (TickModel.of_ticked(set()), TickModel.of_unchecked(set(KEYS))):
            with self.subTest(stores_ticked=model.stores_ticked):
                self.assertEqual(model.ticked_among(KEYS), [])
                model.tick(["a1", "a2"])
                self.assertEqual(model.ticked_among(KEYS), ["a1", "a2"])
                self.assertTrue(model.is_ticked("a1"))
                self.assertFalse(model.is_ticked("b1"))
                model.untick(["a2"])
                self.assertEqual(model.ticked_among(KEYS), ["a1"])

    def test_toggle_ticks_all_when_any_is_unticked(self):
        for model in (TickModel.of_ticked({"a1"}), TickModel.of_unchecked({"a2", "b1"})):
            with self.subTest(stores_ticked=model.stores_ticked):
                self.assertTrue(model.toggle(iter(["a1", "a2"])))  # a2 was unticked: both ticked now
                self.assertEqual(model.ticked_among(KEYS), ["a1", "a2"])
                self.assertFalse(model.toggle(["a1", "a2"]))  # all ticked: all unticked
                self.assertEqual(model.ticked_among(KEYS), [])

    def test_changes_the_set_in_place(self):
        ticked, unchecked = set(), set()
        TickModel.of_ticked(ticked).tick(["a1"])
        TickModel.of_unchecked(unchecked).untick(["a1"])
        self.assertEqual((ticked, unchecked), ({"a1"}, {"a1"}))

    def test_unticked_feeds_tick_mark(self):
        ticked = TickModel.of_ticked({"a1"})
        unchecked = TickModel.of_unchecked({"a2", "b1"})
        self.assertIsInstance(ticked.unticked, NotTicked)
        self.assertIs(unchecked.unticked, unchecked.keys)
        for model in (ticked, unchecked):
            self.assertEqual(tick_mark(["a1", "a2"], model.unticked)[0], "◩ ")
            self.assertEqual(tick_mark(["b1"], model.unticked)[1], "dim")
        self.assertEqual((len(NotTicked({"x"})), list(NotTicked({"x"})), "y" in NotTicked({"x"})), (0, [], True))


class ToyReview(ReviewBase, Screen[str]):
    """Groups a and b with their keys as leaves; ticks of either polarity; `shown` narrows select all / none."""

    TREE_SELECTOR = "#toy"
    LOG_SCREEN = "toy_review"
    DEFAULT_CSS = two_pane_css("ToyReview", "#toy")
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {"btn-go": "go"}
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        Binding("q", "leave('quit')", "Quit"),
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *NAV_BINDINGS,
    ]

    def __init__(self, *, stores_ticked: bool) -> None:
        super().__init__()
        self.keys: set[str] = set() if stores_ticked else set(KEYS)  # nothing ticked at first, either way
        self.stores_ticked = stores_ticked
        self.shown: list[str] | None = None  # None: every key
        self.frozen = False
        self.went = 0
        self.rebuilds: list[bool] = []
        self.can_rebuild = True
        self.checking_changes: list[bool] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Ka0sCheckbox("Box", False, id="box", compact=True)
                yield Input(id="filter", compact=True)
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Go", "overwrite", id="btn-go")
                    yield action_button("Other", "navigate", id="btn-other")
            with Vertical(id="scan-box"):
                yield ProgressBar(id="scan-progress", show_eta=False)
                yield Static("", id="scan-label")
            yield ReviewTree(Text("root"), id="toy")
        yield Static("", id="summary")

    def on_mount(self) -> None:
        self.show_scan_box(False)
        tree = self.query_one("#toy", Tree)
        tree.root.data = ("root",)
        for group in ("a", "b"):
            node = tree.root.add(group, data=("group", group), expand=True)
            for key in KEYS:
                if key.startswith(group):
                    node.add_leaf(key, data=("key", key))
        tree.root.expand()
        tree.focus()

    def first_filter(self):
        return self.query_one("#box")

    def tick_model(self) -> TickModel:
        return TickModel(self.keys, ticked=self.stores_ticked)

    def node_tick_keys(self, node):
        if node is None or node.data is None:
            return []
        kind = node.data[0]
        if kind == "root":
            return list(KEYS)
        return [k for k in KEYS if k.startswith(node.data[1])] if kind == "group" else [node.data[1]]

    def filter_keys(self, keys):
        return keys if self.shown is None else [k for k in keys if k in self.shown]

    def tick_log_key(self, node, keys) -> str:
        return ",".join(keys)

    def ticks_frozen(self) -> bool:
        return self.frozen

    def _refresh_labels(self, node=None) -> None:
        relabel_branch(self.query_one("#toy", Tree), node, lambda data: Text(str(data)))
        self._update_summary()

    def _update_summary(self) -> None:
        self.query_one("#summary", Static).update(Text(f"{len(self.ticked())} ticked"))

    def ticked(self) -> list[str]:
        return self.tick_model().ticked_among(KEYS)

    def action_go(self) -> None:
        self.went += 1

    def _checking_changed(self) -> None:
        self.checking_changes.append(self._checking)

    def _can_rebuild(self) -> bool:
        return self.can_rebuild

    def _rebuild(self) -> None:
        self.rebuilds.append(self.query_one("#toy", Tree).loading)


class Host(App):
    def __init__(self, screen: Screen) -> None:
        super().__init__()
        self.review = screen
        self.busy = False
        self.result = "unset"

    def on_mount(self) -> None:
        self.push_screen(self.review, self.done)

    def done(self, value) -> None:
        self.result = value


def summary(screen: Screen) -> str:
    return str(screen.query_one("#summary", Static).render())


class ReviewBaseTest(TuiTestCase):
    async def run_toy(self, stores_ticked: bool, test) -> None:
        app = Host(ToyReview(stores_ticked=stores_ticked))
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await test(app, app.review, pilot)

    async def test_space_ticks_the_node_in_either_polarity(self):
        for stores_ticked in (True, False):
            with self.subTest(stores_ticked=stores_ticked):
                async def test(app, review, pilot):
                    tree = review.query_one("#toy", Tree)
                    tree.move_cursor(tree.root.children[0])  # group a
                    with capture_events() as records:
                        await pilot.press("space")
                        self.assertEqual(review.ticked(), ["a1", "a2"])
                        await pilot.press("space")
                        self.assertEqual(review.ticked(), [])
                    toggles = [r["data"] for r in records if r["event"] == "ui.item_toggled"]
                    self.assertEqual([(t["screen"], t["key"], t["checked"]) for t in toggles],
                                     [("toy_review", "a1,a2", True), ("toy_review", "a1,a2", False)])
                    self.assertEqual(summary(review), "0 ticked")
                    review.frozen = True
                    await pilot.press("space")
                    self.assertEqual(review.ticked(), [])
                await self.run_toy(stores_ticked, test)

    async def test_space_on_a_control_presses_toggles_or_types(self):
        async def test(app, review, pilot):
            review.query_one("#btn-go", Button).focus()
            await pilot.press("space")
            await pilot.pause()
            self.assertEqual(review.went, 1)
            box = review.query_one("#box", Ka0sCheckbox)
            box.focus()
            await pilot.press("space")
            self.assertTrue(box.value)
            field = review.query_one("#filter", Input)
            field.focus()
            await pilot.press("a", "space", "b")
            self.assertEqual(field.value, "a b")  # typed, not ticked or selected
            self.assertEqual(review.ticked(), [])
        await self.run_toy(True, test)

    async def test_select_all_and_none_act_on_the_shown_keys_only(self):
        for stores_ticked in (True, False):
            with self.subTest(stores_ticked=stores_ticked):
                async def test(app, review, pilot):
                    with capture_events() as records:
                        await pilot.press("a")
                        self.assertEqual(review.ticked(), list(KEYS))
                        review.shown = ["a1", "b1"]  # a filter hides a2: its tick stays
                        await pilot.press("n")
                        self.assertEqual(review.ticked(), ["a2"])
                        await pilot.press("a")
                        self.assertEqual(review.ticked(), list(KEYS))
                        review.frozen = True
                        await pilot.press("n")
                        self.assertEqual(review.ticked(), list(KEYS))
                    controls = [r["data"]["control"] for r in records if r["event"] == "ui.selection"]
                    self.assertEqual(controls, ["select_all", "select_none", "select_all"])
                    self.assertEqual(summary(review), "3 ticked")
                await self.run_toy(stores_ticked, test)

    async def test_select_all_keys_can_leave_some_keys_alone(self):
        async def test(app, review, pilot):
            review.select_all_keys = lambda: ["a1"]
            await pilot.press("a")
            self.assertEqual(review.ticked(), ["a1"])
        await self.run_toy(False, test)

    async def test_buttons_dispatch_by_id(self):
        async def test(app, review, pilot):
            review.query_one("#btn-go", Button).press()
            review.query_one("#btn-other", Button).press()  # not in BUTTON_ACTIONS: nothing happens
            await pilot.pause()
            self.assertEqual(review.went, 1)
        await self.run_toy(True, test)

    async def test_left_on_the_tree_goes_to_the_left_pane(self):
        async def test(app, review, pilot):
            await pilot.press("left")
            self.assertEqual(review.focused.id, "box")
            await pilot.press("right")
            self.assertIs(review.focused, review.query_one("#toy", Tree))
        await self.run_toy(True, test)

    async def test_preflight_runs_in_a_worker_then_answers_on_the_ui_thread(self):
        async def test(app, review, pilot):
            release = threading.Event()
            self.addCleanup(release.set)
            answers = []

            def check():
                release.wait(5)
                return ["Wow.exe"]

            review.run_preflight(check, lambda running, extra: answers.append(
                (running, extra, threading.current_thread() is threading.main_thread())), extra=lambda: 42)
            await pilot.pause()
            self.assertTrue(review._checking)
            self.assertIn("Checking for running programs", summary(review))
            release.set()
            await settle(app, pilot)
            self.assertEqual(answers, [(["Wow.exe"], 42, True)])
            self.assertEqual(review.checking_changes, [True, False])
            self.assertEqual(summary(review), "0 ticked")  # the selection is back on the summary

            def fail():
                raise OSError("no PowerShell")

            review.run_preflight(fail, lambda running, extra: answers.append((running, extra)), extra=fail)
            await settle(app, pilot)
            self.assertEqual(answers[-1], (None, None))  # unknown, never a crash
        await self.run_toy(True, test)

    async def test_preflight_answer_is_dropped_once_the_screen_is_left(self):
        async def test(app, review, pilot):
            release = threading.Event()
            self.addCleanup(release.set)
            answers = []
            review.run_preflight(lambda: release.wait(5) and [], lambda running, extra: answers.append(running))
            await pilot.pause()
            app.push_screen(Screen())
            await pilot.pause()
            release.set()
            await settle(app, pilot)
            self.assertEqual(answers, [])
            self.assertFalse(review._checking)
        await self.run_toy(True, test)

    async def test_scheduled_rebuild_shows_the_indicator_and_runs_once(self):
        async def test(app, review, pilot):
            tree = review.query_one("#toy", Tree)
            review._schedule_rebuild()
            review._schedule_rebuild()  # folded into the first
            self.assertTrue(tree.loading)
            self.assertIn("Updating the list", summary(review))
            await settle(app, pilot)
            self.assertEqual(review.rebuilds, [True])
            self.assertFalse(tree.loading)
            self.assertFalse(review._rebuild_pending)
            review.can_rebuild = False
            review._schedule_rebuild()
            self.assertFalse(tree.loading)
            await settle(app, pilot)
            self.assertEqual(review.rebuilds, [True])
        await self.run_toy(True, test)

    async def test_leave_waits_for_a_run(self):
        async def test(app, review, pilot):
            app.busy = True
            await pilot.press("q")
            await pilot.pause()
            self.assertIs(app.screen, review)
            app.busy = False
            await pilot.press("q")
            await pilot.pause()
            self.assertEqual(app.result, "quit")
        await self.run_toy(True, test)

    async def test_scan_box_stands_in_for_the_tree(self):
        async def test(app, review, pilot):
            tree = review.query_one("#toy", Tree)
            review.show_scan_box(True, "Reading things")
            self.assertTrue(review._scanning)
            self.assertFalse(tree.display)
            self.assertTrue(review.query_one("#scan-progress", ProgressBar).display)
            self.assertIsNone(review.query_one("#scan-progress", ProgressBar).total)
            self.assertEqual(str(review.query_one("#scan-label", Static).render()), "Reading things")
            review._scan_progress(2, 5, "two of five")
            self.assertEqual(review.query_one("#scan-progress", ProgressBar).total, 5)
            self.assertEqual(str(review.query_one("#scan-label", Static).render()), "two of five")
            review._scan_progress(0, 0, "")
            self.assertIsNone(review.query_one("#scan-progress", ProgressBar).total)  # no total yet: it pulses
            review.show_scan_box(False)
            self.assertFalse(review._scanning)
            self.assertTrue(tree.display)
            self.assertFalse(review.query_one("#scan-box").display)
        await self.run_toy(True, test)


class ToyProgress(ProgressScreen):
    ID_PREFIX = "toy"
    finished = 0

    def finish_all(self) -> None:
        self.finished += 1
        super().finish_all()


class ToyCfg:
    def __init__(self, wow_path: Path | None) -> None:
        self.wow_path = wow_path


class ToyRunReview(RunActions, ToyReview):
    """ToyReview with the apply / undo / recover plumbing: records refreshes, stale marks and notifications."""

    SV_TOOL = RUN_TOOL

    def __init__(self, wow_path: Path | None = None, backup_dir: Path | None = None) -> None:
        super().__init__(stores_ticked=True)
        self.cfg = ToyCfg(wow_path)
        self.backup_dir = backup_dir
        self.refreshes = 0
        self.stale_marks = 0
        self.notes: list[tuple[str, str]] = []

    def run_backup_dir(self) -> Path | None:
        return self.backup_dir

    def _refresh_buttons(self) -> None:
        self.refreshes += 1

    def _mark_stale(self) -> None:
        self.stale_marks += 1

    def notify(self, message, *, title="", severity="information", timeout=None, markup=True) -> None:
        self.notes.append((str(message), severity))


class RunActionsTest(TuiTestCase):
    async def run_toy(self, test, review: ToyRunReview | None = None) -> None:
        app = Host(review or ToyRunReview())
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await test(app, app.review, pilot)

    async def test_a_run_opens_the_progress_works_in_a_worker_and_closes(self):
        async def test(app, review, pilot):
            release = threading.Event()
            self.addCleanup(release.set)
            seen, done = [], []

            def work():
                seen.append((activity.wait_idle(0), threading.current_thread() is threading.main_thread()))
                release.wait(5)
                return "result"

            progress = ToyProgress("Working")
            review.start_run(progress, work, lambda result: done.append((result, app.busy, app.screen)),
                             name="apply", failure="The run stopped unexpectedly", stale_on_crash=True)
            await pilot.pause()
            self.assertTrue(app.busy)
            self.assertIs(app.screen, progress)
            self.assertIs(review._progress_screen, progress)
            release.set()
            await settle(app, pilot)
            self.assertEqual(seen, [(False, False)])  # inside activity.running(), off the UI thread
            self.assertEqual(done, [("result", False, review)])  # the popup is closed before `done`
            self.assertIsNone(review._progress_screen)
            self.assertFalse(app.busy)
            self.assertEqual(review.notes, [])
            self.assertEqual(progress.finished, 1)  # finish_all: the board ends at m of m
        await self.run_toy(test)

    async def test_an_expected_error_is_its_message_and_leaves_the_scan(self):
        async def test(app, review, pilot):
            def work():
                raise ValueError("WoW is running")

            done = []
            with capture_events() as records:
                review.start_run(ToyProgress("Working"), work, done.append, name="undo",
                                 failure="Undo stopped unexpectedly", stale_on_crash=True, expected=(ValueError,))
                await settle(app, pilot)
            self.assertEqual(done, [])
            self.assertEqual(review.notes, [("WoW is running", "error")])
            self.assertEqual(review.stale_marks, 0)
            self.assertFalse(app.busy)
            self.assertIs(app.screen, review)
            errors = [r["data"] for r in records if r["event"] == "error"]
            self.assertEqual([(e["where"], e["type"]) for e in errors], [("tur.undo", "ValueError")])
        await self.run_toy(test)

    async def test_a_crash_is_shown_and_marks_the_scan_stale_when_asked(self):
        for stale in (True, False):
            with self.subTest(stale=stale):
                async def test(app, review, pilot, stale=stale):
                    def work():
                        raise RuntimeError("boom")

                    review.start_run(ToyProgress("Working"), work, lambda result: None, name="recover",
                                     failure="Putting the originals back stopped", stale_on_crash=stale,
                                     expected=(ValueError,))
                    await settle(app, pilot)
                    self.assertEqual(review.notes,
                                     [("Putting the originals back stopped: RuntimeError: boom", "error")])
                    self.assertEqual(review.stale_marks, int(stale))
                    self.assertFalse(app.busy)
                await self.run_toy(test)

    async def test_refused_while_running(self):
        async def test(app, review, pilot):
            alerts: list[str] = []
            with capture_events() as records:
                self.assertTrue(review._refused_while_running(["Wow.exe"], alerts))
            self.assertEqual([r["event"] for r in records], ["tur.wow_running"])
            self.assertEqual(records[0]["data"]["running"], ["Wow.exe"])
            self.assertIn("WoW is running (Wow.exe)", review.notes[0][0])
            self.assertEqual(alerts, [])
            self.assertFalse(review._refused_while_running([], alerts))
            self.assertEqual(alerts, [])
            self.assertFalse(review._refused_while_running(None, alerts))
            self.assertEqual(alerts, ["Could not check whether WoW is running; close it before you go on."])
        await self.run_toy(test)

    async def test_check_wow_answers_on_the_ui_thread(self):
        async def test(app, review, pilot):
            answers = []
            review._check_wow(lambda: ["Wow.exe"], answers.append)
            await settle(app, pilot)
            self.assertEqual(answers, [["Wow.exe"]])
        await self.run_toy(test)

    async def test_backup_dir_refused(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wow = build_wow_tree(Path(tmp.name) / "wow")
        for wow_path, backup_dir, refused in ((None, wow, False), (wow, None, False),
                                              (wow, Path(tmp.name) / "backups", False), (wow, wow, True)):
            with self.subTest(wow_path=wow_path, backup_dir=backup_dir):
                async def test(app, review, pilot, refused=refused):
                    self.assertEqual(review._backup_dir_refused(), refused)
                    self.assertEqual(len(review.notes), int(refused))
                    if refused:
                        self.assertIn("Fix the folder in settings (s).", review.notes[0][0])
                await self.run_toy(test, ToyRunReview(wow_path, backup_dir))
