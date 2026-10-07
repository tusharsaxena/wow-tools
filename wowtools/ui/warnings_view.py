"""The warnings view every tool shares (spec W1, W2): what a scan could not read or skipped, on a screen of its own
instead of only in the log, which nobody reads.

- `SummaryLine`: the bottom line's text (#summary); `show_one_line` keeps a failed scan's message on one row
  (ellipsis), so a long error never moves the bars above it (STD-7.25); the next `update` wraps again.
- `SummaryBar`: a screen's bottom line (#summary, a `SummaryLine`) with the compact **Warnings** button at its right end, shown only
  while there are warnings ("⚠ 4 scan warnings (!)"): a click or its key, `!` (WARNINGS_KEY), opens the view. The
  button takes no focus (the bottom line is not a row of controls) and carries its key (spec D17), so the footer
  never lists it.
- `WarningsHost`: the mixin a screen showing warnings takes: `warning_items()` (what it collected), `refresh_warnings()`
  (call it where the screen updates its bottom line), `action_show_warnings()` (bind WARNINGS_BINDING).
- `WarningsScreen`: the view, in the two-pane look: a count, the `/` filter and Back (Esc) on the left; on the right
  a tree of the warnings, grouped by flavor where the tool knows it, each one's where (a path or a part) and what (the
  message the tool logged). x / c expand / collapse, h is the tool's help."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import Screen
from textual.widget import Widget
from textual.visual import VisualType
from textual.widgets import Button, Header, Static, Tree

from wowtools.core.events import log_event
from wowtools.core.paths import to_stored
from wowtools.core.text import plural
from wowtools.ui.branding import BottomBar
from wowtools.ui.dialogs import ACCENT, TREE_BINDINGS, TREE_HINT, TwoPaneFocus, theme_colour, two_pane_css
from wowtools.ui.review import ButtonActions, ReviewTree
from wowtools.ui.tree_filter import FILTER_BINDINGS, FILTER_HINT, FilterBar, FilterBox, ModelNode
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button, key_text

__all__ = ["WARNINGS_BINDING", "WARNINGS_BUTTON_ID", "WARNINGS_KEY", "SummaryBar", "WarningItem", "WarningsHost",
           "WarningsScreen", "scan_warning_items", "warnings_label", "where_text"]

WARNINGS_KEY = "exclamation_mark"  # `!`: free on every screen that shows warnings (a text box types it)
WARNINGS_BUTTON_ID = "btn-warnings"
# Not in the footer: the Warnings button carries the key while there are warnings, and without any it does nothing.
WARNINGS_BINDING = Binding(WARNINGS_KEY, "show_warnings", "Warnings", show=False)
WARNINGS_HINT = "↑↓/Tab move · ←→ panes · Space/Enter open · " + FILTER_HINT + TREE_HINT.removesuffix(" · ")


@dataclass(frozen=True)
class WarningItem:
    """One warning as the view lists it: where (a path, a part, a file; "" when there is none), what (the tool's own
    message, as logged) and the group it sits under (the flavor's name; "" for none)."""
    where: str
    what: str
    group: str = ""


def where_text(path: str | Path | None, base: Path | None = None) -> str:
    """A warning's where: the path inside `base` (the flavor's folder: the group names the flavor already) with
    forward slashes, else the whole path as the settings store it; "" for none."""
    if not path:
        return ""
    path = Path(path)
    if base is not None:
        try:
            return path.relative_to(base).as_posix() or path.name
        except ValueError:
            pass
    return to_stored(path)


def scan_warning_items(warnings: Iterable, group: str = "", base: Path | None = None) -> list[WarningItem]:
    """Warning items of scan warnings that carry a `path` (a Path, a str or None) and a `message` (the WTF Cleaner's
    ScanWarning, core.svfiles.SvScanWarning), under `group`, their paths inside `base` (see where_text)."""
    return [WarningItem(where_text(w.path, base), w.message, group) for w in warnings]


def warnings_label(count: int, noun: str) -> str:
    """The Warnings button's text before its key: "⚠ 4 scan warnings"."""
    return f"⚠ {plural(count, noun)}"


class SummaryLine(Static):
    """The text of a screen's bottom line (#summary). It wraps, so a warning at its end (selected items hidden by
    the filter, flavors not scanned) is read in full; `show_one_line` shows a failed scan's (or a refused folder's)
    message on one row, cut with an ellipsis, so a long error with a WoW path never pushes the rows under the tree
    up (STD-7.25). The whole message is in the notice and the log. The next `update` wraps again."""

    ONE_LINE: ClassVar[str] = "-one-line"
    DEFAULT_CSS = """
    SummaryLine.-one-line { text-wrap: nowrap; text-overflow: ellipsis; }
    """

    def update(self, content: VisualType = "", *, layout: bool = True) -> None:
        self.remove_class(self.ONE_LINE)
        super().update(content, layout=layout)

    def show_one_line(self, message: str) -> None:
        """Show `message` on one row (ellipsis when it is wider than the line)."""
        super().update(Text(message))
        self.add_class(self.ONE_LINE)


class SummaryBar(Horizontal):
    """A screen's bottom line: the #summary `SummaryLine` (what the screen says about the selection) and, at its right end,
    the Warnings button (hidden until `show_count` has a count)."""

    DEFAULT_CSS = """
    SummaryBar { height: auto; width: 100%; background: $surface; }
    SummaryBar > #summary { width: 1fr; }
    SummaryBar > #btn-warnings { width: auto; min-width: 0; height: 1; margin: 0 1 0 1; }
    """

    def __init__(self, text: str | Text = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text

    def compose(self) -> ComposeResult:
        yield SummaryLine(self._text, id="summary")
        button = action_button("Warnings", "navigate", WARNINGS_KEY, id=WARNINGS_BUTTON_ID, compact=True)
        button.can_focus = False  # the bottom line is not a row of controls: a click or `!` presses it
        button.display = False
        yield button

    def show_count(self, count: int, noun: str) -> None:
        """Show the button with `count` warnings (hide it with none)."""
        button = self.query_one(f"#{WARNINGS_BUTTON_ID}", Button)
        if count:
            button.label = Content.assemble(warnings_label(count, noun), " ",
                                            (f"({key_text(WARNINGS_KEY)})", "not bold"))
        button.display = count > 0

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == WARNINGS_BUTTON_ID:
            event.stop()
            self.screen.action_show_warnings()


class WarningsHost:
    """Mixin for a screen with a `SummaryBar` that collects warnings: bind WARNINGS_BINDING, supply
    `warning_items()`, call `refresh_warnings()` whenever the warnings may have changed (where the bottom line is
    updated). WARNINGS_TITLE heads the view, WARNINGS_NOUN counts on the button; LOG_SCREEN (the screen's own) names
    it in the ui.selection event. The view does not open while the
    screen is busy (a scan, a run, the running-programs check: the confirm it leads to opens only on this screen)."""

    WARNINGS_TITLE: ClassVar[str] = "Scan warnings"
    WARNINGS_NOUN: ClassVar[str] = "scan warning"

    def warning_items(self) -> list[WarningItem]:
        """What the screen has to show now (none before a scan)."""
        raise NotImplementedError

    def refresh_warnings(self) -> None:
        if not self.is_attached:
            return
        count = len(self.warning_items())
        for bar in self.query(SummaryBar).results(SummaryBar):
            bar.show_count(count, self.WARNINGS_NOUN)

    def warnings_blocked(self) -> bool:
        return bool(getattr(self, "_checking", False) or getattr(self, "_scanning", False)
                    or getattr(self.app, "busy", False))

    def action_show_warnings(self) -> None:
        items = self.warning_items()
        if not items or self.warnings_blocked() or self.app.screen is not self:
            return
        log_event("ui.selection", screen=self.LOG_SCREEN, control="warnings", value=len(items))
        self.app.push_screen(WarningsScreen(self.WARNINGS_TITLE, items, noun=self.WARNINGS_NOUN,
                                            scope=str(self.sub_title or "")))


class WarningsScreen(FilterBox, ButtonActions, TwoPaneFocus, Screen[None]):
    """The warnings, read-only: a tree grouped by `WarningItem.group` (groups open; none when no item has one), a
    leaf per warning: where in bold, then what. The left pane counts them and has the filter and Back (Esc)."""

    TREE_SELECTOR = "#warnings"
    LOG_SCREEN = "warnings"
    BUTTON_ACTIONS: ClassVar[dict[str, str]] = {"btn-back": "close"}
    DEFAULT_CSS = two_pane_css("WarningsScreen", "#warnings") + """
    WarningsScreen #warnings-count { margin-top: 1; height: auto; }
    WarningsScreen #warning-detail { margin-top: 1; height: auto; max-height: 8; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Back"),
        *FILTER_BINDINGS,
        *TREE_BINDINGS,
        Binding("left", "focus_filters", "Filters", show=False),
        Binding("right", "focus_tree", "Tree", show=False),
        *NAV_BINDINGS,
    ]

    def __init__(self, title: str, items: Sequence[WarningItem], *, noun: str = "scan warning",
                 scope: str = "") -> None:
        super().__init__()
        self.title_text = title
        self.items = list(items)
        self.noun = noun
        self.scope = scope
        self._last_filter: Widget | None = None

    def compose(self) -> ComposeResult:
        groups = len({item.group for item in self.items if item.group})
        count = plural(len(self.items), self.noun) + (f" in {plural(groups, 'flavor')}" if groups > 1 else "")
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="filters"):
                yield Static(self.title_text, classes="section")
                yield Static(Text(count), id="warnings-count")
                yield Static("", id="warning-detail")
                yield FilterBar()
                with ButtonRow(id="actions", wrap=False):
                    yield action_button("Back", "cancel", "escape", id="btn-back")
                yield NavHint(WARNINGS_HINT)
            yield ReviewTree(Text(self.title_text, style=ACCENT), id="warnings")
        yield BottomBar()

    def on_mount(self) -> None:
        self.sub_title = f"{self.scope} · warnings" if self.scope else self.title_text
        self._rebuild()
        self.query_one("#warnings", Tree).focus()
        self.call_after_refresh(self._highlight_first)

    def _highlight_first(self) -> None:
        """Open on the first warning, so the left pane shows it in full at once."""
        tree = self.query_one("#warnings", Tree)
        first = next((node for node in self._walk(tree.root) if node.data and node.data[0] == "item"), None)
        if first is not None:
            tree.get_node_at_line(0)  # lay the lines out, so move_cursor finds the node's line
            tree.move_cursor(first)

    @staticmethod
    def _walk(node):
        for child in node.children:
            yield child
            yield from WarningsScreen._walk(child)

    # --- panes and filter ------------------------------------------------------------------------
    def first_filter(self) -> Widget | None:
        return self.filter_input()

    def filter_changed(self) -> None:
        self._rebuild()

    # --- the tree -------------------------------------------------------------------------------
    def _model(self) -> list[ModelNode]:
        """Group nodes (("group", name)) holding the warnings (("item", index)), or the warnings alone."""
        if not any(item.group for item in self.items):
            return [ModelNode(("item", index)) for index in range(len(self.items))]
        groups: dict[str, ModelNode] = {}
        for index, item in enumerate(self.items):
            groups.setdefault(item.group, ModelNode(("group", item.group))).children.append(ModelNode(("item", index)))
        return list(groups.values())

    def _texts(self, node: ModelNode) -> tuple[str, ...]:
        kind, value = node.data
        if kind == "group":
            return (value,)
        item = self.items[value]
        return item.where, item.what

    def _leaf_label(self, item: WarningItem) -> Text:
        what = Text(item.what, style=theme_colour(self.app, "warning"))
        return Text.assemble((item.where, "bold"), "  ", what) if item.where else what

    def _rebuild(self) -> None:
        tree = self.query_one("#warnings", Tree)
        tree.clear()
        model = self._model()
        kept = self.model_filter(model, lambda n: n.children, self._texts, key=lambda n: n.data)
        for node in model:
            if not kept.shows(node):
                continue
            kind, value = node.data
            if kind == "item":
                tree.root.add_leaf(self._leaf_label(self.items[value]), data=node.data)
                continue
            shown = [child for child in node.children if kept.shows(child)]
            group = tree.root.add(Text.assemble((value, ACCENT), (f"  {plural(len(node.children), self.noun)}",
                                                                   "dim")), data=node.data, expand=True)
            for child in shown:
                group.add_leaf(self._leaf_label(self.items[child.data[1]]), data=child.data)
        self.note_no_match(tree.root)
        tree.root.expand()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """The highlighted warning in full in the left pane (the tree cuts a long path off, at 80 columns surely)."""
        data = event.node.data
        detail = Text()
        if data is not None and data[0] == "item":
            item = self.items[data[1]]
            parts = [(item.group, ACCENT)] if item.group else []
            if item.where:
                parts.append((item.where, "bold"))
            parts.append((item.what, theme_colour(self.app, "warning")))
            detail = Text("\n").join(Text(text, style=style) for text, style in parts)
        self.query_one("#warning-detail", Static).update(detail)

    def action_close(self) -> None:
        self.dismiss(None)
