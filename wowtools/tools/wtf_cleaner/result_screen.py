"""The outcome of a clean or dry run, for one flavor or several, or of Undo last clean: a summary table and a
per-file table."""
from __future__ import annotations

from typing import ClassVar


from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header

from wowtools.core.events import log_event
from wowtools.core.install import Flavor
from wowtools.tools.wtf_cleaner.cleaner import CleanResult
from wowtools.tools.wtf_cleaner.multi import FlavorRun, MultiCleanResult, nothing_deleted
from wowtools.tools.wtf_cleaner.report import (CRITERION_COLORS, MULTI_RESULT_COLUMNS, RESULT_COLUMNS, UNDO_COLUMNS,
                                               format_size, multi_result_rows, result_rows, undo_row,
                                               undo_summary_rows)
from wowtools.tools.wtf_cleaner.undo import UndoResult
from wowtools.ui.dialogs import theme_colour
from wowtools.ui.widgets import NAV_BINDINGS, ButtonRow, NavHint, action_button

BLOCK_STYLE = "bold #5CC8FF"
# Theme colour per file status in the result table.
STATUS_COLOURS = {"deleted": "success", "restored": "success", "would_delete": "accent", "skipped": "warning",
                  "failed": "error"}


def reasons_text(reasons: list[str]) -> Text:
    """Reasons, comma separated, each in its criterion's colour."""
    text = Text()
    for index, reason in enumerate(reasons):
        if index:
            text.append(", ")
        text.append(reason, style=CRITERION_COLORS.get(reason, ""))
    return text


def summary_rows(result: CleanResult) -> list[tuple[str, str]]:
    """The summary of one flavor's clean or dry run."""
    done = result.would_delete if result.dry_run else result.deleted
    if result.dry_run:
        snapshot, check = "not taken (dry run)", "not run (dry run)"
    elif result.snapshot_path is None:
        snapshot, check = "not taken", "not run"
    else:
        snapshot = str(result.snapshot_path)
        if result.pruned:
            snapshot += f" ({len(result.pruned)} older backups removed)"
        check = "passed"
        if result.check_problems:
            check = (f"{len(result.check_problems)} problems: {result.check_problems[0]}"
                     + (" (more in the log)" if len(result.check_problems) > 1 else ""))
    rows = [
        ("Mode", "Dry run" if result.dry_run else "Clean"),
        ("Cleaned files zip", str(result.backup_path) if result.backup_path else "none (turned off in settings)"),
        ("WTF backup", snapshot),
        ("Post-clean check", check),
        ("Would delete" if result.dry_run else "Deleted", f"{len(done)} files"),
        ("Size", format_size(result.bytes_freed)),
        ("Skipped", f"{len(result.skipped)} files (changed or missing since the scan)"),
        ("Failed", f"{len(result.failed)} files"),
    ]
    if result.journal_path is not None:
        rows.insert(4, ("Run journal", f"{result.journal_path} (Undo last clean (z) puts these files back)"))
    return rows


def multi_summary_rows(result: MultiCleanResult) -> list[tuple[str, str, bool]]:
    """(item, value, is a flavor heading): which flavors ran, then one block of rows per finished flavor."""
    def names(runs: list[FlavorRun]) -> str:
        return ", ".join(r.flavor.display_name for r in runs) or "none"

    rows: list[tuple[str, str, bool]] = []
    stopped = result.stopped
    if stopped is not None:
        rows.append(("Done", names(result.done), False))
        suffix = " (nothing deleted there)" if nothing_deleted(stopped.error) else ""
        rows.append(("Stopped", f"{stopped.flavor.display_name}: {stopped.error}{suffix}", False))
        if result.not_started:
            rows.append(("Not started", names(result.not_started), False))
    if result.journal_path is not None:
        rows.append(("Run journal", str(result.journal_path), False))
    for run in result.done:
        rows.append((run.flavor.display_name, "", True))
        rows += [(item, value, False) for item, value in summary_rows(run.result)]  # type: ignore[arg-type]
    return rows


class ResultScreen(Screen[str]):
    """The outcome of a clean or dry run: a summary table, a per-file table and what to do next. `result` is a
    CleanResult (with its flavor), a MultiCleanResult (several flavors: one summary block each, and a Flavor
    column) or an UndoResult (Undo last clean: the same layout, titled "undo result")."""

    DEFAULT_CSS = """
    ResultScreen #result { height: 1fr; padding: 1 2; }
    ResultScreen #result-summary { height: auto; max-height: 50%; margin-bottom: 1; }
    ResultScreen #result-files { height: 1fr; }
    ResultScreen .buttons { height: auto; padding: 0 2; }
    ResultScreen Button { margin-right: 2; }
    ResultScreen NavHint { padding: 0 2; margin-top: 0; }
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("r", "choose('review')", "Rescan"), Binding("f", "choose('flavors')", "Flavors"),
                Binding("t", "choose('tools')", "Tools"), Binding("q", "choose('quit')", "Quit"),
                Binding("escape", "choose('review')", "Back", show=False),
                *NAV_BINDINGS]

    def __init__(self, result: CleanResult | MultiCleanResult | UndoResult, flavor: Flavor | None = None) -> None:
        super().__init__()
        self.result = result
        self.flavor = flavor

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="result"):
            summary = DataTable(id="result-summary", cursor_type="none", zebra_stripes=True)
            # Read-only summary: not a focus stop for one flavor. With several flavors it can outgrow its 50%
            # cap, so it takes focus there and the arrow keys scroll it (no cursor).
            summary.can_focus = isinstance(self.result, MultiCleanResult)
            yield summary
            yield DataTable(id="result-files", cursor_type="row", zebra_stripes=True)
        with ButtonRow(classes="buttons"):
            yield action_button("Rescan (r)", "neutral", id="review")
            yield action_button("Other flavor (f)", "neutral", id="flavors")
            yield action_button("Tools (t)", "neutral", id="tools")
            yield action_button("Quit (q)", "neutral", id="quit")
        yield NavHint("↑↓/Tab move · ←→ buttons · Enter/Space press · Esc back · r rescan · f other flavor · "
                      "t tools · q quit")
        yield Footer()

    def on_mount(self) -> None:
        summary = self.query_one("#result-summary", DataTable)
        summary.add_columns("Item", "Value")
        files = self.query_one("#result-files", DataTable)
        if isinstance(self.result, UndoResult):
            self.sub_title = "WTF Cleaner · undo result"
            summary.add_rows((Text(item), Text(value)) for item, value in undo_summary_rows(self.result))
            files.add_columns(*UNDO_COLUMNS)
            for outcome in self.result.outcomes:
                status, *rest = undo_row(outcome)
                files.add_row(Text(status, style=self._status_style(outcome.status)), *(Text(c) for c in rest))
            self.query_one("#review", Button).focus()
            return
        self.sub_title = "WTF Cleaner · dry run result" if self.result.dry_run else "WTF Cleaner · result"
        if isinstance(self.result, MultiCleanResult):
            summary.add_rows((Text(item, style=BLOCK_STYLE if heading else ""), Text(value))
                             for item, value, heading in multi_summary_rows(self.result))
            files.add_columns(*MULTI_RESULT_COLUMNS)
            outcomes = [outcome for _, outcome in self.result.outcomes]
            rows = multi_result_rows(self.result)
        else:
            assert self.flavor is not None
            summary.add_rows((Text(item), Text(value)) for item, value in self.summary_rows())
            files.add_columns(*RESULT_COLUMNS)
            outcomes = self.result.outcomes
            rows = result_rows(self.result, self.flavor)
        for outcome, row in zip(outcomes, rows):
            status, *middle, _ = row
            files.add_row(Text(status, style=self._status_style(outcome.status)), *(Text(c) for c in middle),
                          reasons_text(list(outcome.reasons)))
        self.query_one("#review", Button).focus()

    def summary_rows(self) -> list[tuple[str, str]]:
        if isinstance(self.result, UndoResult):
            return undo_summary_rows(self.result)
        if isinstance(self.result, MultiCleanResult):
            return [(item, value) for item, value, _ in multi_summary_rows(self.result)]
        return summary_rows(self.result)

    def _status_style(self, status: str) -> str:
        name = STATUS_COLOURS.get(status)
        return f"bold {theme_colour(self.app, name)}" if name else "bold"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_choose(event.button.id or "quit")

    def action_choose(self, choice: str) -> None:
        log_event("ui.selection", screen="result", control="next", value=choice)
        self.dismiss(choice)
