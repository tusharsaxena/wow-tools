"""The tree filter every tree screen shares (spec D7, D8): a "Filter" input in the left pane, `/` to reach it from
anywhere on the screen, a case-insensitive substring match on the labels of the screen's model (never on the tree's
nodes: children that load on expand must match too), and what select all / none and the summaries need from it.

The filter is a view. Typing re-filters through the screen's debounced rebuild; `a` / `n` act on the keys it shows
(the `filter_keys()` hook of `ui.review.TickActions`); ticks it hides stay as they are and still count, and
`hidden_ticked_note()` says how many. Esc in the input clears it and goes back to the tree, Enter goes back to the
tree keeping it, → at the end of the text goes to the tree as well; Space types a space (TickActions)."""
from __future__ import annotations

from collections.abc import Callable, Collection, Hashable, Iterable, Sequence
from typing import ClassVar, Generic, TypeVar

from textual.binding import Binding
from textual.widgets import Input

from wowtools.core.events import log_event
from wowtools.core.text import plural

__all__ = ["FILTER_BINDINGS", "FILTER_HINT", "FILTER_ID", "FILTER_PLACEHOLDER", "FilterInput", "ModelFilter",
           "TextFilter", "TreeFilter", "hidden_by_filter"]

FILTER_ID = "tree-filter"
FILTER_PLACEHOLDER = "Filter (/)"
FILTER_HINT = "/ filter · "  # a screen's hint names it right before TREE_HINT
# Every tree screen with a filter binds this (TreeFilter's action).
FILTER_BINDINGS = [Binding("slash", "focus_filter", "Filter", show=False)]

Node = TypeVar("Node")


def hidden_by_filter(count: int) -> str:
    """The line a summary and a run's confirm add while the filter hides ticked items ("" when it hides none)."""
    if count <= 0:
        return ""
    verb = "is" if count == 1 else "are"
    return f"{plural(count, 'selected item')} {verb} hidden by the filter"


class TextFilter:
    """The filter text and the match: case-insensitive, substring, surrounding blanks ignored. Empty matches
    everything."""

    def __init__(self, text: str = "") -> None:
        self.text = text

    @property
    def wanted(self) -> str:
        return self.text.strip().casefold()

    @property
    def active(self) -> bool:
        return bool(self.wanted)

    def matches(self, *texts: str) -> bool:
        """True when any of these labels holds the filter text (always, with no filter)."""
        wanted = self.wanted
        return not wanted or any(wanted in text.casefold() for text in texts)

    def path_matches(self, path: Iterable[str]) -> bool:
        """True when an item shows: its own label or one of its groups' (the path from the top) matches."""
        return self.matches(*path)


class ModelFilter(Generic[Node]):
    """Which nodes of a screen's model tree a filter keeps and opens, worked out on the model (children a tree
    loads on expand are matched as well). A node stays when its label matches, when a group above it matches (a
    matched group keeps everything in it) or when something below it matches. A node opens when it matches or
    something below it does, so every match shows. With no filter every node stays and none is opened by it.

    `children(node)` lists a node's children, `texts(node)` its own labels and `key(node)` its identity (the node
    itself by default; it must be hashable)."""

    def __init__(self, text_filter: TextFilter, roots: Iterable[Node], children: Callable[[Node], Iterable[Node]],
                 texts: Callable[[Node], Iterable[str]], key: Callable[[Node], Hashable] = lambda node: node) -> None:
        self.active = text_filter.active
        self.key = key
        self.shown: set[Hashable] = set()
        self.opened: set[Hashable] = set()
        if not self.active:
            return
        for root in roots:
            self._walk(text_filter, root, children, texts, inside_match=False)

    def _walk(self, text_filter: TextFilter, node: Node, children: Callable[[Node], Iterable[Node]],
              texts: Callable[[Node], Iterable[str]], *, inside_match: bool) -> bool:
        """Mark this node and those below it; True when it or something below it matches."""
        own = text_filter.matches(*texts(node))
        below = False
        for child in children(node):
            below = self._walk(text_filter, child, children, texts, inside_match=inside_match or own) or below
        node_key = self.key(node)
        if own or below or inside_match:
            self.shown.add(node_key)
        if own or below:
            self.opened.add(node_key)
        return own or below

    def shows(self, node: Node) -> bool:
        return not self.active or self.key(node) in self.shown

    def opens(self, node: Node) -> bool:
        """True when the filter opens this node (a screen opens it then, whatever the user had)."""
        return self.active and self.key(node) in self.opened


class FilterInput(Input):
    """The left pane's filter box (one row). Esc clears it and goes back to the tree; → at the end of the text
    goes to the tree too (Input's ← and → move the cursor otherwise)."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "clear_filter", "Clear filter", show=False)]

    def __init__(self, placeholder: str = FILTER_PLACEHOLDER, *, id: str = FILTER_ID) -> None:
        super().__init__(placeholder=placeholder, id=id, compact=True)

    def action_clear_filter(self) -> None:
        self.screen.clear_filter()

    def action_cursor_right(self, select: bool = False) -> None:
        if not select and self.selection.is_empty and self.cursor_at_end:
            self.screen.action_focus_tree()
            return
        super().action_cursor_right(select)


class TreeFilter:
    """Mixin for a tree screen with a `FilterInput` in its left pane (`FILTER_SELECTOR`), placed before the
    review mixins (`class X(TreeFilter, ReviewBase, Screen)`) so its `filter_keys()` is the one `a` / `n` use. Bind
    FILTER_BINDINGS, name FILTER_HINT in the hint.

    The screen supplies `filter_texts(key)`: the labels a tick key's item is matched on, its group's first (the
    flavor, the account, the addon, the file; a key shows when any of them holds the text), and builds its tree
    with `model_filter(...)` in `_rebuild()`. It may override `filter_changed()` (the default reschedules the
    rebuild) and, where the keys a node shows are not simply the matching items, `filter_keys()`. It relies on
    ReviewBase for the rest: TREE_SELECTOR, LOG_SCREEN, all_tick_keys(), tick_model(), _schedule_rebuild() and
    action_focus_tree()."""

    FILTER_SELECTOR: ClassVar[str] = f"#{FILTER_ID}"
    _text_filter: TextFilter | None = None

    @property
    def text_filter(self) -> TextFilter:
        if self._text_filter is None:
            self._text_filter = TextFilter()
        return self._text_filter

    @property
    def filtering(self) -> bool:
        return self.text_filter.active

    def filter_texts(self, key: Hashable) -> Sequence[str]:
        """The labels this tick key's item is matched on: its groups' and its own."""
        raise NotImplementedError

    def filter_keys(self, keys: Collection[Hashable]) -> Collection[Hashable]:
        """The keys the filter shows (all of them with no filter)."""
        if not self.filtering:
            return keys
        return [key for key in keys if self.text_filter.path_matches(self.filter_texts(key))]

    def model_filter(self, roots: Iterable[Node], children: Callable[[Node], Iterable[Node]],
                     texts: Callable[[Node], Iterable[str]],
                     key: Callable[[Node], Hashable] = lambda node: node) -> ModelFilter[Node]:
        """What the current filter keeps and opens of the screen's model (see ModelFilter)."""
        return ModelFilter(self.text_filter, roots, children, texts, key)

    def hidden_ticked_count(self) -> int:
        """How many ticked items the filter hides: they stay ticked and the run takes them."""
        if not self.filtering:
            return 0
        every = list(self.all_tick_keys())
        shown = set(self.filter_keys(every))
        return len(self.tick_model().ticked_among(k for k in every if k not in shown))

    def hidden_ticked_note(self) -> str:
        """"N selected items are hidden by the filter", or "" when it hides none: for the summary and confirms."""
        return hidden_by_filter(self.hidden_ticked_count())

    # --- the input -----------------------------------------------------------------------------
    def filter_changed(self) -> None:
        """The filter text changed: rebuild the tree (folded into one rebuild while the user types)."""
        self._schedule_rebuild()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != FILTER_ID:
            return
        event.stop()
        if event.value == self.text_filter.text:
            return
        self.text_filter.text = event.value
        self.filter_changed()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != FILTER_ID:
            return
        event.stop()
        log_event("ui.selection", screen=self.LOG_SCREEN, control="filter", value=self.text_filter.text.strip())
        self.action_focus_tree()

    def action_focus_filter(self) -> None:
        """`/`: to the filter box, from anywhere on the screen."""
        field = self.query_one(self.FILTER_SELECTOR, Input)
        if field.display and not field.disabled:
            field.focus()

    def clear_filter(self) -> None:
        """Esc in the filter box: empty it (the tree shows everything again) and go back to the tree."""
        field = self.query_one(self.FILTER_SELECTOR, Input)
        if field.value:
            log_event("ui.selection", screen=self.LOG_SCREEN, control="filter", value="")
            field.value = ""
        self.action_focus_tree()
