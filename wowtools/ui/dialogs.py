"""Dialogs and screen helpers shared by every tool: the yes/no confirmation, the progress modal of a run, tick marks
and relabelling for review trees, the two-pane (filters + tree) focus moves, and theme colours with the Ka0s
colours as a fallback. A tool's screens import these; no tool imports another tool's screens."""
from __future__ import annotations

from collections.abc import Callable, Collection, Hashable, Iterable
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, ProgressBar, Static, Tree

from wowtools.ui.theme import KA0S_THEME
from wowtools.ui.widgets import CHECK_OFF, CHECK_ON, NAV_BINDINGS, ButtonRow, NavHint, action_button

PARTLY_TICKED = "◩"
ALERT_STYLE = "bold #E5534B"


def theme_colour(app, name: str) -> str:
    """A colour of the running theme ("success", "accent", "warning", "error", ...), or the Ka0s theme's colour
    when there is no theme yet."""
    try:
        colour = getattr(app.current_theme, name, None)
    except Exception:  # noqa: BLE001 - no app or no theme yet: use the Ka0s colour
        colour = None
    return colour or getattr(KA0S_THEME, name)


def tick_mark(items: Iterable, unchecked: Collection[Hashable], key: Callable[[object], Hashable] | None = None,
              *, success: str | None = None) -> tuple[str, str]:
    """(mark, style) for a review-tree line covering `items`: ✘ when every item is unticked, ◩ when some are, ✔
    (in the success colour) otherwise. An item is unticked when key(item) is in `unchecked`."""
    items = list(items)
    keyed = items if key is None else [key(i) for i in items]
    off = sum(1 for k in keyed if k in unchecked)
    if items and off == len(items):
        return f"{CHECK_OFF} ", "dim"
    if off:
        return f"{PARTLY_TICKED} ", "bold"
    return f"{CHECK_ON} ", f"bold {success or KA0S_THEME.success}"


def relabel_branch(tree: Tree, node, label: Callable[[object], Text], skip: Collection[str] = ()) -> None:
    """Relabel node's branch and its ancestors (everything a tick there can change), or the whole tree when node is
    None. Nodes whose data kind (data[0]) is in `skip` keep their label (read-only groups)."""
    if node is not None:
        parent = node.parent
        while parent is not None:
            if parent.data is not None:
                parent.set_label(label(parent.data))
            parent = parent.parent
    stack = [node or tree.root]
    while stack:
        current = stack.pop()
        if current.data is not None and current.data[0] not in skip:
            current.set_label(label(current.data))
        stack.extend(current.children)


class TwoPaneFocus:
    """Mixin for a review screen with a left panel (id "filters") and a tree (TREE_SELECTOR): ← goes back to the
    control last focused in the panel (or first_filter()), → goes to the tree."""

    TREE_SELECTOR = "Tree"
    _last_filter: Widget | None = None

    def first_filter(self) -> Widget | None:
        raise NotImplementedError

    def on_descendant_focus(self, event) -> None:
        widget = event.widget
        if any(ancestor.id == "filters" for ancestor in widget.ancestors):
            self._last_filter = widget

    def action_focus_filters(self) -> None:
        focused = self.focused
        if focused is not None and any(a.id == "filters" for a in focused.ancestors):
            return  # already in the left panel
        target = self._last_filter
        if target is None or not target.is_attached or not target.focusable:
            target = self.first_filter()
        if target is not None:
            target.focus()

    def action_focus_tree(self) -> None:
        tree = self.query_one(self.TREE_SELECTOR, Tree)
        if tree.display and self.focused is not tree:
            tree.focus()


class ConfirmScreen(ModalScreen[bool]):
    """A yes/no question. `alerts` are extra lines shown in red; `default_yes` decides which button has focus (risky
    actions start on No)."""

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen #confirm-box { width: 80; height: auto; border: thick $accent; background: $panel; padding: 1 2; }
    ConfirmScreen #confirm-title { color: $accent; text-style: bold; margin-bottom: 1; }
    ConfirmScreen #confirm-buttons { height: auto; align-horizontal: right; margin-top: 1; }
    ConfirmScreen Button { margin-left: 2; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("y", "answer(True)", "Yes"), Binding("n,escape", "answer(False)", "No"), *NAV_BINDINGS]

    def __init__(self, title: str, body: str, alerts: tuple[str, ...] = (), *, default_yes: bool = False) -> None:
        super().__init__()
        self.default_yes = default_yes
        self.title_text = title
        self.alerts = alerts
        self.body_text = "\n".join([body, *alerts]) if alerts else body

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(Text(self.title_text), id="confirm-title")
            body = Text(self.body_text)
            for alert in self.alerts:
                body.highlight_words([alert], style=ALERT_STYLE)
            yield Static(body)
            with ButtonRow(id="confirm-buttons"):
                yield action_button("Yes (y)", "confirm", id="yes")
                yield action_button("No (n)", "neutral", id="no")
            yield NavHint("←→ choose · Enter/Space press · y yes · n/Esc no")

    def on_mount(self) -> None:
        self.query_one("#yes" if self.default_yes else "#no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class ProgressScreen(ModalScreen[None]):
    """Shown while a run, dry run or undo works in a worker: the stage, a progress bar and the current file.

    A tool subclasses it with its own ID_PREFIX (widget ids <prefix>-box, -stage, -progress, -file), STAGE_TITLES
    and SIMULATED_STAGE (the stage a dry run calls "Simulating"). update_progress(stage, current, total, detail)
    is the run's progress callback (on the UI thread: workers go through call_from_thread); a total of 0 means
    "not known" and runs the bar as indeterminate. set_flavor(label) puts "<label>: " in front of the stage title
    while several flavors run one after another."""

    DEFAULT_CSS = """
    ProgressScreen { align: center middle; }
    ProgressScreen .progress-box { width: 80; height: auto; border: thick $accent; background: $panel; padding: 1 2; }
    ProgressScreen .progress-stage { color: $accent; text-style: bold; margin-bottom: 1; }
    ProgressScreen .progress-bar { width: 1fr; }
    ProgressScreen .progress-file { color: $text-muted; margin-top: 1; height: 2; overflow: hidden hidden; }
    """
    ID_PREFIX = "progress"
    STAGE_TITLES: ClassVar[dict[str, str]] = {}
    SIMULATED_STAGE = ""

    def __init__(self, *, dry_run: bool = False, first_stage: str = "",
                 stage_titles: dict[str, str] | None = None) -> None:
        super().__init__()
        self.dry_run = dry_run
        self.first_stage = first_stage
        self.stage = first_stage
        self.stage_titles = self.STAGE_TITLES if stage_titles is None else stage_titles
        self.flavor_label = ""

    def _part_id(self, part: str) -> str:
        return f"{self.ID_PREFIX}-{part}"

    def compose(self) -> ComposeResult:
        with Vertical(id=self._part_id("box"), classes="progress-box"):
            yield Static(Text(self.stage_title(self.first_stage)), id=self._part_id("stage"), classes="progress-stage")
            yield ProgressBar(id=self._part_id("progress"), classes="progress-bar", show_eta=False)
            yield Static("", id=self._part_id("file"), classes="progress-file")

    def stage_title(self, stage: str) -> str:
        if self.dry_run and stage == self.SIMULATED_STAGE:
            title = "Simulating"
        else:
            title = self.stage_titles.get(stage, stage)
        return f"{self.flavor_label}: {title}" if self.flavor_label else title

    def set_flavor(self, label: str) -> None:
        self.flavor_label = label

    def update_progress(self, stage: str, current: int, total: int, detail: str = "") -> None:
        self.stage = stage
        self.query_one(f"#{self._part_id('stage')}", Static).update(Text(self.stage_title(stage)))
        bar = self.query_one(f"#{self._part_id('progress')}", ProgressBar)
        bar.update(total=total if total > 0 else None, progress=current)
        self.query_one(f"#{self._part_id('file')}", Static).update(Text(detail))
