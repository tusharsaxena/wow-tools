"""The WTF Cleaner's run journals: the suite format (core/journal.py) with this tool's entries.

One journal per real clean, even across All flavors: <WoW>/wow-tools/wtf-cleaner/journal/journal-<stamp>.jsonl.
The header lists the flavors, the backup folder and the suite version. Each deleted file adds one entry:
{"action": "deleted", "flavor", "path", "rel", "size", "mtime", "zip", "snapshot"} where rel is the path inside
the flavor folder (as stored in both zips), zip the cleaned-files zip that holds it (null when backups are off)
and snapshot that flavor's WTF backup.

When a clean stops and puts back what it deleted in a flavor, it appends {"action": "rolled_back", "flavor",
"rels"}: those entries are dropped on reading, so a rolled-back clean is never offered for Undo (and one whose every
delete was rolled back is not kept at all), which would otherwise hide the clean before it.
"""
from __future__ import annotations

from pathlib import Path

from wowtools.core import journal as core
from wowtools.core.journal import Journal
from wowtools.core.paths import to_native
from wowtools.tools.wtf_cleaner.events import TOOL_NAME

A_DELETED = "deleted"
A_ROLLED_BACK = "rolled_back"
PATH_FIELDS = ("path", "zip", "snapshot")


class CleanJournal(core.JournalWriter):
    def __init__(self, path: Path, header: dict) -> None:
        super().__init__(path, header)
        self._deleted: set[tuple[str, str]] = set()

    def add_deleted(self, *, flavor: str, path: Path, rel: str, size: int, mtime: float, zip_path: Path | None,
                    snapshot: Path | None) -> None:
        self.add_entry({"action": A_DELETED, "flavor": flavor, "path": path, "rel": rel, "size": size,
                        "mtime": mtime, "zip": zip_path, "snapshot": snapshot})
        self._deleted.add((flavor, rel))

    def add_rolled_back(self, *, flavor: str, rels: list[str]) -> None:
        """These deletes of this run were put back. Their entries no longer count: a journal left with none is
        discarded like one that deleted nothing."""
        undone = {(flavor, rel) for rel in rels} & self._deleted
        if not undone:
            return
        self._write({"action": A_ROLLED_BACK, "flavor": flavor, "rels": sorted(rel for _, rel in undone)})
        self._deleted -= undone
        self.count -= len(undone)


def read_journal(path: Path) -> Journal:
    """A journal with only well-formed cleaner entries (paths as native Paths, size an int)."""
    journal = core.read_journal(path, path_fields=PATH_FIELDS)
    if isinstance(journal.header.get("backup_dir"), str):
        journal.header["backup_dir"] = to_native(journal.header["backup_dir"])
    rolled_back = {(entry.get("flavor"), rel) for entry in journal.entries
                   if entry.get("action") == A_ROLLED_BACK and isinstance(entry.get("rels"), list)
                   for rel in entry["rels"] if isinstance(rel, str)}
    entries = []
    for entry in journal.entries:
        if (entry.get("flavor"), entry.get("rel")) in rolled_back:
            continue
        if entry.get("action") != A_DELETED or not isinstance(entry.get("rel"), str) \
                or not isinstance(entry.get("flavor"), str):
            continue
        try:
            entry["size"] = int(entry.get("size", -1))
        except (TypeError, ValueError):
            continue
        entries.append(entry)
    journal.entries = entries
    return journal


JOURNALS = core.ToolJournals(TOOL_NAME, read_journal, "clean.journal_pruned")
resolve_journal_dir = JOURNALS.dir
latest_undoable = JOURNALS.latest_undoable
prune_journals = JOURNALS.prune
