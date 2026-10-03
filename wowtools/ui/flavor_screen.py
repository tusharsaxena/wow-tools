"""Choose which WoW flavor (_retail_, _classic_era_, ...) to work on."""
from __future__ import annotations

from typing import Union

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

ALL_FLAVORS = "__all__"  # dismiss value for the "All flavors" entry (include_all=True only)


class FlavorScreen(Screen[Union[Flavor, str, None]]):
    """Dismisses with a Flavor, with ALL_FLAVORS (only when include_all), or with None (Esc).

    flavors overrides install.flavors() (e.g. only flavors with a Screenshots folder); last is the folder to
    highlight ("" means "All flavors"), and None falls back to [general] last_flavor."""
    DEFAULT_CSS = """
    FlavorScreen .title { color: $accent; text-style: bold; padding: 0 2; }
    FlavorScreen NavHint { padding: 0 2; }
    FlavorScreen OptionList { margin: 1 2; height: auto; max-height: 20; border: tall $primary; }
    """
    BINDINGS = [Binding("escape", "cancel", "Tools"), *NAV_BINDINGS]

    def __init__(self, cfg: Config, install: WowInstall, *, include_all: bool = False, last: str | None = None,
                 flavors: list[Flavor] | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.flavors = install.flavors() if flavors is None else list(flavors)
        self.include_all = include_all
        self.last = cfg.last_flavor if last is None else last

    def compose(self) -> ComposeResult:
        options = [Option(Text(f"{f.display_name}  ({f.folder})"), id=f.folder) for f in self.flavors]
        if self.include_all:
            options.insert(0, Option(Text.assemble(("All flavors", "bold"), f"  ({len(self.flavors)})"),
                                     id=ALL_FLAVORS))
        yield Header()
        yield Banner()
        yield Static("Choose a WoW flavor", classes="title")
        yield OptionList(*options, id="flavors")
        yield NavHint("↑↓ choose · Enter select · Esc back to tools")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Choose flavor"
        options = self.query_one("#flavors", OptionList)
        ids = ([ALL_FLAVORS] if self.include_all else []) + [f.folder for f in self.flavors]
        wanted = ALL_FLAVORS if self.include_all and self.last == "" else self.last
        options.highlighted = ids.index(wanted) if wanted in ids else 0
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == ALL_FLAVORS:
            log_event("ui.selection", screen="flavor", control="flavor", value="all")
            self.dismiss(ALL_FLAVORS)
            return
        flavor = next(f for f in self.flavors if f.folder == event.option.id)
        self.cfg.set(GENERAL, "last_flavor", flavor.folder)
        self.cfg.save_if_exists()
        log_event("ui.selection", screen="flavor", control="flavor", value=flavor.folder)
        self.dismiss(flavor)

    def action_cancel(self) -> None:
        self.dismiss(None)
