"""The Config Copier's run journals: the shared edit journal (core/sv_journal.py) under this tool's name,
<WoW>/wow-tools/config-copier/journal/journal-<stamp>.jsonl, one per Copy, kept to [general] keep_journals. A file
the run created is journaled "created" (core/client_apply.py). UI-free."""
from __future__ import annotations

from wowtools.core.sv_journal import read_edit_journal
from wowtools.tools.config_copier.events import SV_TOOL

__all__ = ["JOURNALS", "latest_undoable", "prune_journals", "read_journal", "resolve_journal_dir"]

read_journal = read_edit_journal
JOURNALS = SV_TOOL.journals
resolve_journal_dir = JOURNALS.dir
latest_undoable = JOURNALS.latest_undoable
prune_journals = JOURNALS.prune
