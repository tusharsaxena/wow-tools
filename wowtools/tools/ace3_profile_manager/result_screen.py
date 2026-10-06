"""The outcome of an Apply, a dry run or Undo last change: an Item/Value summary, one detail table and what to do
next (the shared ResultScreen)."""
from __future__ import annotations

from typing import ClassVar

from wowtools.ui.result_screen import ResultScreen

# Theme colour of a detail row's last cell, by its first words (report.RESULT_TEXT and the undo statuses).
STATUS_COLOURS = (("would change", "accent"), ("changed", "success"), ("restored", "success"),
                  ("put back", "warning"), ("skipped", "warning"), ("failed", "error"))


class ProfileResultScreen(ResultScreen):
    """`title` is "Apply", "Dry run" or "Undo". Dismisses with "rescan", "flavors", "tools" or "quit"; with `back`
    (a dry run: nothing was written, the pending changes are still there) it opens on "Back to review", and Esc
    dismisses with "back"."""

    LOG_SCREEN = "ace_result"
    STATUS_COLOURS: ClassVar = STATUS_COLOURS

    def __init__(self, title: str, summary_rows: list[tuple[str, str]], columns: tuple[str, ...],
                 detail_rows: list[tuple], scope_label: str, *, back: bool = False) -> None:
        super().__init__(f"Ace3 Profile Manager · {scope_label} · {title} result", summary_rows, columns,
                         detail_rows, back=back)
        self.title_text = title
        self.scope_label = scope_label
