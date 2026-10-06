"""The outcome of an Apply, a dry run or Undo last change (spec §5): the summary (flavors, files changed / would
change / skipped / failed / put back, edits written, the WTF snapshot and originals zips, the journal), one detail
row per file and what to do next (the shared ResultScreen)."""
from __future__ import annotations

from typing import ClassVar

from wowtools.core.sv_report import STATUS_COLOURS
from wowtools.ui.result_screen import ResultScreen

TITLE = "Saved Variables Browser"


class SvResultScreen(ResultScreen):
    """`title` is "Apply", "Dry run" or "Undo". Dismisses with "rescan", "flavors", "tools" or "quit"; with `back`
    (a dry run: nothing was written, the staged edits and ticked results are still there) it opens on "Back to
    review", and Esc dismisses with "back"."""

    LOG_SCREEN = "svb_result"
    STATUS_COLOURS: ClassVar = STATUS_COLOURS

    def __init__(self, title: str, summary_rows: list[tuple[str, str]], columns: tuple[str, ...],
                 detail_rows: list[tuple], scope_label: str, *, back: bool = False) -> None:
        super().__init__(f"{TITLE} · {scope_label} · {title} result", summary_rows, columns, detail_rows, back=back)
        self.title_text = title
        self.scope_label = scope_label
