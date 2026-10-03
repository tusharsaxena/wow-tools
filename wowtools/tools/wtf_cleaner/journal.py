"""The WTF Cleaner's run journals: the suite format (core/journal.py) with this tool's entries.

One journal per real clean, even across All flavors: <WoW>/wow-tools/wtf-cleaner/journal/journal-<stamp>.jsonl.
The header lists the flavors, the backup folder and the suite version. Each deleted file adds one entry:
{"action": "deleted", "flavor", "path", "rel", "size", "mtime", "zip", "snapshot"} where rel is the path inside
the flavor folder (as stored in both zips), zip the cleaned-files zip that holds it (null when backups are off)
and snapshot that flavor's WTF backup.
"""
from __future__ import annotations

from pathlib import Path

from wowtools.core import journal as core
from wowtools.core.events import log_event
from wowtools.core.journal import Journal
from wowtools.core.paths import to_native
from wowtools.tools.wtf_cleaner.events import TOOL_NAME

A_DELETED = "deleted"
PATH_FIELDS = ("path", "zip", "snapshot")


def clean_journal_dir(wow_path: Path | None) -> Path | None:
    return core.journal_dir(wow_path, TOOL_NAME)


class CleanJournal(core.JournalWriter):
    def add_deleted(self, *, flavor: str, path: Path, rel: str, size: int, mtime: float, zip_path: Path | None,
                    snapshot: Path | None) -> None:
        self.add_entry({"action": A_DELETED, "flavor": flavor, "path": path, "rel": rel, "size": size,
                        "mtime": mtime, "zip": zip_path, "snapshot": snapshot})


def read_journal(path: Path) -> Journal:
    """A journal with only well-formed cleaner entries (paths as native Paths, size an int)."""
    journal = core.read_journal(path, path_fields=PATH_FIELDS)
    if isinstance(journal.header.get("backup_dir"), str):
        journal.header["backup_dir"] = to_native(journal.header["backup_dir"])
    entries = []
    for entry in journal.entries:
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


def latest_undoable(folder: Path | None) -> Path | None:
    return core.latest_undoable(folder, read_journal)


def prune_journals(folder: Path | None, keep: int) -> list[Path]:
    removed = core.prune_journals(folder, keep)
    if removed:
        log_event("clean.journal_pruned", removed=[p.name for p in removed], keep=keep)
    return removed
