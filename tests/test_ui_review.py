"""The review screens' shared machinery in wowtools/ui/review.py (spec D9): the tick model of either polarity, and a
toy review screen driving Space, select all / none over the shown keys, buttons by id, the running-programs check,
the debounced rebuild, leaving and the scan box. The tools' own TUI tests drive the same code on real screens."""
from __future__ import annotations

import threading
import unittest
from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, ProgressBar, Static, Tree

from tests.fixtures import TuiTestCase, settle
from wowtools.core.events import capture_events
from wowtools.ui.dialogs import relabel_branch, tick_mark, two_pane_css
from wowtools.ui.review import NotTicked, ReviewBase, ReviewTree, TickModel
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, action_button

KEYS = ("a1", "a2", "b1")  # two groups: a (a1, a2) and b (b1)


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
                    yield action_button("Go", "apply", id="btn-go")
                    yield action_button("Other", "neutral", id="btn-other")
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

    def shown_tick_keys(self):
        return list(KEYS) if self.shown is None else self.shown

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
