"""Small shared widgets: a checkbox with ✔/✘ marks, a button row with ←/→ focus (and one that wraps onto more rows),
arrow-key focus bindings."""
from __future__ import annotations

from typing import ClassVar

from rich.cells import cell_len
from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.content import Content
from textual.events import Resize
from textual.widgets import Button, Checkbox, Static

# Pick lists (tool menu, flavor picker): names in gold, in their own column, readable on the cursor row too, whose
# background is a deeper blue than the default cursor for that reason.
LIST_NAME_STYLE = "bold #F2C14E"
LIST_CURSOR_BACKGROUND = "#1C4E8F"

# One colour per kind of action, the same in every tool (Textual Button variants). Pick buttons by what they do:
ACTION_VARIANTS = {
    "delete": "error",      # removes files for good (Clean): red
    "apply": "success",     # changes files, can be undone (Organize): green
    "simulate": "primary",  # shows what would happen, changes nothing (Dry run): blue
    "revert": "warning",    # puts a change back, or overrides a safeguard (Undo last run, Override): amber
    "confirm": "primary",   # the expected next step of a dialog (Save, Yes, Update now, Remind me): blue
    "neutral": "default",   # refresh, navigation and backing out (Rescan, Other flavor, Tools, Quit, Cancel, No)
}


def action_button(label: str, action: str, **kwargs) -> Button:
    """A Button coloured by the kind of action it performs (see ACTION_VARIANTS)."""
    return Button(label, variant=ACTION_VARIANTS[action], **kwargs)


CHECK_ON = "✔"
CHECK_OFF = "✘"

# ↑/↓ move focus between widgets. Not priority bindings: a focused tree, list, table or input that uses the
# arrow keys itself handles them first.
NAV_BINDINGS = [
    Binding("up", "app.focus_previous", "Previous", show=False),
    Binding("down", "app.focus_next", "Next", show=False),
]


class FormScroll(VerticalScroll):
    """A scrolling form. ↑/↓ move focus (the focused field scrolls into view) instead of scrolling, so the keys
    keep working once the form is taller than the screen."""

    BINDINGS: ClassVar[list[Binding]] = list(NAV_BINDINGS)

    def open_at_top(self) -> None:
        """Show the form from its title once it is laid out, even though the focused field (lower down) asked to be
        scrolled into view on mount."""
        self.call_after_refresh(self.scroll_home, animate=False)


class Ka0sCheckbox(Checkbox):
    """A checkbox that shows a bright ✔ when on and a dimmed ✘ when off."""

    DEFAULT_CSS = """
    Ka0sCheckbox > .toggle--button { color: $text-muted; background: $panel; text-style: dim; }
    Ka0sCheckbox.-on > .toggle--button { color: $success; background: $panel; text-style: bold not dim; }
    """

    @property
    def _button(self) -> Content:
        style = self.get_visual_style("toggle--button")
        return Content.assemble((f" {CHECK_ON if self.value else CHECK_OFF} ", style))


class ButtonRow(Horizontal):
    """A row of buttons; ← and → move focus between them.

    With wrap=False the keys do not wrap round at either end: they fall through to the screen instead (the
    review screen uses → at the last button to jump to the tree)."""

    DEFAULT_CSS = """
    ButtonRow { height: auto; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("left", "move(-1)", "Previous button", show=False),
        Binding("right", "move(1)", "Next button", show=False),
        Binding("space", "press_focused", "Press", show=False),
    ]

    def __init__(self, *children, wrap: bool = True, **kwargs) -> None:
        super().__init__(*children, **kwargs)
        self.wrap = wrap

    def action_press_focused(self) -> None:
        """Space activates the focused button, like Enter (Textual's Button only binds Enter)."""
        focused = self.screen.focused
        if isinstance(focused, Button) and focused in self.query(Button):
            focused.press()

    def action_move(self, step: int) -> None:
        buttons = [b for b in self.query(Button) if b.focusable]
        focused = self.screen.focused
        if not buttons or focused not in buttons:
            return
        index = buttons.index(focused) + step
        if not self.wrap and not 0 <= index < len(buttons):
            raise SkipAction()
        buttons[index % len(buttons)].focus()


class WrapButtonRow(ButtonRow):
    """A ButtonRow whose compact buttons flow onto as many rows as its width needs, in order, each as wide as its
    label: a grid of one-cell columns where each button spans its label's width plus a gap, and the room left on a
    full row is shared out among its buttons (the last row keeps the first row's share, so it lines up). ← and →
    move through the buttons in order, wrapping round (the Ace3 review's action bar under the tree)."""

    DEFAULT_CSS = """
    WrapButtonRow { layout: grid; grid-size: 1; grid-columns: 1; grid-gutter: 0 0; grid-rows: 1; height: auto; }
    WrapButtonRow > Button { width: 1fr; min-width: 0; height: 1; margin-right: 1; }
    """
    GUTTER = 1  # the blank cell after each button (its margin-right)

    def on_mount(self) -> None:
        self._fit(self.size.width)

    def on_resize(self, event: Resize) -> None:
        self._fit(event.size.width)

    def _fit(self, width: int) -> None:
        buttons = list(self.query(Button))
        if not buttons or width <= 0:
            return
        rows: list[list[tuple[Button, int]]] = [[]]
        used = 0
        for button in buttons:
            need = min(width, cell_len(button.label.plain) + 2 + self.GUTTER)  # a compact button's padding
            if rows[-1] and used + need > width:
                rows.append([])
                used = 0
            rows[-1].append((button, need))
            used += need
        share = None
        for number, row in enumerate(rows):
            slack = width - sum(need for _, need in row)
            if number == len(rows) - 1 and share is not None:
                extra, left = min(share, slack // len(row)), 0  # the last row lines up with the first
            else:
                extra, left = divmod(slack, len(row))
            share = extra if share is None else share
            for index, (button, need) in enumerate(row):
                span = need + extra + (1 if index < left else 0)
                if button.styles.column_span != span:
                    button.styles.column_span = span
        if self.styles.grid_size_columns != width:
            self.styles.grid_size_columns = width


class NavHint(Static):
    """The one-line keyboard hint under a screen's controls."""

    DEFAULT_CSS = """
    NavHint { color: $text-muted; height: auto; margin-top: 1; }
    """
