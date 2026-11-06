"""The diff of one replaced (target, file) pair (config tools spec CC4, CC5; feedback round 1 CP4): the target's file as
it is against what the copy gives it, side by side: the file as it is on the left, what it gets on the right, each
with its own line numbers, removed lines white on red on the left, added white on green on the right, a changed run
paired row by row; three lines of context around each change, `…` between two parts, a long line cut with `…` so the
two sides stay row-aligned, a removed or added line's number marked - / + so the change reads without colour. A
config-cache.wtf shows the whole file, its state lines marked kept (the target's own, CC5; the head says so once).
`diff_text` is the unified (inline) view of the same lines: `v` (and View) switches between the two. The view chosen
with `v` lasts the tool's session (`DiffSession`, held by the flow), not saved; with none chosen, a window under
NARROW_WIDTH columns opens the diff inline and the head says so. The width is read on open only. Read-only; Back
(Esc) returns to the review."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Header, Static

from wowtools.core.events import log_event
from wowtools.core.text import plural
from wowtools.tools.config_copier.model import CONFIG_FILE, PairPlan
from wowtools.tools.config_copier.report import (BYTES_ONLY, GAP, SideRow, bytes_only, character_text, diff_rows,
                                                 pair_text, side_by_side_rows)
from wowtools.ui.branding import BottomBar
from wowtools.ui.theme import DIFF_ADDED_BACKGROUND, DIFF_REMOVED_BACKGROUND, DIFF_TEXT
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

NAV_HINT = "↑↓ PgUp/PgDn scroll · Tab move"  # v is on the View button only (STD-8.6)
SAME = "The files are the same."
SEPARATOR = "│"  # between the two sides
KEPT_MARK = "kept"  # the side view's short note on a config-cache.wtf state line (the head line explains it)
SIDE, INLINE = "side", "inline"  # the two views
NARROW_WIDTH = 100  # under it (two sides of under about 45 cells each) a diff opens inline, unless v chose a view
NARROW_NOTE = "opened inline: the window is narrow"  # the head's note when the width rule chose inline


@dataclass
class DiffSession:
    """The diff view the user chose with `v` this session (SIDE or INLINE), or None: the width rule picks. The
    tool's flow holds one, so the choice carries to the next diff and to a new review (Change source), and is gone
    once the tool is closed (spec CP4: not a setting)."""
    view: str | None = None


class DiffScreen(Screen[None]):
    DEFAULT_CSS = """
    DiffScreen #diff-box { height: 1fr; padding: 0 1; }
    DiffScreen #diff-head { height: auto; margin-bottom: 1; }
    DiffScreen #diff-scroll { height: 1fr; border: tall $primary; }
    DiffScreen .buttons { height: auto; margin: 1 1 0 1; }
    DiffScreen NavHint { padding: 0 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "close", "Back", show=False),
                                         Binding("v", "switch_view", "View", show=False), *NAV_BINDINGS]
    LOG_SCREEN = "copier_diff"

    def __init__(self, plan: PairPlan, source_text: str, session: DiffSession | None = None) -> None:
        super().__init__()
        self.plan = plan
        self.source_text = source_text
        self.session = session if session is not None else DiffSession()
        self.rows = diff_rows(plan)
        self.side_rows = side_by_side_rows(plan)
        self.view = SIDE
        self.narrow = False  # the width rule chose inline (the head's note)

    def head_text(self) -> Text:
        removed = sum(mark == "-" for mark, _, _ in self.rows)
        added = sum(mark == "+" for mark, _, _ in self.rows)
        line = (f"{self.plan.name} of {character_text(self.plan.target)}: {pair_text(self.plan)} from "
                f"{self.source_text}. {plural(removed, 'line')} removed, {plural(added, 'line')} added.")
        if self.plan.name == CONFIG_FILE:
            kept = sum(bool(note) for _, _, note in self.rows)
            line += f" {plural(kept, 'state line')} kept as they are, the target's own (marked {KEPT_MARK})."
        text = Text(line)
        if self.narrow:
            text.append(f"\n{NARROW_NOTE}", style="dim italic")
        return text

    @staticmethod
    def _styles() -> dict[str, str]:
        """A removed or added line: white on a darker red or green (GitHub's look), filled to its column's edge."""
        return {"-": f"{DIFF_TEXT} on {DIFF_REMOVED_BACKGROUND}", "+": f"{DIFF_TEXT} on {DIFF_ADDED_BACKGROUND}"}

    @staticmethod
    def _filled(text: Text, style: str, right: int = 0) -> RenderableType:
        """`text` with its background carried to the edge of its cell (a bare Text colours only its characters), and
        `right` blank cells after it in the same background."""
        return Padding(text, (0, right, 0, 0), style=style, expand=True) if style or right else text

    def _end_line(self) -> Text | None:
        """The dim line under (or instead of) the diff: only bytes differ, or the files are the same."""
        if bytes_only(self.plan):
            return Text(BYTES_ONLY, style="dim")
        return None if self.rows else Text(SAME, style="dim")

    def side_view(self) -> RenderableType:
        """The side-by-side diff (CP4): a grid of left number, left line, separator, right number, right line and,
        for a config-cache.wtf, a short dim `kept` column. Each line is one row, cut at its end with … (never wrapped),
        so old line i stays beside new line i; the two line columns share the width left equally."""
        styles = self._styles()
        # No grid padding: the spaces live inside the cells, so a coloured row has no navy gap between its number
        # and its line (the colour runs from the number to the column's edge, as on GitHub).
        table = Table.grid(expand=True)
        for side in range(2):
            if side:
                table.add_column(no_wrap=True, style="dim")  # the separator
            table.add_column(justify="right", no_wrap=True)
            table.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        notes = any(row.note for row in self.side_rows)
        if notes:
            table.add_column(no_wrap=True, style="dim italic")
        for row in self.side_rows:
            table.add_row(*self._side_cells(row, styles), *([f" {KEPT_MARK}" if row.note else ""] if notes else []))
        closing = self._end_line()
        if closing is None:
            return table
        if not self.side_rows:
            return closing
        return Group(table, Text(), closing)

    @staticmethod
    def _side_cells(row: SideRow, styles: dict[str, str]) -> list[RenderableType]:
        separator = Text(f" {SEPARATOR} ")
        if row.left_mark == GAP:
            return [Text(f"{GAP} ", style="dim"), Text(""), separator, Text(f"{GAP} ", style="dim"), Text("")]
        cells: list[RenderableType] = []
        for number, line, mark in ((row.left_no, row.left, row.left_mark), (row.right_no, row.right, row.right_mark)):
            if cells:
                cells.append(separator)
            style = styles.get(mark, "")
            prefix = mark if mark in styles else ""  # - or + beside the number of a removed or added line
            shown = "" if number is None else f"{prefix}{number}"
            cells += [DiffScreen._filled(Text(shown, style=style or "dim", justify="right"), style, right=1),
                      DiffScreen._filled(Text(line, style=style, no_wrap=True, overflow="ellipsis"), style)]
        return cells

    def diff_text(self) -> Text:
        """The unified (inline) diff, one row per line: its mark, the line and, dim, its note."""
        styles = self._styles()
        text = Text()
        for index, (mark, line, note) in enumerate(self.rows):
            if index:
                text.append("\n")
            text.append(f"{mark} {line}".rstrip() if mark != " " else f"  {line}", style=styles.get(mark, ""))
            if note:
                text.append(f"    ({note})", style="dim italic")
        closing = self._end_line()
        if closing is not None:
            text.append("\n\n" if self.rows else "")
            text.append(closing)
        return text

    def inline_view(self) -> RenderableType:
        """diff_text drawn line by line, a removed or added line's background filled to the pane's edge."""
        styles = self._styles()
        lines = self.diff_text().split("\n", allow_blank=True)
        marks = [mark for mark, _, _ in self.rows]
        return Group(*(self._filled(line, styles.get(marks[index], "") if index < len(marks) else "")
                       for index, line in enumerate(lines)))

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="diff-box"):
            yield Static(self.head_text(), id="diff-head")
            with VerticalScroll(id="diff-scroll"):
                yield Static(id="diff")
        with ButtonRow(classes="buttons"):
            yield action_button("Back", "cancel", "escape", id="btn-back")
            yield action_button("View", "navigate", "v", id="btn-view")
        yield NavHint(NAV_HINT)
        yield BottomBar()

    def on_mount(self) -> None:
        self.sub_title = f"Config Copier · diff · {self.plan.name}"
        chosen = self.session.view
        self.narrow = chosen is None and self.app.size.width < NARROW_WIDTH  # the width on open only
        self._show(chosen or (INLINE if self.narrow else SIDE))

    def _show(self, view: str) -> None:
        """Draw `view` from its top: the two views have different row counts (inline lists a replaced run's lines one
        after the other), so the old scroll offset would land on unrelated lines."""
        self.view = view
        self.query_one("#diff-head", Static).update(self.head_text())
        self.query_one("#diff", Static).update(self.side_view() if view == SIDE else self.inline_view())
        scroll = self.query_one("#diff-scroll", VerticalScroll)
        scroll.scroll_home(animate=False)
        scroll.focus()

    def action_switch_view(self) -> None:
        """v: side by side <-> inline; the choice lasts the session and drops the width rule's note."""
        view = INLINE if self.view == SIDE else SIDE
        self.session.view = view
        self.narrow = False
        log_event("ui.selection", screen=self.LOG_SCREEN, control="view", value=view)
        self._show(view)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            event.stop()
            self.action_close()
        elif event.button.id == "btn-view":
            event.stop()
            self.action_switch_view()

    def action_close(self) -> None:
        self.dismiss(None)
