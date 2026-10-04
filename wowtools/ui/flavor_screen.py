"""Choose which WoW flavor (_retail_, _classic_era_, ...) to work on."""
from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

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
from wowtools.ui.widgets import LIST_CURSOR_BACKGROUND, LIST_NAME_STYLE, NAV_BINDINGS, NavHint

ALL_FLAVORS = "__all__"  # dismiss value for the "All flavors" entry (include_all=True only)


COLUMN_GAP = 3


def flavor_rows(rows: list[tuple[str, str, str]]) -> list[Text]:
    """Pick-list rows as three aligned columns (name, folder, remark), like the tool menu: each column is as wide
    as its longest entry plus a gap. Nothing is drawn between them."""
    name_width = max(len(name) for name, _, _ in rows) + COLUMN_GAP
    folder_width = max(len(folder) for _, folder, _ in rows) + COLUMN_GAP
    return [Text.assemble((name.ljust(name_width), LIST_NAME_STYLE),
                          folder.ljust(folder_width) if remark else folder, (remark, "dim"))
            for name, folder, remark in rows]


class FlavorScreen(Screen[Flavor | str | None]):
    """Dismisses with a Flavor, with ALL_FLAVORS (only when include_all), or with None (Esc).

    flavors overrides install.flavors(); last is the folder to highlight ("" means "All flavors"), and None falls
    back to [general] last_flavor. note(flavor) may return a short remark for a flavor's third column (e.g.
    "12 screenshots to file"), and all_note the remark for the "All flavors" row."""
    DEFAULT_CSS = f"""
    FlavorScreen .title {{ color: $accent; text-style: bold; padding: 0 2; }}
    FlavorScreen NavHint {{ padding: 0 2; }}
    FlavorScreen OptionList {{ margin: 1 2; height: auto; max-height: 20; border: tall $primary; }}
    FlavorScreen OptionList > .option-list--option-highlighted {{ background: {LIST_CURSOR_BACKGROUND}; }}
    FlavorScreen OptionList:focus > .option-list--option-highlighted {{ background: {LIST_CURSOR_BACKGROUND}; }}
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "Tools"), *NAV_BINDINGS]

    def __init__(self, cfg: Config, install: WowInstall, *, include_all: bool = False, last: str | None = None,
                 flavors: list[Flavor] | None = None, note: Callable[[Flavor], str | None] | None = None,
                 all_note: str | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.flavors = install.flavors() if flavors is None else list(flavors)
        self.include_all = include_all
        self.last = cfg.last_flavor if last is None else last
        self.note = note
        self.all_note = all_note

    def _rows(self) -> tuple[list[str], list[Text]]:
        ids = [f.folder for f in self.flavors]
        rows = [(f.display_name, f"({f.folder})", (self.note(f) if self.note else None) or "") for f in self.flavors]
        if self.include_all:
            ids.insert(0, ALL_FLAVORS)
            count = len(self.flavors)
            rows.insert(0, ("All flavors", f"({count} flavor{'' if count == 1 else 's'})", self.all_note or ""))
        return ids, flavor_rows(rows) if rows else []

    def set_notes(self, note: Callable[[Flavor], str | None] | None, all_note: str | None = None) -> None:
        """Replace the remarks column (e.g. once counts worked out in the background are ready). The highlighted
        row stays where it is."""
        self.note = note
        self.all_note = all_note
        options = self.query_one("#flavors", OptionList)
        for option_id, label in zip(*self._rows()):
            options.replace_option_prompt(option_id, label)

    def compose(self) -> ComposeResult:
        ids, labels = self._rows()
        options = [Option(label, id=option_id) for option_id, label in zip(ids, labels)]
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
