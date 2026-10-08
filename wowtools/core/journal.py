"""Run journals, shared by every tool that changes files: one JSON Lines file per real run.

The standard location is <WoW>/wow-tools/<tool>/journal/journal-<YYYYMMDD-HHMMSS>.jsonl (journal_dir()). Line 1 is
a header. Each completed change appends one line, flushed and fsync'ed at once (F-012), so the journal is accurate
even if the run is cut short, a power cut included. A {"finished": ...} line closes a run and an {"undone": ...} line records an undo.

Tools add their own entry fields (every entry has an "action") and their own undo rules. Path values are written
with to_stored() and read back with to_native() (read_journal's path_fields). No textual import here.
"""
from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from wowtools.core.events import log_event
from wowtools.core.fsutil import free_name
from wowtools.core.paths import to_native, to_stored

JOURNAL_VERSION = 1
JOURNAL_SUBDIR = "journal"
TOOLS_SUBDIR = "wow-tools"
_NAME = re.compile(r"^journal-(\d{8}-\d{6})(?:-(\d+))?\.jsonl$")


def journal_dir(wow_path: Path | None, tool: str) -> Path | None:
    """<WoW folder>/wow-tools/<tool>/journal, or None without a WoW folder."""
    return wow_path / TOOLS_SUBDIR / tool / JOURNAL_SUBDIR if wow_path is not None else None


def tool_root(backup_dir: Path | None, wow_path: Path | None, tool: str) -> Path | None:
    """A tool's own folder: <backup_dir>/<tool> when a backup folder is set, else <WoW folder>/wow-tools/<tool>;
    None with neither."""
    if backup_dir is not None:
        return backup_dir / tool
    return wow_path / TOOLS_SUBDIR / tool if wow_path is not None else None


def now_iso() -> str:
    """The local time with its UTC offset, to the second (journal headers and markers)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def friendly_stamp(stamp: str) -> str:
    """A journal's ISO-8601 time as "YYYY-MM-DD HH:MM" (its own clock); anything unparsable is shown as is."""
    if not stamp:
        return "an unknown time"
    try:
        return datetime.fromisoformat(stamp).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return stamp


def new_journal_path(folder: Path, now: datetime | None = None) -> Path:
    """journal-<stamp>.jsonl in folder, with -2, -3, ... when that name is taken."""
    return free_name(folder, f"journal-{(now or datetime.now()):%Y%m%d-%H%M%S}", ".jsonl")


def _stored(value: Any) -> Any:
    return to_stored(value) if isinstance(value, Path) else value


class JournalWriter:
    """`open()` creates the file (exclusive) and writes the header before the run touches anything, so a journal
    that cannot be written stops the run first. `add_entry()` writes one change (Path values are stored with
    to_stored()). `discard_if_empty()` removes a header-only journal, so a run that changes nothing leaves none.

    Thread-safe: units of a parallel run (core/parallel.py) may share one writer. Every method holds one re-entrant
    lock, so lines never interleave and `count` stays right; a subclass that writes a record and changes its own
    state (CleanJournal.add_rolled_back) takes `self.lock` around both."""

    def __init__(self, path: Path, header: dict[str, Any]) -> None:
        self.path = path
        self.header = {"version": JOURNAL_VERSION, "started": now_iso(),
                       **{k: _stored(v) for k, v in header.items()}}
        self.count = 0
        self.lock = threading.RLock()
        self._handle: IO[str] | None = None

    def _write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self.lock:
            assert self._handle is not None
            self._handle.write(line)
            self._handle.flush()
            os.fsync(self._handle.fileno())  # on the disk before the change it records (F-012)

    def open(self) -> None:
        with self.lock:
            if self._handle is not None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("x", encoding="utf-8")
            try:
                self._write(self.header)
            except BaseException:
                self.close()
                self.path.unlink(missing_ok=True)
                raise

    def add_entry(self, entry: dict[str, Any]) -> None:
        """Append one completed change. `entry` must have an "action"."""
        record = {k: _stored(v) for k, v in entry.items()}
        with self.lock:
            if self._handle is None:
                self.open()
            self._write(record)
            self.count += 1

    def finish(self) -> None:
        with self.lock:
            if self._handle is not None:
                self._write({"finished": now_iso(), "entries": self.count})

    def close(self) -> None:
        with self.lock:
            if self._handle is not None:
                self._handle.close()
                self._handle = None

    def discard_if_empty(self) -> None:
        """Close, and delete the file if no entry was written (a run that changed nothing)."""
        with self.lock:
            self.close()
            if self.count == 0:
                try:
                    self.path.unlink(missing_ok=True)
                except OSError:
                    pass

    @property
    def opened(self) -> bool:
        """True once an entry was written (the journal is kept)."""
        return self.count > 0


@dataclass
class Journal:
    path: Path
    header: dict[str, Any]
    entries: list[dict[str, Any]] = field(default_factory=list)
    finished: str | None = None
    undone: str | None = None

    @property
    def started(self) -> str:
        return str(self.header.get("started", ""))


def read_journal(path: Path, *, path_fields: Iterable[str] = ()) -> Journal:
    """Read a journal. Entries are the records with an "action"; the string values of path_fields are turned
    into native Paths. A torn line (a crash mid-write) is skipped."""
    names = tuple(path_fields)
    journal = Journal(path, {})
    # errors="replace": a crash can cut the last line inside a multibyte character (paths are written
    # with ensure_ascii=False); that line then fails to parse and is skipped like any other torn line.
    with path.open(encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            if number == 0 and "version" in record:
                journal.header = record
            elif "action" in record:
                for name in names:
                    if isinstance(record.get(name), str):
                        record[name] = to_native(record[name])
                journal.entries.append(record)
            elif "finished" in record:
                journal.finished = str(record["finished"])
            elif "undone" in record:
                journal.undone = str(record["undone"])
    return journal


def list_journals(folder: Path | None) -> list[Path]:
    """Journal files, newest first (only journal-<stamp>.jsonl names)."""
    if folder is None or not folder.is_dir():
        return []
    found = [p for p in folder.iterdir() if _NAME.match(p.name) and p.is_file()]

    def key(p: Path) -> tuple[str, int]:
        m = _NAME.match(p.name)
        assert m is not None
        return m.group(1), int(m.group(2) or 1)

    return sorted(found, key=key, reverse=True)


def latest_undoable(folder: Path | None, reader: Callable[[Path], Journal] = read_journal) -> Path | None:
    """The newest journal that has entries and was not undone. Only that journal is ever offered: this never
    reaches back past an undone run. Never raises: run in the scan and run workers, a folder that cannot be listed
    offers nothing."""
    try:
        paths = list_journals(folder)
    except OSError:  # e.g. no permission to list the folder: nothing offered, never a crash
        return None
    for path in paths:
        try:
            journal = reader(path)
        except (OSError, ValueError, TypeError):  # unreadable: never offered, and never a crash
            continue
        if journal.undone is not None:
            return None
        if journal.entries:
            return path
    return None


def append_record(path: Path, record: dict[str, Any]) -> None:
    """Append one JSON line to an existing journal (an undo or recovery record)."""
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell():
            handle.seek(-1, 2)
            if handle.read(1) != b"\n":
                line = "\n" + line  # the last line was torn by a crash: start the record on its own line
        handle.seek(0, 2)
        handle.write(line.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


def mark_undone(path: Path, restored: int, skipped: int) -> None:
    append_record(path, {"undone": now_iso(), "restored": restored, "skipped": skipped})


def prune_journals(folder: Path | None, keep: int, *, event: str | None = None) -> list[Path]:
    """Delete all but the newest `keep` (at least 1) journals. Other files are never touched. Returns what was
    removed; when something was and `event` is given, logs it with the removed names and keep (a tool that logs
    more, such as Interface Backup with the safety zips it drops, passes no event and logs its own)."""
    removed = []
    for path in list_journals(folder)[max(1, keep):]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            continue
    if removed and event:
        log_event(event, removed=[p.name for p in removed], keep=keep)
    return removed


@dataclass(frozen=True)
class ToolJournals:
    """One tool's journals: where they live (journal_dir under its name), how its journals are read (its entry
    rules) and the event it logs when old ones are pruned. A tool's journal module makes one and exports its bound
    methods (resolve_journal_dir, latest_undoable, prune_journals) instead of writing the same wrappers again."""
    tool: str
    reader: Callable[[Path], Journal] = read_journal
    pruned_event: str | None = None

    def dir(self, wow_path: Path | None) -> Path | None:
        """<WoW folder>/wow-tools/<tool>/journal (always under the WoW folder, whatever the tool's output folder)."""
        return journal_dir(wow_path, self.tool)

    def latest_undoable(self, folder: Path | None) -> Path | None:
        return latest_undoable(folder, self.reader)

    def prune(self, folder: Path | None, keep: int) -> list[Path]:
        return prune_journals(folder, keep, event=self.pruned_event)
