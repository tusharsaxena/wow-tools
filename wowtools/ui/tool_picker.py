"""`python -m wowtools` with no tool: pick one from the registry."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from wowtools.core.events import log_event
from wowtools.tools import TOOLS
from wowtools.ui.base import Ka0sApp
from wowtools.ui.branding import Banner, BrandBar


class ToolPickerApp(Ka0sApp):
    SUB_TITLE = "Choose a tool"
    CSS = """
    #pick-title { color: $accent; text-style: bold; padding: 0 2; }
    #tools { margin: 1 2; height: auto; border: tall $primary; }
    """
    BINDINGS = [Binding("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Banner()
        yield Static("Choose a tool", id="pick-title")
        yield OptionList(*[Option(Text(f"{t.title}  ·  {t.description}"), id=t.name) for t in TOOLS.values()],
                         id="tools")
        yield BrandBar()
        yield Footer()

    def after_mount(self) -> None:
        self.query_one("#tools", OptionList).highlighted = 0
        self.query_one("#tools", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        log_event("ui.selection", screen="tool_picker", control="tool", value=event.option.id)
        self.exit(event.option.id)
