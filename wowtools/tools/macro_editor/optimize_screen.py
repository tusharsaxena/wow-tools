"""The optimizer's review (config tools spec ME10), opened from the edit screen with Ctrl+O: the body's length before
and after, then each rewrite (optimizer.optimize) as its line before (`-`) and after (`+`), with the rule's reason and
its source. Nothing changes until OK, which dismisses with True (the edit screen takes the rewritten body); Cancel
and Esc dismiss with False."""
from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from wowtools.core.kb import load_optimizer_rules
from wowtools.core.macrofile import BODY_LIMIT
from wowtools.core.text import plural
from wowtools.tools.macro_editor.ops import body_length
from wowtools.tools.macro_editor.optimizer import Rewrite
from wowtools.ui.dialogs import popup_css, theme_colour
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

__all__ = ["OptimizeScreen"]


class OptimizeScreen(ModalScreen[bool]):
    DEFAULT_CSS = popup_css("OptimizeScreen") + """
    OptimizeScreen #rewrites-box { height: auto; max-height: 14; border: tall $primary; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Cancel"),
                                         Binding("ctrl+s", "ok", "OK", show=False), *NAV_BINDINGS]

    def __init__(self, before: str, after: str, rewrites: Sequence[Rewrite]) -> None:
        super().__init__()
        self.before = before
        self.after = after
        self.rewrites = list(rewrites)

    def compose(self) -> ComposeResult:
        old, new = body_length(self.before), body_length(self.after)
        with Vertical(classes="popup-box"):
            yield Static(Text("Optimize the macro"), classes="title")
            yield Static(Text(f"{plural(len(self.rewrites), 'rewrite')}: {old} → {new} of {BODY_LIMIT} characters. "
                              "Each one is the same in game, for the reason given."), classes="popup-body")
            with VerticalScroll(id="rewrites-box"):
                yield Static("", id="rewrites")
            with ButtonRow(classes="popup-buttons"):
                yield action_button("OK", "confirm", "ctrl+s", id="ok")
                yield action_button("Cancel", "cancel", "escape", id="cancel")
            yield NavHint("↑↓ PgUp/PgDn scroll · Tab move")

    def on_mount(self) -> None:
        rules = load_optimizer_rules()
        removed, added = (f"bold {theme_colour(self.app, 'error')}", f"bold {theme_colour(self.app, 'success')}")
        text = Text()
        for index, rewrite in enumerate(self.rewrites):
            if index:
                text.append("\n\n")
            info = rules.get(rewrite.rule)
            text.append(info.title if info is not None else rewrite.rule, style="bold")
            text.append(f"\n- {rewrite.before}", style=removed)
            text.append(f"\n+ {rewrite.after}", style=added)
            text.append(f"\n{rewrite.reason}\nSource: {rewrite.source}", style="dim")
        self.query_one("#rewrites", Static).update(text)
        self.query_one("#rewrites-box").focus()

    def action_ok(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "ok")

    def action_cancel(self) -> None:
        self.dismiss(False)
