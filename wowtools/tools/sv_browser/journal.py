"""The Saved Variables Browser's run journals (spec D14): the shared SavedVariables edit journal
(core/sv_journal.py) under this tool's name, <WoW>/wow-tools/sv-browser/journal/journal-<stamp>.jsonl, one per
Apply, kept to [general] keep_journals. UI-free."""
from __future__ import annotations

from wowtools.core.sv_journal import EditJournal, read_edit_journal, record_recovered
from wowtools.tools.sv_browser.events import SV_TOOL

__all__ = ["JOURNALS", "EditJournal", "latest_undoable", "prune_journals", "read_journal", "record_recovered",
           "resolve_journal_dir"]

read_journal = read_edit_journal
JOURNALS = SV_TOOL.journals
resolve_journal_dir = JOURNALS.dir
latest_undoable = JOURNALS.latest_undoable
prune_journals = JOURNALS.prune
