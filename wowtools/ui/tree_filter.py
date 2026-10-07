"""The tree filter every tree screen shares (spec D7, D8, D40): a "Filter" input in the left pane with a Filter button
beside it, `/` to reach it from anywhere on the screen but a text box, a case-insensitive substring match on the
labels of the screen's model (never on the tree's nodes: children that load on expand must match too), and what
select all / none and the summaries need from it.

The filter is a view, applied when it is submitted (spec D40): typing only changes the box; Enter in it or the
Filter button applies the text (one rebuild, then the tree has focus), and an empty box submitted shows everything.
A big tree is never rebuilt on each keystroke. `a` / `n` and Space on a group act on the keys the applied filter
shows (the `filter_keys()` hook of `ui.review.TickActions`); ticks it hides stay as they are and still count, and
`hidden_ticked_note()` says how many. Esc in the input clears it (and the filter) and goes back to the tree, → at
the end of the text goes to the tree as well (keeping the applied filter); Space types a space (TickActions).
`FilterBox` is the box alone (a read-only tree), `TreeFilter` adds the ticks."""
from __future__ import annotations

from collections.abc import Callable, Collection, Hashable, Iterable, Sequence
from typing import ClassVar, Generic, TypeVar

from rich.text import Text
from textual.actions import SkipAction
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, Input

from wowtools.core.events import log_event
from wowtools.core.text import plural
from wowtools.ui.dialogs import theme_colour, tick_mark
from wowtools.ui.widgets import action_button

__all__ = ["FILTER_BINDINGS", "FILTER_BUTTON_ID", "FILTER_HINT", "FILTER_ID", "FILTER_PLACEHOLDER", "NO_MATCH_TEXT",
           "FilterBar", "FilterBox", "FilterInput", "ModelFilter", "ModelNode", "TextFilter", "TreeFilter",
           "hidden_by_filter"]

FILTER_ID = "tree-filter"
FILTER_PLACEHOLDER = "Filter (/)"
NO_MATCH_TEXT = "Nothing matches the filter (Esc in the box clears it)"
FILTER_BUTTON_ID = "btn-filter"
# A screen's hint names it right before TREE_HINT: `/` reaches the box, the Filter button (or its key, Enter, shown on
# it) applies what was typed (spec D40).
FILTER_HINT = "/ filter, then Filter · "
# Every tree screen with a filter binds this (FilterBox's action). Priority, so `/` leaves another control that
# would take the key first (an integer box would ring the bell); the action skips it to a text box.
FILTER_BINDINGS = [Binding("slash", "focus_filter", "Filter", priority=True)]

Node = TypeVar("Node")


def hidden_by_filter(count: int, noun: str = "item", by: str = "the filter") -> str:
    """The line a summary and a run's confirm add while the filter hides ticked items ("" when it hides none).
    `noun` is what the screen's summary counts ("3 selected files are hidden by the filter"); `by` names what hides
    them where more than the filter can (Ace3's Show boxes and view)."""
    if count <= 0:
        return ""
    verb = "is" if count == 1 else "are"
    return f"{plural(count, 'selected ' + noun)} {verb} hidden by {by}"


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


class ModelNode:
    """A node of a screen's tree before it is built, for a screen whose model is not a tree already: its data (as
    the tree node gets it) and its children. ModelFilter works on these (key=id), then the screen adds only the
    nodes it keeps."""

    __slots__ = ("children", "data")

    def __init__(self, data, children: list[ModelNode] | None = None) -> None:
        self.data = data
        self.children: list[ModelNode] = children if children is not None else []


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


class FilterBar(Horizontal):
    """The filter's row in the left pane: the `FilterInput` and, beside it, the compact Filter button (spec D40,
    navigate, its key Enter shown on it). The button takes no focus, so the row keeps one focusable control (the
    box, where Enter is the button's key); a click on it applies the filter as Enter does. A screen yields this, not
    the input alone; `input_id` is the box's id (the screen's FILTER_SELECTOR finds it)."""

    DEFAULT_CSS = """
    FilterBar { height: 1; width: 100%; }
    FilterBar > FilterInput { width: 1fr; }
    FilterBar > Button { width: auto; min-width: 0; margin-left: 1; }
    """

    def __init__(self, *, input_id: str = FILTER_ID, placeholder: str = FILTER_PLACEHOLDER, **kwargs) -> None:
        super().__init__(**kwargs)
        self._input_id = input_id
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        yield FilterInput(self._placeholder, id=self._input_id)
        button = action_button("Filter", "navigate", "enter", id=FILTER_BUTTON_ID, compact=True)
        button.can_focus = False
        yield button

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == FILTER_BUTTON_ID:
            event.stop()
            self.screen.submit_filter()


class FilterBox:
    """Mixin for a tree screen with a `FilterBar` in its left pane (its box found by `FILTER_SELECTOR`): the box,
    `/`, Esc, Enter and the Filter button, the applied text and `model_filter(...)`. Enough for a read-only tree
    (IB's Restore); a screen with ticks takes `TreeFilter`, which adds what select all / none, Space and the
    summaries need. Bind FILTER_BINDINGS, name FILTER_HINT in the hint, build the tree with `model_filter(...)`.

    The screen supplies LOG_SCREEN (the `screen` of the filter's ui events), action_focus_tree() (`TwoPaneFocus`)
    and filter_changed() (rebuild the tree; `TreeFilter` schedules ReviewBase's rebuild)."""

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

    def model_filter(self, roots: Iterable[Node], children: Callable[[Node], Iterable[Node]],
                     texts: Callable[[Node], Iterable[str]],
                     key: Callable[[Node], Hashable] = lambda node: node) -> ModelFilter[Node]:
        """What the current filter keeps and opens of the screen's model (see ModelFilter)."""
        return ModelFilter(self.text_filter, roots, children, texts, key)

    def note_no_match(self, root) -> None:
        """Every screen calls this at the end of a build: when the filter leaves nothing under the tree's root, a
        dim line says so (NO_MATCH_TEXT) rather than an empty tree that reads as "nothing to do". It has no data,
        so no tick, relabel or expand touches it. Status rows (a flavor not scanned, scan warnings) are filtered on
        their names like every other row, so an empty root means nothing matched."""
        if self.filtering and not root.children:
            root.add_leaf(Text(NO_MATCH_TEXT, style="dim"))

    # --- the input -----------------------------------------------------------------------------
    def filter_input(self) -> Input:
        return self.query_one(self.FILTER_SELECTOR, Input)

    def filter_changed(self) -> None:
        """The applied filter text changed: rebuild the tree."""
        raise NotImplementedError

    def on_input_changed(self, event: Input.Changed) -> None:
        """Typing changes the box only (spec D40): nothing is filtered until the box is submitted."""
        if event.input is self.filter_input():
            event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input is not self.filter_input():
            return
        event.stop()
        self.submit_filter()

    def submit_filter(self) -> None:
        """Enter in the box or the Filter button: apply what the box holds (an empty box shows everything; the
        same text again rebuilds nothing), log it and go to the tree."""
        value = self.filter_input().value
        log_event("ui.selection", screen=self.LOG_SCREEN, control="filter", value=value.strip())
        self._apply_filter(value)

    def _apply_filter(self, value: str) -> None:
        """Make `value` the applied filter (rebuilding the tree when it changes) and go to the tree: once the rebuild
        has run as well, as a tree is not focusable while it shows that it is loading."""
        self.action_focus_tree()
        if value == self.text_filter.text:
            return
        self.text_filter.text = value
        self.filter_changed()
        self.call_after_refresh(self.action_focus_tree)

    def action_focus_filter(self) -> None:
        """`/` (a priority binding): to the filter box from anywhere on the screen, except from a text box, the
        filter's own included, where `/` is typed (an integer or number box cannot hold it, so `/` leaves it)."""
        focused = self.focused
        if isinstance(focused, Input) and focused.type == "text":
            raise SkipAction
        field = self.filter_input()
        if not field.display or field.disabled:
            raise SkipAction
        field.focus()

    def clear_filter(self) -> None:
        """Esc in the filter box: empty it and drop the applied filter (the tree shows everything again), whether or
        not what was typed had been submitted, and go back to the tree."""
        field = self.filter_input()
        if field.value or self.text_filter.text:
            log_event("ui.selection", screen=self.LOG_SCREEN, control="filter", value="")
            field.value = ""
        self._apply_filter("")


class TreeFilter(FilterBox):
    """`FilterBox` for a review screen with ticks, placed before the review mixins
    (`class X(TreeFilter, ReviewBase, Screen)`) so its `filter_keys()` is the one `a` / `n` and Space use: Space on
    a group or the root ticks only the keys the filter shows (`TickActions.action_toggle`), so `node_tick_keys()`
    need not narrow them itself.

    The screen supplies `filter_texts(key)`: the labels a tick key's item is matched on, its group's first (the
    flavor, the account, the addon, the file; a key shows when any of them holds the text), and `all_tick_keys()`:
    every key of the model, never the filtered tree's (TickActions' default reads the root node, which a filtered
    rebuild narrows, so the hidden ticks would never be counted: TreeFilter makes it abstract). It may override
    `filter_changed()` (the default reschedules the rebuild) and, where the keys a node shows are not simply the
    matching items, `filter_keys()`. It relies on ReviewBase for the rest: TREE_SELECTOR, LOG_SCREEN, tick_model(),
    _schedule_rebuild() and action_focus_tree(). HIDDEN_NOUN is what one tick key is in the screen's summary
    ("file", "shot", "flavor"), for hidden_ticked_note()."""

    HIDDEN_NOUN: ClassVar[str] = "item"

    def filter_texts(self, key: Hashable) -> Sequence[str]:
        """The labels this tick key's item is matched on: its groups' and its own."""
        raise NotImplementedError

    def all_tick_keys(self) -> Collection[Hashable]:
        """Every key of the screen's model, filtered or not (never worked out from the tree the filter built)."""
        raise NotImplementedError

    def filter_keys(self, keys: Collection[Hashable]) -> Collection[Hashable]:
        """The keys the filter shows (all of them with no filter)."""
        if not self.filtering:
            return keys
        return [key for key in keys if self.text_filter.path_matches(self.filter_texts(key))]

    def tree_narrowed(self) -> bool:
        """True when the tree may leave keys out: while the filter is set (a screen whose own controls narrow the
        tree too, Ace3's Show boxes, says so here)."""
        return self.filtering

    def hidden_ticked_keys(self) -> list[Hashable]:
        """The ticked keys the filter hides: they stay ticked and the run takes them."""
        if not self.tree_narrowed():
            return []
        every = list(self.all_tick_keys())
        shown = set(self.filter_keys(every))
        return list(self.tick_model().ticked_among(k for k in every if k not in shown))

    def shown_tick_mark(self, items: Iterable, key: Callable[[object], Hashable] | None = None) -> tuple[str, str]:
        """The tick mark of a node covering `items` (`key(item)` is its tick key; the item itself by default): over
        the items the filter shows only, so a group's mark says what Space on it would tick or untick. One rule for
        every tool's tree (the Ace3 builders only ever hold the shown keys); the ticks it hides are counted on the
        summary line instead (hidden_ticked_note). No mark when the filter shows none of them."""
        items = list(items)
        if self.filtering:
            keys = [item if key is None else key(item) for item in items]
            shown = set(self.filter_keys(keys))
            items = [item for item, k in zip(items, keys) if k in shown]
            if not items:
                return "  ", ""
        return tick_mark(items, self.tick_model().unticked, key, success=theme_colour(self.app, "success"))

    def hidden_cause(self, keys: Collection[Hashable]) -> str:
        """What hides these ticked keys, for the note: the filter (a screen whose own controls narrow the tree too
        names them)."""
        return "the filter"

    def hidden_ticked_note(self) -> str:
        """"N selected items are hidden by the filter", or "" when it hides none: for the summary and confirms."""
        keys = self.hidden_ticked_keys()
        return hidden_by_filter(len(keys), self.HIDDEN_NOUN, self.hidden_cause(keys))

    def filter_changed(self) -> None:
        """The applied filter changed: rebuild the tree (ReviewBase's scheduled rebuild shows that it runs)."""
        self._schedule_rebuild()
