"""Small shared widgets: a checkbox with ✔/✘ marks, a button row with ←/→ focus, arrow-key focus bindings."""
from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal
from textual.content import Content
from textual.widgets import Button, Checkbox, Static

CHECK_ON = "✔"
CHECK_OFF = "✘"

# ↑/↓ move focus between widgets. Not priority bindings: a focused tree, list, table or input that uses the
# arrow keys itself handles them first.
NAV_BINDINGS = [
    Binding("up", "app.focus_previous", "Previous", show=False),
    Binding("down", "app.focus_next", "Next", show=False),
]


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
    """A row of buttons; ← and → move focus between them."""

    DEFAULT_CSS = """
    ButtonRow { height: auto; }
    """
    BINDINGS = [
        Binding("left", "move(-1)", "Previous button", show=False),
        Binding("right", "move(1)", "Next button", show=False),
        Binding("space", "press_focused", "Press", show=False),
    ]

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
        buttons[(buttons.index(focused) + step) % len(buttons)].focus()


class NavHint(Static):
    """The one-line keyboard hint under a screen's controls."""

    DEFAULT_CSS = """
    NavHint { color: $text-muted; height: auto; margin-top: 1; }
    """
