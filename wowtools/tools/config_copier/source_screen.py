"""The Config Copier's source picker (config tools spec CC2, X2): the shared account › realm › character tree of the
chosen flavors (under each flavor's name when "All flavors" was chosen), one choice. Enter on a character, or Choose,
picks it; nothing is ticked. The left pane has the filter, Choose and Back. Dismisses with (flavor, character), BACK
(Esc, Back: the flavor picker) or TOOLS (t: the tool menu)."""
from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Header, Label, Static, Tree

from wowtools.core.events import log_event
from wowtools.core.install import Character, Flavor
from wowtools.core.text import plural
from wowtools.ui.branding import BottomBar
from wowtools.ui.character_tree import CharacterNode, character_filter_texts, populate_characters
from wowtools.ui.dialogs import ACCENT, TREE_BINDINGS, TREE_HINT, TwoPaneFocus, two_pane_css
from wowtools.ui.review import ButtonActions, ReviewTree
from wowtools.ui.tree_filter import FILTER_BINDINGS, FILTER_HINT, FilterBar, FilterBox
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

BACK = "__back__"
TOOLS = "__tools__"
NAV_HINT = "↑↓ move · ←→ panes · " + FILTER_HINT + TREE_HINT + "t tools"
EXPLAIN = "Pick the character to copy from. Its files are only read."


class SourceScreen(FilterBox, ButtonActions, TwoPaneFocus, Screen["tuple[Flavor, Character] | str | None"]):
    """One character of `flavors`, picked from the shared character tree."""

    TREE_SELECTOR = "#sources"
    LOG_SCREEN = "copier_source"
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {"btn-choose": "choose_highlighted", "btn-back": "back"}
    DEFAULT_CSS = two_pane_css("SourceScreen", "#sources", width=46) + """
    SourceScreen #explain { margin-top: 1; height: auto; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("enter", "choose_highlighted", "Choose", show=False),
        Binding("escape", "back", "Back", show=False),
        Binding("t", "tool_menu", "Tools"),
        *FILTER_BINDINGS,
        *TREE_BINDINGS,
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *NAV_BINDINGS,
    ]

    def __init__(self, flavors: list[Flavor], scope_label: str) -> None:
        super().__init__()
        self.flavors = list(flavors)
        self.scope_label = scope_label
        self.choices: list[tuple[Flavor, Character]] = []  # every character listed, in tree order

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Label("Source", classes="section")
                yield Static(EXPLAIN, id="explain")
                yield FilterBar()
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Choose", "confirm", "enter", id="btn-choose")
                    yield action_button("Back", "cancel", "escape", id="btn-back")
                yield NavHint(NAV_HINT)
            yield ReviewTree(Text(self.scope_label, style=ACCENT), id="sources")
        yield Static("", id="summary")
        yield BottomBar()

    def on_mount(self) -> None:
        self.sub_title = f"Config Copier · {self.scope_label} · choose the source"
        self._build()
        self.query_one("#sources", Tree).focus()

    def first_filter(self) -> Widget | None:
        return self.filter_input()

    # --- the tree --------------------------------------------------------------------------------
    def _shown(self, flavor: Flavor):
        if not self.filtering:
            return None
        return lambda c: self.text_filter.path_matches((flavor.display_name, *character_filter_texts(c)))

    def _build(self) -> None:
        tree = self.query_one("#sources", Tree)
        tree.clear()
        self.choices = []
        many = len(self.flavors) > 1
        for flavor in self.flavors:
            parent = tree.root.add(Text(flavor.display_name, style=ACCENT), data=("flavor", flavor.folder),
                                   expand=True) if many else tree.root
            populate_characters(parent, flavor, key=lambda c: str(c.path), label=lambda c: c.name,
                                shown=self._shown(flavor))
            self.choices += [(flavor, n.data.character) for n in _walk(parent)
                             if isinstance(n.data, CharacterNode) and n.data.kind == "character"]
            if many and not parent.children:
                parent.remove()
        self.note_no_match(tree.root)
        tree.root.expand()
        count = plural(len(self.choices), "character")
        self.query_one("#summary", Static).update(Text(f"{count} to choose from"))

    def filter_changed(self) -> None:
        self._build()

    # --- choosing ----------------------------------------------------------------------------------
    def _flavor_of(self, node) -> Flavor | None:
        while node is not None:
            if isinstance(node.data, tuple) and node.data and node.data[0] == "flavor":
                return next(f for f in self.flavors if f.folder == node.data[1])
            node = node.parent
        return self.flavors[0] if len(self.flavors) == 1 else None

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        self._choose_node(event.node, toggle=False)  # the tree opens or closes a group itself

    def action_choose_highlighted(self) -> None:
        self._choose_node(self.query_one("#sources", Tree).cursor_node)

    def _choose_node(self, node, *, toggle: bool = True) -> None:
        data = None if node is None else node.data
        if not isinstance(data, CharacterNode) or data.kind != "character" or data.character is None:
            if toggle and node is not None and node.allow_expand:
                node.toggle()
            return
        flavor = self._flavor_of(node)
        if flavor is not None:
            self.choose(flavor, data.character)

    def choose(self, flavor: Flavor, character: Character) -> None:
        log_event("ui.selection", screen=self.LOG_SCREEN, control="source",
                  value=f"{flavor.folder}/{character.account}/{character.label}")
        self.dismiss((flavor, character))

    def action_back(self) -> None:
        self.dismiss(BACK)

    def action_tool_menu(self) -> None:
        self.dismiss(TOOLS)


def _walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(list(current.children)))

