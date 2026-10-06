"""The outcome of a clean or dry run, for one flavor or several, or of Undo last clean: a summary table and a
per-file table."""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.binding import Binding
from textual.widgets import DataTable

from wowtools.core.install import Flavor
from wowtools.core.paths import to_stored
from wowtools.core.text import human_size
from wowtools.tools.wtf_cleaner.cleaner import CleanResult
from wowtools.tools.wtf_cleaner.multi import FlavorRun, MultiCleanResult, nothing_deleted
from wowtools.tools.wtf_cleaner.report import (CRITERION_COLORS, CRITERION_SHORT, MULTI_RESULT_COLUMNS, RESULT_COLUMNS,
                                               UNDO_COLUMNS, multi_result_rows, result_rows, undo_row,
                                               undo_summary_rows)
from wowtools.tools.wtf_cleaner.undo import UndoResult
from wowtools.ui.result_screen import ResultBase, result_bindings, status_colour, status_style

UNDO_NOTE = "(Undo last clean, on the review, puts them back)"
BLOCK_STYLE = "bold #5CC8FF"
# Theme colour per file status in the result table.
STATUS_COLOURS = {"deleted": "success", "restored": "success", "would_delete": "accent", "skipped": "warning",
                  "failed": "error"}


def reasons_text(reasons: list[str]) -> Text:
    """Reasons by their short names ("Not installed"), comma separated, each in its criterion's colour."""
    text = Text()
    for index, reason in enumerate(reasons):
        if index:
            text.append(", ")
        text.append(CRITERION_SHORT.get(reason, reason), style=CRITERION_COLORS.get(reason, ""))
    return text


def _in_backup_folder(path: Path) -> str:
    """A zip's path inside the backup folder ("cleaned/<name>", "backup/<name>"): the folder has a row of its own,
    as a whole path does not fit at 120x30."""
    return str(Path(path.parent.name, path.name))


def journal_text(journal: Path, folder: Path | None) -> str:
    """The run journal's path: inside the backup folder (the default one holds journal/) relative to it, else whole.
    The journal lives in <WoW>/wow-tools/wtf-cleaner/journal, which a backup folder set elsewhere does not hold."""
    if folder is not None and journal.is_relative_to(folder):
        return str(journal.relative_to(folder))
    return to_stored(journal)


def _backup_folder(result: CleanResult) -> Path | None:
    zipped = result.backup_path or result.snapshot_path
    return zipped.parent.parent if zipped is not None else None


def summary_rows(result: CleanResult) -> list[tuple[str, str]]:
    """The summary of one flavor's clean or dry run. Zips are named inside the backup folder, which gets a row of
    its own; the run journal too when it is in there, else by its whole path."""
    done = result.would_delete if result.dry_run else result.deleted
    if result.dry_run:
        snapshot, check = "not taken (dry run)", "not run (dry run)"
    elif result.snapshot_path is None:
        snapshot, check = "not taken", "not run"
    else:
        snapshot = _in_backup_folder(result.snapshot_path)
        if result.pruned:
            snapshot += f" ({len(result.pruned)} older backups removed)"
        check = "passed"
        if result.check_problems:
            check = (f"{len(result.check_problems)} problems: {result.check_problems[0]}"
                     + (" (more in the log)" if len(result.check_problems) > 1 else ""))
    zipped = _in_backup_folder(result.backup_path) if result.backup_path else "none (turned off in settings)"
    if result.cleaned_pruned:
        zipped += f" ({len(result.cleaned_pruned)} older cleaned zips removed)"
    rows = [
        ("Mode", "Dry run" if result.dry_run else "Clean"),
        ("Cleaned files zip", zipped),
        ("WTF backup", snapshot),
    ]
    folder = _backup_folder(result)
    if folder is not None:
        rows.append(("Backup folder", to_stored(folder)))
    rows += [
        ("Post-clean check", check),
        ("Would delete" if result.dry_run else "Deleted", f"{len(done)} files"),
        ("Size", human_size(result.bytes_freed)),
        ("Skipped", f"{len(result.skipped)} files (changed or missing since the scan)"),
        ("Failed", f"{len(result.failed)} files"),
    ]
    if result.journal_path is not None:
        at = rows.index(("Post-clean check", check))
        journal = journal_text(result.journal_path, folder)
        if folder is not None and result.journal_path.is_relative_to(folder):
            rows.insert(at, ("Run journal", f"{journal} {UNDO_NOTE}"))
        else:  # a whole path: the note gets a row of its own, so the journal's row fits at 120x30
            rows[at:at] = [("Run journal", journal), ("", UNDO_NOTE)]
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
        folders = [_backup_folder(run.result) for run in result.done]  # type: ignore[arg-type]
        rows.append(("Run journal", journal_text(result.journal_path, next((f for f in folders if f), None)), False))
    for run in result.done:
        rows.append((run.flavor.display_name, "", True))
        rows += [(item, value, False) for item, value in summary_rows(run.result)]  # type: ignore[arg-type]
    return rows


class ResultScreen(ResultBase):
    """The outcome of a clean or dry run: a summary table, a per-file table and what to do next. `result` is a
    CleanResult (with its flavor), a MultiCleanResult (several flavors: one summary block each, and a Flavor
    column) or an UndoResult (Undo last clean: the same layout, titled "undo result")."""

    RESCAN = "review"
    DETAIL_ID = "result-files"
    BINDINGS: ClassVar[list[Binding]] = result_bindings(RESCAN)

    def __init__(self, result: CleanResult | MultiCleanResult | UndoResult, flavor: Flavor | None = None) -> None:
        super().__init__()
        self.result = result
        self.flavor = flavor

    def summary_focusable(self) -> bool:
        # With several flavors the summary can outgrow its 60% cap: it takes focus there and the arrow keys scroll
        # it (no cursor).
        return isinstance(self.result, MultiCleanResult)

    def result_title(self) -> str:
        if isinstance(self.result, UndoResult):
            return "WTF Cleaner · undo result"
        return "WTF Cleaner · dry run result" if self.result.dry_run else "WTF Cleaner · result"

    def fill_summary(self, summary: DataTable) -> None:
        if isinstance(self.result, MultiCleanResult):
            summary.add_rows((Text(item, style=BLOCK_STYLE if heading else ""), Text(value))
                             for item, value, heading in multi_summary_rows(self.result))
        else:
            super().fill_summary(summary)

    def fill_detail(self, files: DataTable) -> None:
        if isinstance(self.result, UndoResult):
            files.add_columns(*UNDO_COLUMNS)
            for outcome in self.result.outcomes:
                status, *rest = undo_row(outcome)
                files.add_row(Text(status, style=self._status_style(outcome.status)), *(Text(c) for c in rest))
            return
        if isinstance(self.result, MultiCleanResult):
            files.add_columns(*MULTI_RESULT_COLUMNS)
            outcomes = [outcome for _, outcome in self.result.outcomes]
            rows = multi_result_rows(self.result)
        else:
            assert self.flavor is not None
            files.add_columns(*RESULT_COLUMNS)
            outcomes = self.result.outcomes
            rows = result_rows(self.result, self.flavor)
        reasons = [str(column.label) for column in files.ordered_columns].index("Reasons")
        for outcome, row in zip(outcomes, rows):
            cells = [Text(c) for c in row]
            cells[0] = Text(row[0], style=self._status_style(outcome.status))
            cells[reasons] = reasons_text(list(outcome.reasons))
            files.add_row(*cells)

    def summary_rows(self) -> list[tuple[str, str]]:
        if isinstance(self.result, UndoResult):
            return undo_summary_rows(self.result)
        if isinstance(self.result, MultiCleanResult):
            return [(item, value) for item, value, _ in multi_summary_rows(self.result)]
        return summary_rows(self.result)

    def _status_style(self, status: str) -> str:
        return status_style(self.app, status_colour(status, STATUS_COLOURS))
