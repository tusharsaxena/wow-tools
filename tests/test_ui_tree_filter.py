"""The shared tree filter in wowtools/ui/tree_filter.py (spec D7, D8): the match, what it keeps and opens of a model
whose children load on expand, the hidden-ticks line, and a toy review screen driving `/`, typing, Esc, Enter, →,
Space and select all / none under a filter. The tools' own TUI tests drive the same code on real screens."""
from __future__ import annotations

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
from wowtools.ui.dialogs import TREE_BINDINGS, TwoPaneFocus, relabel_branch, two_pane_css
from wowtools.ui.review import ReviewBase, ReviewTree, TickModel
from wowtools.ui.tree_filter import (FILTER_BINDINGS, FILTER_ID, FilterBox, FilterInput, ModelFilter, TextFilter,
                                     TreeFilter, hidden_by_filter)
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, Ka0sCheckbox, action_button

MODEL = {"Alpha": ["apple", "apricot"], "Beta": ["Banana", "cherry"]}
KEYS = [(group, item) for group, items in MODEL.items() for item in items]


def children(node):
    return [(node, item) for item in MODEL[node]] if isinstance(node, str) else []


def texts(node):
    return [node] if isinstance(node, str) else [node[1]]


class TextFilterTest(unittest.TestCase):
    def test_case_insensitive_substring_ignoring_blanks(self):
        text_filter = TextFilter("  AP ")
        self.assertTrue(text_filter.active)
        self.assertTrue(text_filter.matches("Apple"))
        self.assertTrue(text_filter.matches("x", "grAPe"))
        self.assertFalse(text_filter.matches("Banana", "cherry"))
        self.assertFalse(text_filter.path_matches(["Alpha", "x"]))
        self.assertTrue(text_filter.path_matches(["Alpha", "apple"]))

    def test_empty_filter_matches_everything(self):
        for text in ("", "   "):
            text_filter = TextFilter(text)
            self.assertFalse(text_filter.active)
            self.assertTrue(text_filter.matches("anything"))
            self.assertTrue(text_filter.matches())

    def test_unicode_case_folds(self):
        self.assertTrue(TextFilter("STRASSE").matches("Straße"))


class ModelFilterTest(unittest.TestCase):
    def model(self, text: str) -> ModelFilter:
        return ModelFilter(TextFilter(text), list(MODEL), children, texts)

    def test_a_match_keeps_its_groups_and_opens_them(self):
        kept = self.model("ban")
        self.assertEqual(kept.shown, {"Beta", ("Beta", "Banana")})
        self.assertEqual(kept.opened, {"Beta", ("Beta", "Banana")})
        self.assertTrue(kept.shows("Beta"))
        self.assertFalse(kept.shows("Alpha"))
        self.assertFalse(kept.shows(("Beta", "cherry")))
        self.assertTrue(kept.opens("Beta"))
        self.assertFalse(kept.opens("Alpha"))

    def test_a_matched_group_keeps_everything_in_it(self):
        kept = self.model("BETA")
        self.assertEqual(kept.shown, {"Beta", ("Beta", "Banana"), ("Beta", "cherry")})
        self.assertEqual(kept.opened, {"Beta"})  # the group opens; its items need not match

    def test_matches_in_several_groups(self):
        kept = self.model("a")  # every name holds an a except cherry, which Beta keeps
        self.assertEqual(kept.shown, {"Alpha", "Beta", *KEYS})
        self.assertNotIn(("Beta", "cherry"), kept.opened)

    def test_no_match_keeps_nothing(self):
        kept = self.model("zzz")
        self.assertEqual((kept.shown, kept.opened), (set(), set()))
        self.assertFalse(kept.shows("Alpha"))

    def test_no_filter_keeps_everything_and_opens_nothing(self):
        visited = []
        kept = ModelFilter(TextFilter(""), list(MODEL), lambda n: visited.append(n) or children(n), texts)
        self.assertEqual(visited, [])  # nothing to work out
        self.assertTrue(all(kept.shows(n) for n in [*MODEL, *KEYS]))
        self.assertFalse(any(kept.opens(n) for n in [*MODEL, *KEYS]))

    def test_key_gives_unhashable_nodes_an_identity(self):
        roots = [{"name": "Alpha", "items": [{"name": "apple"}]}]
        kept = ModelFilter(TextFilter("app"), roots, lambda n: n.get("items", []), lambda n: [n["name"]],
                           key=lambda n: n["name"])
        self.assertEqual(kept.shown, {"Alpha", "apple"})
        self.assertTrue(kept.shows(roots[0]))


class HiddenByFilterTest(unittest.TestCase):
    def test_wording(self):
        self.assertEqual(hidden_by_filter(0), "")
        self.assertEqual(hidden_by_filter(-1), "")
        self.assertEqual(hidden_by_filter(1), "1 selected item is hidden by the filter")
        self.assertEqual(hidden_by_filter(3), "3 selected items are hidden by the filter")
        self.assertEqual(hidden_by_filter(2, "file"), "2 selected files are hidden by the filter")  # HIDDEN_NOUN


class ToyFilterReview(TreeFilter, ReviewBase, Screen[str]):
    """Groups Alpha and Beta whose items load on expand; ticks of either polarity; a filter over the model."""

    TREE_SELECTOR = "#toy"
    LOG_SCREEN = "toy_review"
    DEFAULT_CSS = two_pane_css("ToyFilterReview", "#toy")
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {}
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        Binding("escape", "leave('flavors')", "Flavors", show=False),
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *FILTER_BINDINGS,
        *TREE_BINDINGS,
        *NAV_BINDINGS,
    ]

    def __init__(self, *, stores_ticked: bool) -> None:
        super().__init__()
        self.keys: set = set() if stores_ticked else set(KEYS)  # nothing ticked at first, either way
        self.stores_ticked = stores_ticked
        self.kept: ModelFilter | None = None
        self.rebuilt = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Ka0sCheckbox("Box", False, id="box", compact=True)
                yield FilterInput()
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Go", "overwrite", id="btn-go")
            with Vertical(id="scan-box"):
                yield ProgressBar(id="scan-progress", show_eta=False)
                yield Static("", id="scan-label")
            yield ReviewTree(Text("root"), id="toy")
        yield Static("", id="summary")

    def on_mount(self) -> None:
        self.show_scan_box(False)
        self._rebuild()
        self.query_one("#toy", Tree).focus()

    def first_filter(self):
        return self.query_one("#box")

    # --- the tree, built from the model through the filter; items load on expand ---------------
    def _rebuild(self) -> None:
        self.rebuilt += 1
        self.kept = self.model_filter(list(MODEL), children, texts)
        tree = self.query_one("#toy", Tree)
        tree.clear()
        tree.root.data = ("root",)
        for group in MODEL:
            if self.kept.shows(group):
                node = tree.root.add(group, data=("group", group))
                if self.kept.opens(group):
                    node.expand()
        tree.root.expand()
        self._update_summary()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        if node.data and node.data[0] == "group" and not node.children:
            for key in children(node.data[1]):
                if self.kept.shows(key):
                    node.add_leaf(key[1], data=("item", key))

    def shown_labels(self) -> list[str]:
        tree = self.query_one("#toy", Tree)
        out, stack = [], list(reversed(tree.root.children))
        while stack:
            node = stack.pop()
            out.append(str(node.label))
            stack.extend(reversed(node.children))
        return out

    # --- ticks ----------------------------------------------------------------------------------
    def tick_model(self) -> TickModel:
        return TickModel(self.keys, ticked=self.stores_ticked)

    def all_tick_keys(self):
        return list(KEYS)  # from the model: items not loaded yet count too

    def node_tick_keys(self, node):
        kind = node.data[0]
        if kind == "root":
            return list(KEYS)
        if kind == "group":  # every item: Space narrows a group's keys to what the filter shows (TickActions)
            return [k for k in KEYS if k[0] == node.data[1]]
        return [node.data[1]]

    def filter_texts(self, key):
        return key  # the group's name, then the item's

    def tick_log_key(self, node, keys) -> str:
        return str(node.data)

    def _refresh_labels(self, node=None) -> None:
        relabel_branch(self.query_one("#toy", Tree), node, lambda data: Text(str(data)))
        self._update_summary()

    def _update_summary(self) -> None:
        text = f"{len(self.ticked())} ticked"
        note = self.hidden_ticked_note()
        self.query_one("#summary", Static).update(Text(f"{text} · {note}" if note else text))

    def ticked(self) -> list:
        return self.tick_model().ticked_among(KEYS)


class SearchIdReview(ToyFilterReview):
    """The toy with its filter box under another id (the Ace3 review keeps `#search`)."""

    FILTER_SELECTOR = "#search"

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Ka0sCheckbox("Box", False, id="box", compact=True)
                yield Input(id="max-age", type="integer", compact=True)
                yield Input(id="note", compact=True)
                yield FilterInput(id="search")
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Go", "overwrite", id="btn-go")
            with Vertical(id="scan-box"):
                yield ProgressBar(id="scan-progress", show_eta=False)
                yield Static("", id="scan-label")
            yield ReviewTree(Text("root"), id="toy")
        yield Static("", id="summary")


class RootKeysReview(TreeFilter, ReviewBase):
    """A tick screen that forgot `all_tick_keys()` (TickActions' default would read the filtered tree's root)."""

    def node_tick_keys(self, node):
        return []


class ToyFilterView(FilterBox, TwoPaneFocus, Screen[str]):
    """A read-only tree (IB's Restore): the filter box without ticks, LOG_SCREEN, or ReviewBase."""

    TREE_SELECTOR = "#view"
    LOG_SCREEN = "toy_view"
    DEFAULT_CSS = two_pane_css("ToyFilterView", "#view")
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *FILTER_BINDINGS,
        *TREE_BINDINGS,
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield FilterInput()
            yield Tree(Text("root"), id="view")
        yield Static("", id="summary")

    def on_mount(self) -> None:
        self.filter_changed()
        self.query_one("#view", Tree).focus()

    def first_filter(self):
        return self.filter_input()

    def filter_changed(self) -> None:
        kept = self.model_filter(list(MODEL), children, texts)
        tree = self.query_one("#view", Tree)
        tree.clear()
        for group in MODEL:
            if kept.shows(group):
                node = tree.root.add(group, expand=True)
                for key in children(group):
                    if kept.shows(key):
                        node.add_leaf(key[1])
        tree.root.expand()

    def shown_labels(self) -> list[str]:
        tree = self.query_one("#view", Tree)
        return [str(n.label) for group in tree.root.children for n in (group, *group.children)]


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


class TreeFilterTest(TuiTestCase):
    async def run_toy(self, test, stores_ticked: bool = False, screen: type[Screen] = ToyFilterReview) -> None:
        app = Host(screen(stores_ticked=stores_ticked) if issubclass(screen, ToyFilterReview) else screen())
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await test(app, app.review, pilot)

    async def type_filter(self, app, review, pilot, text: str) -> None:
        await pilot.press("slash")
        await pilot.press(*(" " if ch == " " else ch for ch in text))
        await settle(app, pilot)

    async def test_slash_focuses_the_filter_from_anywhere(self):
        async def test(app, review, pilot):
            field = review.query_one(f"#{FILTER_ID}", Input)
            for start in ("#toy", "#box", "#btn-go"):
                review.query_one(start).focus()
                await pilot.pause()
                await pilot.press("slash")
                self.assertIs(review.focused, field, start)
            await pilot.press("slash")  # typed into the box once it has focus
            self.assertEqual(field.value, "/")
        await self.run_toy(test)

    async def test_typing_filters_the_model_and_opens_the_matches(self):
        async def test(app, review, pilot):
            self.assertEqual(review.shown_labels(), ["Alpha", "Beta"])  # closed: items not loaded yet
            await self.type_filter(app, review, pilot, "AP")
            self.assertEqual(review.shown_labels(), ["Alpha", "apple", "apricot"])
            self.assertIsInstance(review.focused, FilterInput)  # typing stays in the box
            field = review.query_one(f"#{FILTER_ID}", Input)
            field.value = "ban"
            await settle(app, pilot)
            self.assertEqual(review.shown_labels(), ["Beta", "Banana"])  # loaded on expand, still filtered
            field.value = "beta"
            await settle(app, pilot)
            self.assertEqual(review.shown_labels(), ["Beta", "Banana", "cherry"])  # a matched group keeps all
            field.value = "zzz"
            await settle(app, pilot)
            self.assertEqual(review.shown_labels(), [])
        await self.run_toy(test)

    async def test_typing_folds_into_one_rebuild(self):
        async def test(app, review, pilot):
            before = review.rebuilt
            field = review.query_one(f"#{FILTER_ID}", Input)
            field.focus()
            for value in ("a", "ap", "apr"):
                field.value = value
            await settle(app, pilot)
            self.assertEqual(review.rebuilt, before + 1)
            self.assertEqual(review.shown_labels(), ["Alpha", "apricot"])
        await self.run_toy(test)

    async def test_space_and_letters_type_into_the_filter(self):
        async def test(app, review, pilot):
            await self.type_filter(app, review, pilot, "an a")  # `a` and Space type, never select or tick
            field = review.query_one(f"#{FILTER_ID}", Input)
            self.assertEqual(field.value, "an a")
            self.assertEqual(review.ticked(), [])
            await pilot.press("n")
            self.assertEqual(field.value, "an an")
        await self.run_toy(test)

    async def test_select_all_and_none_act_on_what_the_filter_shows(self):
        for stores_ticked in (True, False):
            with self.subTest(stores_ticked=stores_ticked):
                async def test(app, review, pilot):
                    await pilot.press("a")  # no filter: everything
                    self.assertEqual(review.ticked(), KEYS)
                    self.assertEqual(review.hidden_ticked_count(), 0)
                    await self.type_filter(app, review, pilot, "ap")
                    await pilot.press("enter")
                    self.assertIs(review.focused, review.query_one("#toy", Tree))
                    await pilot.press("n")  # unticks apple and apricot only
                    self.assertEqual(review.ticked(), [("Beta", "Banana"), ("Beta", "cherry")])
                    self.assertEqual(review.hidden_ticked_count(), 2)  # hidden, still ticked, still counted
                    self.assertEqual(review.hidden_ticked_note(), "2 selected items are hidden by the filter")
                    self.assertEqual(summary(review), "2 ticked · 2 selected items are hidden by the filter")
                    await pilot.press("a")
                    self.assertEqual(review.ticked(), KEYS)
                    self.assertEqual(review.hidden_ticked_count(), 2)
                    await pilot.press("slash", "escape")  # cleared: nothing hidden
                    await settle(app, pilot)
                    self.assertEqual(review.hidden_ticked_count(), 0)
                    self.assertEqual(summary(review), "4 ticked")
                await self.run_toy(test, stores_ticked)

    async def test_space_on_a_group_ticks_only_what_the_filter_shows(self):
        async def test(app, review, pilot):
            await self.type_filter(app, review, pilot, "ban")
            await pilot.press("enter")
            tree = review.query_one("#toy", Tree)
            tree.move_cursor(tree.root.children[0])  # Beta, showing Banana only
            await pilot.press("space")
            self.assertEqual(review.ticked(), [("Beta", "Banana")])
        await self.run_toy(test, stores_ticked=True)

    async def test_escape_in_the_filter_clears_it_then_escape_on_the_tree_leaves(self):
        async def test(app, review, pilot):
            await self.type_filter(app, review, pilot, "ap")
            with capture_events() as records:
                await pilot.press("escape")
                await settle(app, pilot)
            field = review.query_one(f"#{FILTER_ID}", Input)
            self.assertEqual(field.value, "")
            self.assertFalse(review.filtering)
            self.assertIs(review.focused, review.query_one("#toy", Tree))
            self.assertIs(app.screen, review)  # the first Esc never leaves the review
            self.assertEqual(review.shown_labels(), ["Alpha", "Beta"])
            self.assertEqual([(r["data"]["control"], r["data"]["value"]) for r in records
                              if r["event"] == "ui.selection"], [("filter", "")])
            await pilot.press("slash", "escape")  # an empty box: back to the tree, nothing logged
            self.assertIs(review.focused, review.query_one("#toy", Tree))
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(app.result, "flavors")
        await self.run_toy(test)

    async def test_enter_keeps_the_filter_and_goes_to_the_tree(self):
        async def test(app, review, pilot):
            await self.type_filter(app, review, pilot, "cher")
            with capture_events() as records:
                await pilot.press("enter")
            self.assertIs(review.focused, review.query_one("#toy", Tree))
            self.assertEqual(review.shown_labels(), ["Beta", "cherry"])
            self.assertEqual([(r["data"]["screen"], r["data"]["control"], r["data"]["value"]) for r in records
                              if r["event"] == "ui.selection"], [("toy_review", "filter", "cher")])
        await self.run_toy(test)

    async def test_arrows_between_the_filter_and_the_tree(self):
        async def test(app, review, pilot):
            await self.type_filter(app, review, pilot, "ap")
            field = review.query_one(f"#{FILTER_ID}", Input)
            await pilot.press("left")  # moves the text cursor, stays in the box
            self.assertIs(review.focused, field)
            self.assertEqual(field.cursor_position, 1)
            await pilot.press("right")
            self.assertIs(review.focused, field)
            await pilot.press("right")  # at the end of the text: to the tree
            tree = review.query_one("#toy", Tree)
            self.assertIs(review.focused, tree)
            await pilot.press("left")  # ← on the tree: back to the box, the left pane's last control
            self.assertIs(review.focused, field)
            await pilot.press("down")  # one control per row: ↓ moves on to the buttons
            self.assertIsInstance(review.focused, Button)
        await self.run_toy(test)

    async def test_the_filter_is_one_row_in_the_left_pane(self):
        async def test(app, review, pilot):
            field = review.query_one(f"#{FILTER_ID}", Input)
            self.assertEqual(field.outer_size.height, 1)
            self.assertTrue(any(a.id == "filters" for a in field.ancestors))
            box = review.query_one("#box")
            self.assertNotEqual(field.region.y, box.region.y)
        await self.run_toy(test)

    async def test_slash_does_nothing_while_the_filter_is_hidden(self):
        async def test(app, review, pilot):
            review.query_one(f"#{FILTER_ID}", Input).display = False
            await pilot.press("slash")
            self.assertIs(review.focused, review.query_one("#toy", Tree))
        await self.run_toy(test)

    async def test_a_filter_box_under_another_id(self):
        async def test(app, review, pilot):
            await self.type_filter(app, review, pilot, "ban")
            field = review.query_one("#search", Input)
            self.assertIs(review.focused, field)
            self.assertEqual(review.text_filter.text, "ban")
            self.assertEqual(review.shown_labels(), ["Beta", "Banana"])
            with capture_events() as records:
                await pilot.press("enter")
            self.assertIs(review.focused, review.query_one("#toy", Tree))
            self.assertEqual([r["data"]["value"] for r in records if r["event"] == "ui.selection"], ["ban"])
            await pilot.press("slash", "escape")
            await settle(app, pilot)
            self.assertEqual((field.value, review.shown_labels()), ("", ["Alpha", "Beta"]))
        await self.run_toy(test, screen=SearchIdReview)

    async def test_slash_leaves_a_number_box_and_types_into_a_text_box(self):
        async def test(app, review, pilot):
            field = review.query_one("#search", Input)
            review.query_one("#max-age", Input).focus()
            await pilot.press("1", "slash")  # an integer box cannot hold `/`: to the filter
            self.assertIs(review.focused, field)
            self.assertEqual(review.query_one("#max-age", Input).value, "1")
            note = review.query_one("#note", Input)
            note.focus()
            await pilot.press("a", "slash")  # a text box keeps it
            self.assertIs(review.focused, note)
            self.assertEqual(note.value, "a/")
            self.assertEqual(field.value, "")
        await self.run_toy(test, screen=SearchIdReview)

    async def test_space_on_the_root_ticks_only_what_the_filter_shows(self):
        async def test(app, review, pilot):
            await self.type_filter(app, review, pilot, "ap")
            await pilot.press("enter")
            tree = review.query_one("#toy", Tree)
            tree.move_cursor(tree.root)
            await pilot.press("space")
            self.assertEqual(review.ticked(), [("Alpha", "apple"), ("Alpha", "apricot")])
        await self.run_toy(test, stores_ticked=False)

    async def test_a_read_only_tree_takes_the_filter_box_alone(self):
        async def test(app, view, pilot):
            await self.type_filter(app, view, pilot, "cher")
            self.assertEqual(view.shown_labels(), ["Beta", "cherry"])
            with capture_events() as records:
                await pilot.press("enter")
                await pilot.press("slash", "escape")
                await settle(app, pilot)
            self.assertIs(view.focused, view.query_one("#view", Tree))
            self.assertEqual(view.shown_labels(), ["Alpha", "apple", "apricot", "Beta", "Banana", "cherry"])
            self.assertEqual([(r["data"]["screen"], r["data"]["value"]) for r in records
                              if r["event"] == "ui.selection"], [("toy_view", "cher"), ("toy_view", "")])
        await self.run_toy(test, screen=ToyFilterView)


class AllTickKeysTest(unittest.TestCase):
    def test_a_tick_screen_must_list_its_model_keys(self):
        """TickActions' default all_tick_keys() reads the root of a tree the filter narrowed, so hidden ticks would
        never be counted: TreeFilter makes the screen list every key of its model."""
        with self.assertRaises(NotImplementedError):
            RootKeysReview().all_tick_keys()
