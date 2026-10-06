"""The Saved Variables Browser's review screen. A placeholder until the M3 screens (plan T3.1-T3.4): it names what
was picked and goes back. Dismisses with "flavors", "tools" or "quit" (ToolFlow._after_review)."""
from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Header, Static

from wowtools.core.install import Flavor
from wowtools.ui.branding import BottomBar
from wowtools.ui.widgets import NAV_BINDINGS, NavHint, action_button

TITLE = "Saved Variables Browser"
PLACEHOLDER_TEXT = "Browsing, search and editing come in the next build of this tool. Nothing is read or changed."


class SvReviewScreen(Screen[str]):
    DEFAULT_CSS = """
    SvReviewScreen #placeholder { height: auto; padding: 1 2; }
    SvReviewScreen #placeholder Static { margin-bottom: 1; }
    SvReviewScreen NavHint { padding: 0 2; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "choose('flavors')", "Back", show=False),
                                         Binding("f", "choose('flavors')", "Flavors"),
                                         Binding("t", "choose('tools')", "Tools"),
                                         Binding("q", "choose('quit')", "Quit"), *NAV_BINDINGS]

    def __init__(self, flavors: list[Flavor], label: str) -> None:
        super().__init__()
        self.flavors = flavors
        self.label = label

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="placeholder"):
            yield Static(f"{TITLE}: {self.label} ({len(self.flavors)} flavor{'' if len(self.flavors) == 1 else 's'})")
            yield Static(PLACEHOLDER_TEXT)
            yield action_button("Back", "cancel", "escape", id="btn-back")
        yield NavHint("f flavors · t tools")
        yield BottomBar()

    def on_mount(self) -> None:
        self.sub_title = f"{TITLE} · {self.label}"
        self.query_one("#btn-back", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.dismiss("flavors")

    def action_choose(self, choice: str) -> None:
        self.dismiss(choice)
