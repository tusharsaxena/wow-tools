"""The outcome of an Apply, a dry run or Undo last change: an Item/Value summary, one detail table and what to do
next."""
from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header

from wowtools.core.events import log_event
from wowtools.ui.branding import BrandBar
from wowtools.ui.dialogs import RESULT_HINT, result_css, theme_colour
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

# Theme colour of a detail row's last cell, by its first words (report.RESULT_TEXT and the undo statuses).
STATUS_COLOURS = (("would change", "accent"), ("changed", "success"), ("restored", "success"),
                  ("put back", "warning"), ("skipped", "warning"), ("failed", "error"))


class ProfileResultScreen(Screen[str]):
    """`title` is "Apply", "Dry run" or "Undo". Dismisses with "rescan", "flavors", "tools" or "quit"."""

    DEFAULT_CSS = result_css("ProfileResultScreen")
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("r", "choose('rescan')", "Rescan"), Binding("f", "choose('flavors')", "Flavors"),
        Binding("t", "choose('tools')", "Tools"), Binding("q", "choose('quit')", "Quit"),
        Binding("escape", "choose('rescan')", "Back", show=False),
        *NAV_BINDINGS,
    ]

    def __init__(self, title: str, summary_rows: list[tuple[str, str]], columns: tuple[str, ...],
                 detail_rows: list[tuple], scope_label: str) -> None:
        super().__init__()
        self.title_text = title
        self.summary_rows = list(summary_rows)
        self.columns = tuple(columns)
        self.detail_rows = list(detail_rows)
        self.scope_label = scope_label

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="result"):
            summary = DataTable(id="result-summary", cursor_type="none", zebra_stripes=True)
            summary.can_focus = False  # read-only summary: not a focus stop
            yield summary
            yield DataTable(id="result-detail", classes="result-detail", cursor_type="row", zebra_stripes=True)
        with ButtonRow(classes="buttons"):
            yield action_button("Rescan (r)", "neutral", id="rescan")
            yield action_button("Other flavor (f)", "neutral", id="flavors")
            yield action_button("Tools (t)", "neutral", id="tools")
            yield action_button("Quit (q)", "neutral", id="quit")
        yield NavHint(RESULT_HINT + "r rescan · f other flavor · t tools · q quit")
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"Ace3 Profile Manager · {self.scope_label} · {self.title_text} result"
        summary = self.query_one("#result-summary", DataTable)
        summary.add_columns("Item", "Value")
        summary.add_rows((Text(item), Text(value)) for item, value in self.summary_rows)
        detail = self.query_one("#result-detail", DataTable)
        detail.add_columns(*self.columns)
        for row in self.detail_rows:
            *cells, status = (str(c) for c in row)
            detail.add_row(*(Text(c) for c in cells), Text(status, style=self._status_style(status)))
        self.query_one("#rescan", Button).focus()

    def _status_style(self, status: str) -> str:
        name = next((colour for prefix, colour in STATUS_COLOURS if status.startswith(prefix)), None)
        return f"bold {theme_colour(self.app, name)}" if name else "bold"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_choose(event.button.id or "quit")

    def action_choose(self, choice: str) -> None:
        log_event("ui.selection", screen="ace_result", control="next", value=choice)
        self.dismiss(choice)
