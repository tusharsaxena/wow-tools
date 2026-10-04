"""Small shared widgets: a checkbox with ✔/✘ marks, a button row with ←/→ focus, arrow-key focus bindings."""
from __future__ import annotations

from typing import ClassVar

from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.content import Content
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


class NavHint(Static):
    """The one-line keyboard hint under a screen's controls."""

    DEFAULT_CSS = """
    NavHint { color: $text-muted; height: auto; margin-top: 1; }
    """
