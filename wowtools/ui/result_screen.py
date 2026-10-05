"""The result screen every tool shows after a run, a dry run or an undo: an Item/Value summary table above one
detail table, a row of buttons (Rescan first, then Other flavor, Tools and Quit) and the result hint. Spec D9.

ResultBase holds the layout, the keys and the logging; a tool screen fills the two tables (fill_summary,
fill_detail). ResultScreen is the generic one, built from rows, whose last detail cell is a status coloured by
its first words. status_style() and status_colour() colour a status cell the same way on every result screen."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
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

# (label, action kind, id = dismiss value, hint words) of the buttons after a result screen's own ones.
NAV_BUTTONS = (("Other flavor (f)", "navigate", "flavors", "f other flavor"),
               ("Tools (t)", "navigate", "tools", "t tools"),
               ("Quit (q)", "cancel", "quit", "q quit"))
ResultButton = tuple[str, str, str, str]


def result_bindings(rescan: str, *, before: Sequence[Binding] = (), after: Sequence[Binding] = ()) -> list[Binding]:
    """A result screen's keys: `before`, r (dismisses with `rescan`), `after`, f, t, q, then Esc (action_escape)
    and the navigation keys. Every result screen sets BINDINGS from this (ResultBase has none: Textual would put
    the base's keys before a screen's own in the footer)."""
    return [*before, Binding("r", f"choose('{rescan}')", "Rescan"), *after,
            Binding("f", "choose('flavors')", "Flavors"), Binding("t", "choose('tools')", "Tools"),
            Binding("q", "choose('quit')", "Quit"), Binding("escape", "escape", "Back", show=False),
            *NAV_BINDINGS]


def status_colour(status: str, colours: Mapping[str, str] | Iterable[tuple[str, str]], *,
                  prefix: bool = False) -> str | None:
    """The theme colour name ("success", "warning", ...) for a status: looked up whole in a mapping, or with
    prefix=True the first (start, colour) pair whose start the status begins with."""
    if prefix:
        pairs = colours.items() if isinstance(colours, Mapping) else colours
        return next((colour for start, colour in pairs if status.startswith(start)), None)
    table = colours if isinstance(colours, Mapping) else dict(colours)
    return table.get(status)


def status_style(app, colour: str | None, *, plain: str = "bold") -> str:
    """A status cell's style: bold in the running theme's `colour`, or `plain` when there is none."""
    return f"bold {theme_colour(app, colour)}" if colour else plain


class ResultBase(Screen[str]):
    """A result screen's layout and keys. Subclasses set BINDINGS = result_bindings(RESCAN, ...), and may set
    LOG_SCREEN (the ui.selection event's screen), DETAIL_ID (the detail table's id) and RESCAN (the Rescan
    button's id and dismiss value). They fill the tables in fill_summary / fill_detail and set result_title()
    (the sub-title). lead_buttons() go before Rescan, extra_buttons() after it."""

    DEFAULT_CSS = result_css("ResultBase")
    LOG_SCREEN = "result"
    DETAIL_ID = "result-detail"
    RESCAN = "rescan"

    def result_title(self) -> str:
        raise NotImplementedError

    def summary_rows(self) -> list[tuple[str, str]]:
        return []

    def fill_summary(self, summary: DataTable) -> None:
        summary.add_rows((Text(item), Text(value)) for item, value in self.summary_rows())

    def fill_detail(self, detail: DataTable) -> None:
        raise NotImplementedError

    def summary_focusable(self) -> bool:
        """A read-only summary is not a focus stop; one that can outgrow its height takes focus to scroll."""
        return False

    def lead_buttons(self) -> list[ResultButton]:
        return []

    def extra_buttons(self) -> list[ResultButton]:
        return []

    def buttons(self) -> list[ResultButton]:
        return [*self.lead_buttons(), ("Rescan (r)", "navigate", self.RESCAN, "r rescan"), *self.extra_buttons(),
                *NAV_BUTTONS]

    def focus_id(self) -> str:
        return self.RESCAN

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="result"):
            summary = DataTable(id="result-summary", cursor_type="none", zebra_stripes=True)
            summary.can_focus = self.summary_focusable()
            yield summary
            yield DataTable(id=self.DETAIL_ID, classes="result-detail", cursor_type="row", zebra_stripes=True)
        buttons = self.buttons()
        with ButtonRow(classes="buttons"):
            for label, kind, button_id, _ in buttons:
                yield action_button(label, kind, id=button_id)
        yield NavHint(RESULT_HINT + " · ".join(words for *_, words in buttons if words))
        yield BrandBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self.result_title()
        summary = self.query_one("#result-summary", DataTable)
        summary.add_columns("Item", "Value")
        self.fill_summary(summary)
        self.fill_detail(self.query_one(f"#{self.DETAIL_ID}", DataTable))
        self.query_one(f"#{self.focus_id()}", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_choose(event.button.id or "quit")

    def action_escape(self) -> None:
        self.action_choose(self.RESCAN)

    def action_choose(self, choice: str) -> None:
        log_event("ui.selection", screen=self.LOG_SCREEN, control="next", value=choice)
        self.dismiss(choice)


class ResultScreen(ResultBase):
    """A result built from rows: `summary_rows` (item, value), the detail table's `columns` and `detail_rows`,
    whose last cell is a status coloured by STATUS_COLOURS (prefix match). Dismisses with RESCAN, "flavors",
    "tools" or "quit"; with `back` (nothing was written, the work is still pending: a dry run) it opens on
    "Back to review", and Esc dismisses with "back"."""

    BINDINGS: ClassVar[list[Binding]] = result_bindings("rescan")
    # (first words of a status, theme colour name)
    STATUS_COLOURS: ClassVar[Sequence[tuple[str, str]]] = ()

    def __init__(self, sub_title: str, summary_rows: list[tuple[str, str]], columns: tuple[str, ...],
                 detail_rows: list[tuple], *, back: bool = False) -> None:
        super().__init__()
        self.back = back
        self.sub_title_text = sub_title
        self.rows = list(summary_rows)
        self.columns = tuple(columns)
        self.detail_rows = list(detail_rows)

    def result_title(self) -> str:
        return self.sub_title_text

    def summary_rows(self) -> list[tuple[str, str]]:
        return self.rows

    def extra_buttons(self) -> list[ResultButton]:
        return [("Back to review (Esc)", "navigate", "back", "")] if self.back else []

    def focus_id(self) -> str:
        return "back" if self.back else self.RESCAN

    def fill_detail(self, detail: DataTable) -> None:
        detail.add_columns(*self.columns)
        for row in self.detail_rows:
            *cells, status = (str(c) for c in row)
            colour = status_colour(status, self.STATUS_COLOURS, prefix=True)
            detail.add_row(*(Text(c) for c in cells), Text(status, style=status_style(self.app, colour)))

    def action_escape(self) -> None:
        self.action_choose("back" if self.back else self.RESCAN)
