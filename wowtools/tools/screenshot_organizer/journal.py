"""The Screenshot Organizer's run journals: the suite format (core/journal.py) with this tool's entries.

Each entry is {"action", "src", "dst", "size"}: the action is one of the A_* names below, src the screenshot's
path in its Screenshots folder and dst its filed path. Journals live in <WoW>/wow-tools/screenshot-organizer/journal/.
"""
from __future__ import annotations

from pathlib import Path

from wowtools.core import journal as core
from wowtools.core.events import log_event
from wowtools.core.journal import Journal, list_journals, mark_undone, new_journal_path

__all__ = ["A_COPIED", "A_DUPLICATE", "A_MOVED", "A_SOURCE_LEFT", "Journal", "JournalWriter", "latest_undoable",
           "list_journals", "mark_undone", "new_journal_path", "prune_journals", "read_journal"]

A_MOVED = "moved"
A_COPIED = "copied"
A_SOURCE_LEFT = "copied_source_left"
A_DUPLICATE = "duplicate_removed"


class JournalWriter(core.JournalWriter):
    def add(self, action: str, src: Path, dst: Path, size: int) -> None:
        self.add_entry({"action": action, "src": src, "dst": dst, "size": size})


def read_journal(path: Path) -> Journal:
    """A journal with only well-formed organizer entries (src and dst as native Paths, size an int). An entry
    with a missing or unreadable size (a hand edit, or corruption) is dropped, like one without paths."""
    journal = core.read_journal(path, path_fields=("src", "dst"))
    entries = []
    for e in journal.entries:
        if not (isinstance(e.get("src"), Path) and isinstance(e.get("dst"), Path)):
            continue
        try:
            size = int(e["size"])
        except (KeyError, TypeError, ValueError):
            continue
        entries.append({**e, "size": size})
    journal.entries = entries
    return journal


def latest_undoable(journal_dir: Path | None) -> Path | None:
    """The newest journal that has entries and was not undone. Only that journal is ever offered."""
    return core.latest_undoable(journal_dir, read_journal)


def prune_journals(journal_dir: Path | None, keep: int) -> list[Path]:
    removed = core.prune_journals(journal_dir, keep)
    if removed:
        log_event("shots.journal_pruned", removed=[p.name for p in removed], keep=keep)
    return removed
