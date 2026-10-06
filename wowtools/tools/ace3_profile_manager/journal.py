"""The Ace3 Profile Manager's run journals: the shared SavedVariables edit journal (core/sv_journal.py) under this
tool's name, <WoW>/wow-tools/ace3-profile-manager/journal/journal-<stamp>.jsonl, one per Apply."""
from __future__ import annotations

from wowtools.core.sv_journal import EditJournal, read_edit_journal, record_recovered, referenced_zips
from wowtools.tools.ace3_profile_manager.events import SV_TOOL

__all__ = ["JOURNALS", "ProfileJournal", "latest_undoable", "prune_journals", "read_profile_journal",
           "record_recovered", "referenced_zips", "resolve_journal_dir"]

ProfileJournal = EditJournal
read_profile_journal = read_edit_journal
JOURNALS = SV_TOOL.journals
resolve_journal_dir = JOURNALS.dir
latest_undoable = JOURNALS.latest_undoable
prune_journals = JOURNALS.prune
