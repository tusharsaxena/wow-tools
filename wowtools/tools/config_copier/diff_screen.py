"""The diff of one replaced (target, file) pair (config tools spec CC4, CC5): the target's file as it is against what
the copy gives it, unified (one column fits 80x24): `-` lines it loses, `+` lines it gets, three lines of context
around each change, `…` between two parts. A config-cache.wtf shows the whole file, its state lines marked kept (the
target's own, CC5). Read-only; Back (Esc) returns to the review."""
from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Header, Static

from wowtools.core.text import plural
from wowtools.tools.config_copier.model import CONFIG_FILE, PairPlan
from wowtools.tools.config_copier.report import BYTES_ONLY, bytes_only, character_text, diff_rows, pair_text
from wowtools.ui.branding import BottomBar
from wowtools.ui.dialogs import theme_colour
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

NAV_HINT = "↑↓ PgUp/PgDn scroll · Tab move"


class DiffScreen(Screen[None]):
    DEFAULT_CSS = """
    DiffScreen #diff-box { height: 1fr; padding: 0 1; }
    DiffScreen #diff-head { height: auto; margin-bottom: 1; }
    DiffScreen #diff-scroll { height: 1fr; border: tall $primary; }
    DiffScreen .buttons { height: auto; margin: 1 1 0 1; }
    DiffScreen NavHint { padding: 0 1; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "close", "Back", show=False), *NAV_BINDINGS]

    def __init__(self, plan: PairPlan, source_text: str) -> None:
        super().__init__()
        self.plan = plan
        self.source_text = source_text
        self.rows = diff_rows(plan)

    def head_text(self) -> Text:
        removed = sum(mark == "-" for mark, _, _ in self.rows)
        added = sum(mark == "+" for mark, _, _ in self.rows)
        line = (f"{self.plan.name} of {character_text(self.plan.target)}: {pair_text(self.plan)} from "
                f"{self.source_text}. {plural(removed, 'line')} removed, {plural(added, 'line')} added.")
        if self.plan.name == CONFIG_FILE:
            kept = sum(bool(note) for _, _, note in self.rows)
            line += f" {plural(kept, 'state line')} kept as they are."
        return Text(line)

    def diff_text(self) -> Text:
        """The diff, one row per line: its mark, the line and, dim, its note."""
        styles = {"-": f"bold {theme_colour(self.app, 'error')}", "+": f"bold {theme_colour(self.app, 'success')}"}
        text = Text()
        for index, (mark, line, note) in enumerate(self.rows):
            if index:
                text.append("\n")
            text.append(f"{mark} {line}".rstrip() if mark != " " else f"  {line}", style=styles.get(mark, ""))
            if note:
                text.append(f"    ({note})", style="dim italic")
        if bytes_only(self.plan):
            text.append(f"\n\n{BYTES_ONLY}" if self.rows else BYTES_ONLY, style="dim")
        elif not self.rows:
            text.append("The files are the same.", style="dim")
        return text

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="diff-box"):
            yield Static(self.head_text(), id="diff-head")
            with VerticalScroll(id="diff-scroll"):
                yield Static(id="diff")
        with ButtonRow(classes="buttons"):
            yield action_button("Back", "cancel", "escape", id="btn-back")
        yield NavHint(NAV_HINT)
        yield BottomBar()

    def on_mount(self) -> None:
        self.sub_title = f"Config Copier · diff · {self.plan.name}"
        self.query_one("#diff", Static).update(self.diff_text())
        self.query_one("#diff-scroll").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            event.stop()
            self.action_close()

    def action_close(self) -> None:
        self.dismiss(None)
