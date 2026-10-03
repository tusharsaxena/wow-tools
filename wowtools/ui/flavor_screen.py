"""Choose which WoW flavor (_retail_, _classic_era_, ...) to work on."""
from __future__ import annotations

from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from wowtools.core.config import GENERAL, Config
from wowtools.core.events import log_event
from wowtools.core.install import Flavor, WowInstall
from wowtools.ui.branding import Banner, BrandBar
from wowtools.ui.widgets import NAV_BINDINGS, NavHint


class FlavorScreen(Screen[Optional[Flavor]]):
    DEFAULT_CSS = """
    FlavorScreen .title { color: $accent; text-style: bold; padding: 0 2; }
    FlavorScreen NavHint { padding: 0 2; }
    FlavorScreen OptionList { margin: 1 2; height: auto; max-height: 20; border: tall $primary; }
    """
    BINDINGS = [Binding("escape", "cancel", "Tools"), *NAV_BINDINGS]

    def __init__(self, cfg: Config, install: WowInstall) -> None:
        super().__init__()
        self.cfg = cfg
        self.flavors = install.flavors()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Banner()
        yield Static("Choose a WoW flavor", classes="title")
        yield OptionList(*[Option(Text(f"{f.display_name}  ({f.folder})"), id=f.folder) for f in self.flavors],
                         id="flavors")
        yield NavHint("↑↓ choose · Enter select · Esc back to tools")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Choose flavor"
        options = self.query_one("#flavors", OptionList)
        folders = [f.folder for f in self.flavors]
        options.highlighted = folders.index(self.cfg.last_flavor) if self.cfg.last_flavor in folders else 0
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        flavor = next(f for f in self.flavors if f.folder == event.option.id)
        self.cfg.set(GENERAL, "last_flavor", flavor.folder)
        self.cfg.save_if_exists()
        log_event("ui.selection", screen="flavor", control="flavor", value=flavor.folder)
        self.dismiss(flavor)

    def action_cancel(self) -> None:
        self.dismiss(None)
