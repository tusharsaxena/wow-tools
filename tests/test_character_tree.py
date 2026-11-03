"""The shared character tree for tick screens (config tools spec X2, X3): wowtools/ui/character_tree.py, driven on a
toy review screen over a synthetic install (tests/fixtures.py build_character_tree), never a real one."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static, Tree

from tests.fixtures import TuiTestCase, build_character_tree
from wowtools.core.install import Character, WowInstall
from wowtools.ui.character_tree import (NO_CHARACTERS, CharacterNode, character_filter_texts, character_label,
                                        node_keys, populate_characters)
from wowtools.ui.dialogs import relabel_branch, tick_mark, two_pane_css
from wowtools.ui.review import ReviewBase, ReviewTree, TickModel
from wowtools.ui.tree_filter import FILTER_BINDINGS, FilterBar, TreeFilter
from wowtools.ui.widgets import NAV_BINDINGS


def char_key(c: Character) -> str:
    return f"{c.account}/{c.realm}/{c.name}"


class CharacterReview(ReviewBase, Screen[str]):
    """A tick screen whose tree is populate_characters' (nothing ticked at first)."""

    TREE_SELECTOR = "#chars"
    LOG_SCREEN = "character_tree_test"
    DEFAULT_CSS = two_pane_css("CharacterReview", "#chars")
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "toggle", "Tick/untick", priority=True),
        Binding("a", "select_all", "All"),
        Binding("n", "select_none", "None"),
        *NAV_BINDINGS,
    ]

    def __init__(self, flavor, **populate) -> None:
        super().__init__()
        self.flavor = flavor
        self.populate = populate
        self.ticked: set[str] = set()
        self.added: list[str] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Static("left")
            yield ReviewTree(Text("root"), id="chars")

    def on_mount(self) -> None:
        tree = self.query_one("#chars", Tree)
        self.added = populate_characters(tree.root, self.flavor, key=char_key, label=lambda c: c.name,
                                         mark=self.mark, **self.populate)
        tree.root.expand()
        tree.focus()

    def mark(self, keys) -> tuple[str, str]:
        return tick_mark(keys, self.tick_model().unticked)

    def tick_model(self) -> TickModel:
        return TickModel.of_ticked(self.ticked)

    def all_tick_keys(self):
        return list(self.added)

    def node_tick_keys(self, node):
        return node_keys(node)

    def tick_log_key(self, node, keys) -> str:
        return ",".join(keys)

    def _refresh_labels(self, node=None) -> None:
        relabel_branch(self.query_one("#chars", Tree), node,
                       lambda data: character_label(data, self.mark) if isinstance(data, CharacterNode)
                       else Text(str(data)))


class FilteredCharacterReview(TreeFilter, CharacterReview):
    """The same screen with the filter, as a tool's would be: a filtered rebuild through `shown=`, marks from
    `shown_tick_mark`, keys matched on `character_filter_texts`."""

    BINDINGS: ClassVar[list[Binding]] = [*CharacterReview.BINDINGS, *FILTER_BINDINGS]

    def __init__(self, flavor, **populate) -> None:
        super().__init__(flavor, **populate)
        self.characters = {char_key(c): c for a in flavor.accounts() for c in a.real_characters()}

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield FilterBar()
            yield ReviewTree(Text("root"), id="chars")
        yield Static(Text(""), id="summary")

    def on_mount(self) -> None:
        self._rebuild()
        self.query_one("#chars", Tree).focus()

    def _rebuild(self) -> None:
        tree = self.query_one("#chars", Tree)
        tree.clear()
        self.added = populate_characters(
            tree.root, self.flavor, key=char_key, label=lambda c: c.name, mark=self.mark,
            shown=lambda c: self.text_filter.path_matches(character_filter_texts(c)) if self.filtering else True)
        self.note_no_match(tree.root)
        tree.root.expand()

    def mark(self, keys) -> tuple[str, str]:
        return self.shown_tick_mark(keys)

    def all_tick_keys(self):
        return list(self.characters)

    def filter_texts(self, key):
        return character_filter_texts(self.characters[key])


class Host(App):
    def __init__(self, screen: Screen) -> None:
        super().__init__()
        self.review = screen

    def on_mount(self) -> None:
        self.push_screen(self.review)


def labels(node) -> list:
    """The tree under node as nested (label, children) pairs, children only where there are any."""
    out = []
    for child in node.children:
        text = child.label.plain
        out.append((text, labels(child)) if child.children else text)
    return out


class CharacterTreeTest(TuiTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = build_character_tree(Path(self._tmp.name))
        self.flavor = WowInstall(self.root).flavors()[0]

    async def run_screen(self, test, screen=CharacterReview, **populate) -> None:
        app = Host(screen(self.flavor, **populate))
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await test(app.review, app.review.query_one("#chars", Tree), pilot)

    def find(self, tree: Tree, *path: str):
        node = tree.root
        for part in path:
            node = next(c for c in node.children if isinstance(c.data, CharacterNode) and c.data.text == part)
        return node

    async def test_tree_lists_accounts_realms_characters_without_copies(self):
        async def test(review, tree, pilot):
            self.assertEqual(labels(tree.root), [
                ("✘ ALT", [("✘ Realm1", ["✘ Dænerys"])]),
                ("  BARE", [NO_CHARACTERS]),
                ("✘ MAIN", [("✘ Realm1", ["✘ Aellâ", "✘ Bob"]), ("✘ Realm2", ["✘ Trâxex"])]),
            ])
            self.assertEqual(review.added, ["ALT/Realm1/Dænerys", "MAIN/Realm1/Aellâ", "MAIN/Realm1/Bob",
                                            "MAIN/Realm2/Trâxex"])
            bob = self.find(tree, "MAIN", "Realm1", "Bob")
            self.assertEqual((bob.data.kind, bob.data.character.name, bob.data.keys), ("character", "Bob",
                                                                                        ("MAIN/Realm1/Bob",)))
            self.assertEqual(node_keys(self.find(tree, "MAIN")),
                             ("MAIN/Realm1/Aellâ", "MAIN/Realm1/Bob", "MAIN/Realm2/Trâxex"))
            self.assertEqual(node_keys(tree.root.children[1].children[0]), ())  # the "no characters" line
        await self.run_screen(test)

    async def test_ticking_realm_ticks_its_characters(self):
        async def test(review, tree, pilot):
            tree.move_cursor(self.find(tree, "MAIN", "Realm1"))
            await pilot.press("space")
            self.assertEqual(review.ticked, {"MAIN/Realm1/Aellâ", "MAIN/Realm1/Bob"})
            main = self.find(tree, "MAIN")
            self.assertEqual(labels(main), [("✔ Realm1", ["✔ Aellâ", "✔ Bob"]), ("✘ Realm2", ["✘ Trâxex"])])
            self.assertEqual(main.label.plain, "◩ MAIN")
            tree.move_cursor(main)
            await pilot.press("space")  # a part-ticked account ticks everything under it
            self.assertEqual(review.ticked, {"MAIN/Realm1/Aellâ", "MAIN/Realm1/Bob", "MAIN/Realm2/Trâxex"})
            await pilot.press("space")
            self.assertEqual(review.ticked, set())
            await pilot.press("a")
            self.assertEqual(review.ticked, set(review.added))
        await self.run_screen(test)

    async def test_disabled_character_has_no_tick_and_shows_reason(self):
        def disabled(c: Character) -> str | None:
            return "the source" if c.name == "Aellâ" else ("another flavor" if c.account == "ALT" else None)

        async def test(review, tree, pilot):
            aella = self.find(tree, "MAIN", "Realm1", "Aellâ")
            self.assertEqual(aella.label.plain, "  Aellâ  the source")
            self.assertEqual((aella.data.keys, aella.data.reason), ((), "the source"))
            self.assertIn("dim", str(aella.label.spans[0].style))
            self.assertNotIn("MAIN/Realm1/Aellâ", review.added)
            self.assertEqual(self.find(tree, "ALT").label.plain, "  ALT")  # nothing under it can be ticked
            self.assertEqual(self.find(tree, "ALT", "Realm1").label.plain, "  Realm1")
            tree.move_cursor(aella)
            await pilot.press("space")
            self.assertEqual(review.ticked, set())
            tree.move_cursor(self.find(tree, "MAIN"))
            await pilot.press("space")
            self.assertEqual(review.ticked, {"MAIN/Realm1/Bob", "MAIN/Realm2/Trâxex"})
            self.assertEqual(self.find(tree, "MAIN").label.plain, "✔ MAIN")
            tree.move_cursor(self.find(tree, "ALT"))
            await pilot.press("space")
            self.assertEqual(review.ticked, {"MAIN/Realm1/Bob", "MAIN/Realm2/Trâxex"})
        await self.run_screen(test, disabled=disabled)

    async def test_non_ascii_labels(self):
        async def test(review, tree, pilot):
            names = [n.data.character.name for n in tree.root.children[2].children[0].children]
            self.assertEqual(names, ["Aellâ", "Bob"])
            trax = self.find(tree, "MAIN", "Realm2", "Trâxex")
            self.assertEqual(trax.label.plain, "✘ Trâxex")
            self.assertEqual(trax.data.character.path.name, "Trâxex")
            self.assertTrue(trax.data.character.path.is_dir())
            self.assertEqual(character_filter_texts(trax.data.character), ("MAIN", "Realm2", "Trâxex"))
            self.assertEqual(self.find(tree, "ALT", "Realm1", "Dænerys").data.keys, ("ALT/Realm1/Dænerys",))
        await self.run_screen(test)

    async def test_account_extra_adds_under_the_account_first(self):
        def extra(account, node) -> None:
            node.add_leaf(f"{account.name} macros", data=("extra", account.name))

        async def test(review, tree, pilot):
            self.assertEqual(labels(tree.root), [
                ("✘ ALT", ["ALT macros", ("✘ Realm1", ["✘ Dænerys"])]),
                ("  BARE", ["BARE macros"]),  # an extra keeps an account with no characters
                ("✘ MAIN", ["MAIN macros", ("✘ Realm1", ["✘ Aellâ", "✘ Bob"]), ("✘ Realm2", ["✘ Trâxex"])]),
            ])
        await self.run_screen(test, account_extra=extra)

    async def test_shown_leaves_out_characters_and_empty_groups(self):
        async def test(review, tree, pilot):
            self.assertEqual(labels(tree.root), [("✘ MAIN", [("✘ Realm1", ["✘ Bob"])])])
            self.assertEqual(review.added, ["MAIN/Realm1/Bob"])
        await self.run_screen(test, shown=lambda c: c.name == "Bob")

    async def test_populates_under_any_parent_and_without_marks(self):
        async def test(review, tree, pilot):
            flavor_node = tree.root.add("Retail", data=("flavor", "_retail_"), expand=True)
            keys = populate_characters(flavor_node, self.flavor, key=char_key, label=lambda c: c.name.upper())
            self.assertEqual(keys, review.added)
            self.assertEqual(labels(flavor_node)[0], ("ALT", [("Realm1", ["DÆNERYS"])]))
            self.assertEqual(flavor_node.children[0].data.kind, "account")
        await self.run_screen(test)

    async def test_account_extra_keys_fold_into_the_account(self):
        def extra(account, node):
            node.add_leaf(f"{account.name} macros", data=("extra", account.name))
            return [f"{account.name}/macros"]

        async def test(review, tree, pilot):
            self.assertEqual(review.added[:2], ["ALT/macros", "ALT/Realm1/Dænerys"])
            self.assertEqual(node_keys(self.find(tree, "BARE")), ("BARE/macros",))
            self.assertEqual(self.find(tree, "BARE").label.plain, "✘ BARE")
            review.ticked.add("MAIN/macros")
            review._refresh_labels()
            self.assertEqual(self.find(tree, "MAIN").label.plain, "◩ MAIN")
            tree.move_cursor(self.find(tree, "ALT"))
            await pilot.press("space")
            self.assertEqual(review.ticked, {"MAIN/macros", "ALT/macros", "ALT/Realm1/Dænerys"})
        await self.run_screen(test, account_extra=extra)

    async def test_character_extra_hangs_nodes_under_a_character(self):
        def extra(character, node):
            if character.name == "Trâxex":
                return None  # nothing to add: the character stays a leaf
            node.add_leaf(f"{character.name} macro", data=("macro", character.name))
            return [f"{char_key(character)}/macro"]

        async def test(review, tree, pilot):
            bob = self.find(tree, "MAIN", "Realm1", "Bob")
            self.assertTrue(bob.allow_expand)
            self.assertFalse(bob.is_expanded)
            self.assertEqual([c.label.plain for c in bob.children], ["Bob macro"])
            self.assertEqual(bob.data.keys, ("MAIN/Realm1/Bob", "MAIN/Realm1/Bob/macro"))
            self.assertEqual(bob.label.plain, "✘ Bob")
            self.assertFalse(self.find(tree, "MAIN", "Realm2", "Trâxex").allow_expand)
            self.assertIn("MAIN/Realm1/Aellâ/macro", node_keys(self.find(tree, "MAIN")))
            self.assertIn("ALT/Realm1/Dænerys/macro", review.added)
            tree.move_cursor(self.find(tree, "MAIN", "Realm1"))
            await pilot.press("space")
            self.assertEqual(review.ticked, {"MAIN/Realm1/Aellâ", "MAIN/Realm1/Aellâ/macro", "MAIN/Realm1/Bob",
                                             "MAIN/Realm1/Bob/macro"})
            self.assertEqual(self.find(tree, "MAIN", "Realm1", "Bob").label.plain, "✔ Bob")
        await self.run_screen(test, character_extra=extra)

    async def test_disabled_character_keeps_extra_nodes_without_its_own_key(self):
        async def test(review, tree, pilot):
            aella = self.find(tree, "MAIN", "Realm1", "Aellâ")
            self.assertEqual(aella.data.keys, ("MAIN/Realm1/Aellâ/macro",))
            self.assertEqual(aella.label.plain, "✘ Aellâ  the source")
        await self.run_screen(test, disabled=lambda c: "the source" if c.name == "Aellâ" else None,
                              character_extra=lambda c, node: (node.add_leaf("m"), [f"{char_key(c)}/macro"])[1])

    async def test_filter_rebuilds_with_shown_and_ticks_only_what_it_shows(self):
        async def test(review, tree, pilot):
            review.ticked.add("MAIN/Realm1/Aellâ")  # a tick the filter will hide
            await pilot.press("slash", "b", "o", "b", "enter")
            await pilot.pause()
            tree = review.query_one("#chars", Tree)
            self.assertEqual(labels(tree.root), [("✘ MAIN", [("✘ Realm1", ["✘ Bob"])])])
            self.assertEqual(review.hidden_ticked_keys(), ["MAIN/Realm1/Aellâ"])
            tree.move_cursor(self.find(tree, "MAIN"))
            await pilot.press("space")
            self.assertEqual(review.ticked, {"MAIN/Realm1/Aellâ", "MAIN/Realm1/Bob"})
            self.assertEqual(self.find(tree, "MAIN").label.plain, "✔ MAIN")  # over the shown keys only
            await pilot.press("slash")
            review.filter_input().value = "realm2"  # matched on the realm too, case-insensitively
            await pilot.press("enter")
            await pilot.pause()
            tree = review.query_one("#chars", Tree)
            self.assertEqual(labels(tree.root), [("✘ MAIN", [("✘ Realm2", ["✘ Trâxex"])])])
            await pilot.press("n")  # select none: the shown keys only
            self.assertEqual(review.ticked, {"MAIN/Realm1/Aellâ", "MAIN/Realm1/Bob"})
            await pilot.press("slash", "escape")
            await pilot.pause()
            tree = review.query_one("#chars", Tree)
            self.assertEqual(self.find(tree, "MAIN").label.plain, "◩ MAIN")
            self.assertEqual(self.find(tree, "MAIN", "Realm1").label.plain, "✔ Realm1")
        await self.run_screen(test, screen=FilteredCharacterReview)

    async def test_filter_with_no_match_says_so(self):
        async def test(review, tree, pilot):
            await pilot.press("slash", *"nobody", "enter")
            await pilot.pause()
            tree = review.query_one("#chars", Tree)
            self.assertEqual(labels(tree.root), ["Nothing matches the filter (Esc in the box clears it)"])
        await self.run_screen(test, screen=FilteredCharacterReview)
