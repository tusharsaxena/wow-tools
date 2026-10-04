"""The Ace3 Profile Manager's run journals: the suite format (core/journal.py) with this tool's entries.

One journal per Apply, even across All flavors: <WoW>/wow-tools/ace-profiles/journal/journal-<stamp>.jsonl. Each
rewritten file adds {"action": "edited", "flavor", "path", "rel", "zip", "sha_before", "sha_after", "size_before",
"size_after", "changes"}: zip is the edited-*.zip holding the file's original bytes (as <rel>). When a run puts
written files back after a failure it appends {"action": "rolled_back", "flavor", "rels"}; those entries are
dropped on reading, so they are never offered for Undo.
"""
from __future__ import annotations

from pathlib import Path

from wowtools.core import journal as core
from wowtools.core.events import log_event
from wowtools.core.journal import Journal

A_EDITED = "edited"
A_ROLLED_BACK = "rolled_back"
PATH_FIELDS = ("path", "zip")


class ProfileJournal(core.JournalWriter):
    def __init__(self, path: Path, header: dict) -> None:
        super().__init__(path, header)
        self._edited: set[tuple[str, str]] = set()

    def add_edited(self, *, flavor: str, path: Path, rel: str, zip_path: Path, sha_before: str, sha_after: str,
                   size_before: int, size_after: int, changes: list[str]) -> None:
        self.add_entry({"action": A_EDITED, "flavor": flavor, "path": path, "rel": rel, "zip": zip_path,
                        "sha_before": sha_before, "sha_after": sha_after, "size_before": size_before,
                        "size_after": size_after, "changes": list(changes)})
        self._edited.add((flavor, rel))

    def add_rolled_back(self, *, flavor: str, rels: list[str]) -> None:
        undone = {(flavor, rel) for rel in rels} & self._edited
        if not undone:
            return
        self._write({"action": A_ROLLED_BACK, "flavor": flavor, "rels": sorted(rel for _, rel in undone)})
        self._edited -= undone
        self.count -= len(undone)


def read_profile_journal(path: Path) -> Journal:
    journal = core.read_journal(path, path_fields=PATH_FIELDS)
    rolled = {(e.get("flavor"), rel) for e in journal.entries
              if e.get("action") == A_ROLLED_BACK and isinstance(e.get("rels"), list)
              for rel in e["rels"] if isinstance(rel, str)}
    entries = []
    for entry in journal.entries:
        if entry.get("action") != A_EDITED or (entry.get("flavor"), entry.get("rel")) in rolled:
            continue
        if not all(isinstance(entry.get(k), str) for k in ("flavor", "rel", "sha_before", "sha_after")):
            continue
        if not isinstance(entry.get("zip"), Path):
            continue
        entries.append(entry)
    journal.entries = entries
    return journal


def latest_undoable(folder: Path | None) -> Path | None:
    return core.latest_undoable(folder, read_profile_journal)


def prune_journals(folder: Path | None, keep: int) -> list[Path]:
    removed = core.prune_journals(folder, keep)
    if removed:
        log_event("ace.journal_pruned", removed=[p.name for p in removed], keep=keep)
    return removed


def referenced_zips(folder: Path | None) -> set[str]:
    names: set[str] = set()
    for path in core.list_journals(folder):
        try:
            journal = read_profile_journal(path)
        except OSError:
            continue
        names.update(entry["zip"].name for entry in journal.entries)
    return names
