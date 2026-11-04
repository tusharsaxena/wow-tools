"""The full macro reference (config tools spec ME8), opened from the edit screen with F1: every command, conditional and
@unit target the flavor's reference knows (explain.reference_lines), with its help in our own words, its source and,
where the source leaves this game version out, a note. Read-only; Back (Esc) returns to the edit screen."""
from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Header, Static

from wowtools.core.install import flavor_name
from wowtools.core.kb import MacroReference
from wowtools.tools.macro_editor.explain import reference_lines
from wowtools.ui.branding import BottomBar
from wowtools.ui.dialogs import ACCENT, ALERT_STYLE
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

__all__ = ["ReferenceScreen"]

NAV_HINT = "↑↓ PgUp/PgDn scroll · Tab move"


class ReferenceScreen(Screen[None]):
    DEFAULT_CSS = """
    ReferenceScreen #reference-box { height: 1fr; padding: 0 1; }
    ReferenceScreen #reference-head { height: auto; margin-bottom: 1; }
    ReferenceScreen #reference-scroll { height: 1fr; border: tall $primary; }
    ReferenceScreen .buttons { height: auto; margin: 1 1 0 1; }
    ReferenceScreen NavHint { padding: 0 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "close", "Back", show=False), *NAV_BINDINGS]

    def __init__(self, ref: MacroReference) -> None:
        super().__init__()
        self.ref = ref

    def reference_text(self) -> Text:
        text = Text()
        section = None
        for where, name, help_text, source, note in reference_lines(self.ref):
            if where != section:
                text.append(("\n\n" if section else "") + where, style=ACCENT)
                section = where
            text.append(f"\n{name}", style="bold")
            text.append(f"  {help_text}")
            if note:
                text.append(f"  {note}", style=ALERT_STYLE)
            text.append(f"\n    {source}", style="dim")
        return text

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="reference-box"):
            game = flavor_name(self.ref.flavor) if self.ref.flavor else "every game version"
            yield Static(Text(f"Macro commands, conditionals and units, for {game}. Each line's source is under it; "
                              "spell names are free text and never checked."), id="reference-head")
            with VerticalScroll(id="reference-scroll"):
                yield Static(self.reference_text(), id="reference")
        with ButtonRow(classes="buttons"):
            yield action_button("Back", "cancel", "escape", id="btn-back")
        yield NavHint(NAV_HINT)
        yield BottomBar()

    def on_mount(self) -> None:
        self.sub_title = "Macro Editor · reference"
        self.query_one("#reference-scroll").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            event.stop()
            self.action_close()

    def action_close(self) -> None:
        self.dismiss(None)
