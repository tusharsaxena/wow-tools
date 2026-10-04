"""Restore journals: the tool's entry fields over core/journal.py. A restore writes one journal; Undo uses the
newest one that replaced a part and was not undone. UI-free.

Header: {"flavor": folder, "flavor_path", "backup", "parts", "suite_version"}. Entries:
{"action": "safety_backup", "zip", "parts_existing"} and {"action": "replaced", "part", "existed"}."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from wowtools.core import journal as core_journal
from wowtools.core.journal import Journal, list_journals, read_journal
from wowtools.core.paths import to_native

PATH_FIELDS = ("flavor_path", "backup", "zip")
_HEADER_PATHS = ("flavor_path", "backup")


def read_restore_journal(path: Path) -> Journal:
    """read_journal with this tool's path fields, in the header too (read_journal converts entry fields only)."""
    journal = read_journal(path, path_fields=PATH_FIELDS)
    for name in _HEADER_PATHS:
        if isinstance(journal.header.get(name), str):
            journal.header[name] = to_native(journal.header[name])
    return journal


def _replaced_only(path: Path) -> Journal:
    journal = read_restore_journal(path)
    return replace(journal, entries=[e for e in journal.entries if e.get("action") == "replaced"])


def latest_undoable(folder: Path | None) -> Path | None:
    """The newest restore journal that replaced at least one part and was not undone (a restore whose parts were
    all rolled back changed nothing, so it is passed over)."""
    return core_journal.latest_undoable(folder, reader=_replaced_only)


def safety_zips_named(paths: list[Path]) -> set[str] | None:
    """File names of the safety zips these journals name; None if any of them cannot be read."""
    names: set[str] = set()
    for path in paths:
        try:
            journal = read_restore_journal(path)
        except (OSError, ValueError):
            return None
        for entry in journal.entries:
            zip_path = entry.get("zip")
            if entry.get("action") == "safety_backup" and isinstance(zip_path, Path):
                names.add(zip_path.name)
    return names


def referenced_safety_zips(folder: Path | None) -> set[str] | None:
    """File names of the safety zips the journals in folder name; None if any journal cannot be read (then no
    safety zip is deleted)."""
    return safety_zips_named(list_journals(folder))
