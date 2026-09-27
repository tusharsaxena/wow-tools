"""Choose which WoW account of a flavor to work on, or all of them."""
from __future__ import annotations

from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from wowtools.core.config import Config
from wowtools.core.events import log_event
from wowtools.core.install import Flavor
from wowtools.ui.branding import Banner, BrandBar

ALL_ID = "__all__"


class AccountScreen(Screen[Optional[str]]):
    """Dismisses with the account name, "" for all accounts, or None to go back."""

    DEFAULT_CSS = """
    AccountScreen .title { color: $accent; text-style: bold; padding: 0 2; }
    AccountScreen OptionList { margin: 1 2; height: auto; max-height: 20; border: tall $primary; }
    """
    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self, cfg: Config, flavor: Flavor, last: str | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.flavor = flavor
        self.last = last
        self.accounts = sorted((a.name for a in flavor.accounts()), key=str.casefold)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Banner()
        yield Static(f"Choose an account ({self.flavor.display_name})", classes="title")
        yield OptionList(Option(Text("All accounts"), id=ALL_ID),
                         *[Option(Text(name), id=name) for name in self.accounts], id="accounts")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"{self.flavor.display_name} · choose account"
        options = self.query_one("#accounts", OptionList)
        folded = [name.casefold() for name in self.accounts]
        last = (self.last or "").casefold()
        options.highlighted = folded.index(last) + 1 if last in folded else 0
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        choice = "" if event.option.id == ALL_ID else (event.option.id or "")
        log_event("ui.selection", screen="account", control="account", value=choice or None)
        self.dismiss(choice)

    def action_back(self) -> None:
        self.dismiss(None)
