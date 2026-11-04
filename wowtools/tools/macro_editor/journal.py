"""The Macro Editor's run journals: the shared edit journal (core/sv_journal.py) under this tool's name,
<WoW>/wow-tools/macro-editor/journal/journal-<stamp>.jsonl, one per Apply (every staged change across files and
flavors, ME13), kept to [general] keep_journals. A file the run created is journaled "created"
(core/client_apply.py). UI-free."""
from __future__ import annotations

from wowtools.core.sv_journal import read_edit_journal
from wowtools.tools.macro_editor.events import SV_TOOL

__all__ = ["JOURNALS", "latest_undoable", "prune_journals", "read_journal", "resolve_journal_dir"]

read_journal = read_edit_journal
JOURNALS = SV_TOOL.journals
resolve_journal_dir = JOURNALS.dir
latest_undoable = JOURNALS.latest_undoable
prune_journals = JOURNALS.prune
