"""Dialogs and screen helpers shared by every tool: the yes/no confirmation, an information popup (both can list
their details in a tree), a warning with a choice of buttons, the progress modal of a run, tick marks
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
ACCENT = "bold #5CC8FF"  # names in a review tree (flavors, groups) and section headings in the tree
BUSY_STYLE = "bold #E8B04B"  # a summary line that says work is going on ("Checking for running programs…")

# One look for every tool: the same left pane, action row, bottom line and hints on the two-pane screens, the
# same layout and hints on the result screens, the same form on the settings screens.
FILTERS_WIDTH = 50  # the left pane: wide enough for four action buttons in one row; the tree takes the rest (1fr)
# A popup's width: readable, with room around it at 120x30, centred and never stretched when the window grows, and
# never more than 90% of a smaller window.
POPUP_WIDTH = "width: 90; max-width: 90%;"
# A settings form's width: the whole window up to 100 columns, centred (never stretched edge to edge).
FORM_WIDTH = "width: 100%; max-width: 100;"


def review_hint(space: str = "tick") -> str:
    """The start of a two-pane screen's hint; `space` says what Space does in its tree ("tick", "tick or open")."""
    return f"↑↓/Tab move · ←→ panes and buttons · Space {space} · Enter/Space press · "


REVIEW_HINT = review_hint()
TREE_HINT = "x expand all · c collapse all · "  # every tree screen's hint names these, before r rescan
# Every tree screen binds these (with TreeKeys' actions, which TwoPaneFocus has).
TREE_BINDINGS = [
    Binding("x", "expand_all", "Expand all", show=False),
    Binding("c", "collapse_all", "Collapse all", show=False),
]
RESULT_HINT = "↑↓/Tab move · ←→ buttons · Enter/Space press · Esc back · "


def two_pane_css(screen: str, tree: str, *, width: int = FILTERS_WIDTH) -> str:
    """DEFAULT_CSS of a two-pane screen called `screen`: the left pane (#filters: .section headings, compact
    checkboxes and inputs, the #actions button row in one line), the tree (`tree`), the scan progress that stands
    in for the tree while a scan runs (#scan-box) and the bottom line (#summary)."""
    return f"""
    {screen} #body {{ height: 1fr; }}
    {screen} #filters {{ width: {width}; padding: 0 1; border-right: solid $primary; }}
    {screen} #filters .section {{ color: $accent; text-style: bold; margin: 1 0 0 0; }}
    {screen} #filters Ka0sCheckbox, {screen} #filters Input {{ margin: 0; }}
    {screen} #actions {{ margin-top: 1; height: auto; }}
    {screen} #actions Button {{ min-width: 0; width: auto; margin-right: 1; }}
    {screen} {tree} {{ width: 1fr; padding: 0 1; }}
    {screen} #scan-box {{ width: 1fr; height: auto; padding: 1 2; }}
    {screen} #scan-progress {{ width: 1fr; }}
    {screen} #scan-label {{ color: $text-muted; margin-top: 1; }}
    {screen} #summary {{ height: auto; padding: 0 1; background: $surface; }}
    """


def result_css(screen: str) -> str:
    """DEFAULT_CSS of a result screen called `screen`: #result holds the Item/Value #result-summary (at most 60% of
    the height: a one-flavor clean's 10 rows fit at 120x30) above the detail table (class result-detail), then the
    .buttons row and the NavHint."""
    return f"""
    {screen} #result {{ height: 1fr; padding: 1 2; }}
    {screen} #result-summary {{ height: auto; max-height: 60%; margin-bottom: 1; }}
    {screen} .result-detail {{ height: 1fr; }}
    {screen} .buttons {{ height: auto; padding: 0 2; }}
    {screen} .buttons Button {{ min-width: 0; width: auto; margin-right: 1; }}
    {screen} NavHint {{ padding: 0 2; margin-top: 0; }}
    """


def settings_css(screen: str) -> str:
    """DEFAULT_CSS of a tool's settings screen called `screen` (a FormScroll #settings with a .title, labels,
    inputs, compact checkboxes, #settings-error and a .buttons row): a readable width (FORM_WIDTH), centred."""
    return f"""
    {screen} {{ align-horizontal: center; }}
    {screen} #settings {{ {FORM_WIDTH} padding: 0 2; }}
    {screen} .title {{ color: $accent; text-style: bold; margin: 1 0; }}
    {screen} Label {{ width: 1fr; height: auto; }}
    {screen} Ka0sCheckbox {{ margin-bottom: 1; }}
    {screen} Ka0sCheckbox.-textual-compact {{ margin-bottom: 0; }}
    {screen} #settings-error {{ color: $error; height: auto; }}
    {screen} .buttons {{ height: auto; margin-top: 1; }}
    {screen} Button {{ margin-right: 2; }}
    """


def theme_colour(app, name: str) -> str:
    """A colour of the running theme ("success", "accent", "warning", "error", ...), or the Ka0s theme's colour
    when there is no theme yet."""
    try:
        colour = getattr(app.current_theme, name, None)
    except Exception:  # noqa: BLE001 - no app or no theme yet: use the Ka0s colour
        colour = None
    return colour or getattr(KA0S_THEME, name)


DETAIL_ROWS = 12  # a popup's detail tree opens every branch when it fits in this many lines


def detail_tree(groups: dict[str, list[str]]) -> Tree:
    """A popup's read-only detail tree (#details): one branch per group, labelled with how many items it holds, its
    items as leaves; a group with no items is a leaf. Every branch starts open when everything fits in DETAIL_ROWS
    lines, else closed (Space or Enter opens one, x opens all)."""
    tree: Tree = Tree("", id="details", classes="popup-tree")
    tree.show_root = False
    tree.auto_expand = True
    open_all = len(groups) + sum(len(items) for items in groups.values()) <= DETAIL_ROWS
    for label, items in groups.items():
        if not items:
            tree.root.add_leaf(Text(label))
            continue
        branch = tree.root.add(Text.assemble((label, "bold"), f" ({len(items)})"), expand=open_all)
        for item in items:
            branch.add_leaf(Text(item))
    return tree


def detail_hint(groups: dict[str, list[str]] | None) -> str:
    """The part of a popup's hint about its detail tree (none without one)."""
    return f"↑↓/Tab move · Space open · {TREE_HINT}" if groups else ""


# At 120x30 a confirm with a full detail tree shows its buttons and its two-line hint; a smaller window scrolls the box.
POPUP_TREE_CSS = "height: auto; max-height: 40vh; margin-top: 1; padding: 0 1; background: $surface;"


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


class TreeKeys:
    """Mixin for a screen with a tree (TREE_SELECTOR): x expands every node below the root, c collapses them (the
    root stays open). Bind them with TREE_BINDINGS. A node whose children load on expand (on_tree_node_expanded)
    loads them too: those children are leaves in every tool."""

    TREE_SELECTOR = "Tree"

    def _tree_for_keys(self) -> Tree | None:
        found = self.query(self.TREE_SELECTOR)
        tree = found.first(Tree) if found else None  # a popup's detail tree is optional
        return tree if tree is not None and tree.display else None  # hidden while a scan runs

    def action_expand_all(self) -> None:
        tree = self._tree_for_keys()
        if tree is None:
            return
        cursor = tree.cursor_node
        stack = list(tree.root.children)
        while stack:
            node = stack.pop()
            if node.allow_expand and not node.is_expanded:
                node.expand()
            stack.extend(node.children)
        self._keep_cursor(tree, cursor)

    def action_collapse_all(self) -> None:
        tree = self._tree_for_keys()
        if tree is None:
            return
        cursor = tree.cursor_node
        while cursor is not None and cursor.parent is not None and cursor.parent is not tree.root:
            cursor = cursor.parent  # the top-level node it was under stays highlighted
        for node in tree.root.children:
            node.collapse_all()
        self._keep_cursor(tree, cursor)

    @staticmethod
    def _keep_cursor(tree: Tree, node) -> None:
        if node is None:
            return
        tree.get_node_at_line(0)  # lay the lines out now, so move_cursor finds the node's new line
        if node.line >= 0:
            tree.move_cursor(node)


class TwoPaneFocus(TreeKeys):
    """Mixin for a review screen with a left panel (id "filters") and a tree (TREE_SELECTOR): ← goes back to the
    control last focused in the panel (or first_filter()), → goes to the tree. x and c expand and collapse the
    whole tree (TreeKeys)."""

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


class ConfirmScreen(TreeKeys, ModalScreen[bool]):
    """A yes/no question. `alerts` are extra lines shown in red; `default_yes` decides which button has focus (risky
    actions start on No). `groups` ({label: items}) lists the details in a tree below the body (detail_tree)."""

    DEFAULT_CSS = f"""
    ConfirmScreen {{ align: center middle; }}
    ConfirmScreen #confirm-box {{ {POPUP_WIDTH} height: auto; max-height: 100%; overflow-y: auto;
                                 border: thick $accent; background: $panel; padding: 1 2; }}
    ConfirmScreen #confirm-title {{ color: $accent; text-style: bold; margin-bottom: 1; }}
    ConfirmScreen .popup-tree {{ {POPUP_TREE_CSS} }}
    ConfirmScreen #confirm-buttons {{ height: auto; align-horizontal: right; margin-top: 1; }}
    ConfirmScreen Button {{ margin-left: 2; }}
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("y", "answer(True)", "Yes"), Binding("n,escape", "answer(False)", "No"),
                                         *NAV_BINDINGS, *TREE_BINDINGS]

    def __init__(self, title: str, body: str, alerts: tuple[str, ...] = (), *, default_yes: bool = False,
                 groups: dict[str, list[str]] | None = None) -> None:
        super().__init__()
        self.default_yes = default_yes
        self.title_text = title
        self.alerts = alerts
        self.body_text = "\n".join([body, *alerts]) if alerts else body
        self.groups = groups

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(Text(self.title_text), id="confirm-title")
            body = Text(self.body_text)
            for alert in self.alerts:
                body.highlight_words([alert], style=ALERT_STYLE)
            yield Static(body)
            if self.groups:
                yield detail_tree(self.groups)
            with ButtonRow(id="confirm-buttons"):
                yield action_button("Yes (y)", "confirm", id="yes")
                yield action_button("No (n)", "cancel", id="no")
            yield NavHint(f"{detail_hint(self.groups)}←→ choose · Enter/Space press · y yes · n/Esc no")

    def on_mount(self) -> None:
        self.query_one("#yes" if self.default_yes else "#no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class ChoiceScreen(ModalScreen[str | None]):
    """A warning to act on (an earlier run did not finish, ...): a title in the warning colour, a message and one
    button per choice, given as (id, label, action kind). Pressing one calls choose(id), which dismisses with the
    id; a subclass may act first. `default` is the id focused at the start. With `escape` Esc dismisses with None
    (the question comes back later); without it Esc does nothing and a button must be pressed. `hint` (optional)
    is a NavHint line under the buttons."""

    DEFAULT_CSS = f"""
    ChoiceScreen {{ align: center middle; }}
    ChoiceScreen #choice-box {{ {POPUP_WIDTH} height: auto; max-height: 100%; overflow-y: auto;
                               border: thick $warning; background: $panel; padding: 1 2; }}
    ChoiceScreen #choice-title {{ color: $warning; text-style: bold; margin-bottom: 1; }}
    ChoiceScreen #choice-buttons {{ height: auto; align-horizontal: right; margin-top: 1; }}
    ChoiceScreen Button {{ margin-left: 2; }}
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "close", "Close", show=False)]

    def __init__(self, title: str, message: str, choices: Iterable[tuple[str, str, str]], *, default: str,
                 escape: bool = False, hint: str = "") -> None:
        super().__init__()
        self.title_text = title
        self.message_text = message
        self.choices = list(choices)
        self.default = default
        self.escape = escape
        self.hint = hint

    def compose(self) -> ComposeResult:
        with Vertical(id="choice-box"):
            yield Static(Text(self.title_text), id="choice-title")
            yield Static(Text(self.message_text), id="choice-message")
            with ButtonRow(id="choice-buttons"):
                for choice_id, label, kind in self.choices:
                    yield action_button(label, kind, id=choice_id)
            if self.hint:
                yield NavHint(self.hint)

    def on_mount(self) -> None:
        self.query_one(f"#{self.default}", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.choose(event.button.id or "")

    def choose(self, choice: str) -> None:
        self.dismiss(choice)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return self.escape if action == "close" else True

    def action_close(self) -> None:
        self.dismiss(None)


class InfoScreen(TreeKeys, ModalScreen[None]):
    """Something to read and acknowledge, in place of a notification too long for one: an optional body, then the
    details in a tree (detail_tree), and an OK button."""

    DEFAULT_CSS = f"""
    InfoScreen {{ align: center middle; }}
    InfoScreen #info-box {{ {POPUP_WIDTH} height: auto; max-height: 100%; overflow-y: auto;
                           border: thick $accent; background: $panel; padding: 1 2; }}
    InfoScreen #info-title {{ color: $accent; text-style: bold; }}
    InfoScreen #info-body {{ margin-top: 1; }}
    InfoScreen .popup-tree {{ {POPUP_TREE_CSS} }}
    InfoScreen #info-buttons {{ height: auto; align-horizontal: right; margin-top: 1; }}
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "close", "Close"), *NAV_BINDINGS, *TREE_BINDINGS]

    def __init__(self, title: str, groups: dict[str, list[str]], body: str = "") -> None:
        super().__init__()
        self.title_text = title
        self.groups = groups
        self.body_text = body

    def compose(self) -> ComposeResult:
        with Vertical(id="info-box"):
            yield Static(Text(self.title_text), id="info-title")
            if self.body_text:
                yield Static(Text(self.body_text), id="info-body")
            yield detail_tree(self.groups)
            with ButtonRow(id="info-buttons"):
                yield action_button("OK", "confirm", id="ok")
            yield NavHint(f"{detail_hint(self.groups)}Enter/Space OK · Esc close")

    def on_mount(self) -> None:
        self.query_one("#ok", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class ProgressScreen(ModalScreen[None]):
    """Shown while a run, dry run or undo works in a worker: the stage, a progress bar and the current file.

    A tool subclasses it with its own ID_PREFIX (widget ids <prefix>-box, -stage, -progress, -file), STAGE_TITLES
    and SIMULATED_STAGE (the stage a dry run calls "Simulating"). update_progress(stage, current, total, detail)
    is the run's progress callback (on the UI thread: workers go through call_from_thread); a total of 0 means
    "not known" and runs the bar as indeterminate. set_flavor(label) puts "<label>: " in front of the stage title
    while several flavors run one after another."""

    DEFAULT_CSS = f"""
    ProgressScreen {{ align: center middle; }}
    ProgressScreen .progress-box {{ {POPUP_WIDTH} height: auto; border: thick $accent; background: $panel;
                                   padding: 1 2; }}
    ProgressScreen .progress-stage {{ color: $accent; text-style: bold; margin-bottom: 1; }}
    ProgressScreen .progress-bar {{ width: 1fr; }}
    ProgressScreen .progress-file {{ color: $text-muted; margin-top: 1; height: 2; overflow: hidden hidden; }}
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
