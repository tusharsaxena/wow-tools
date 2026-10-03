"""Run journals: one JSON Lines file per real run, in <WoW>/wow-tools/screenshots/journal/.

Line 1 is a header. Each completed action appends one line, flushed at once, so the journal is accurate even if
the run is cut short. A {"finished": ...} line closes a run and an {"undone": ...} line records an undo."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from wowtools.core.events import log_event
from wowtools.core.paths import to_native, to_stored

JOURNAL_VERSION = 1
A_MOVED = "moved"
A_COPIED = "copied"
A_SOURCE_LEFT = "copied_source_left"
A_DUPLICATE = "duplicate_removed"
_NAME = re.compile(r"^journal-(\d{8}-\d{6})(?:-(\d+))?\.jsonl$")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_journal_path(journal_dir: Path, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    path = journal_dir / f"journal-{stamp}.jsonl"
    n = 2
    while path.exists():
        path = journal_dir / f"journal-{stamp}-{n}.jsonl"
        n += 1
    return path


class JournalWriter:
    """`open()` creates the file and writes the header before the run touches anything, so a journal that
    cannot be written stops the run first. `discard_if_empty()` removes a header-only journal, so a run that
    changes nothing leaves none."""

    def __init__(self, path: Path, header: dict[str, Any]) -> None:
        self.path = path
        self.header = {"version": JOURNAL_VERSION, **header}
        self.count = 0
        self._handle: IO[str] | None = None

    def _write(self, record: dict[str, Any]) -> None:
        assert self._handle is not None
        self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._handle.flush()

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("x", encoding="utf-8")
        try:
            self._write(self.header)
        except BaseException:
            self.close()
            self.path.unlink(missing_ok=True)
            raise

    def add(self, action: str, src: Path, dst: Path, size: int) -> None:
        if self._handle is None:
            self.open()
        self._write({"action": action, "src": to_stored(src), "dst": to_stored(dst), "size": size})
        self.count += 1

    def finish(self) -> None:
        if self._handle is not None:
            self._write({"finished": _now(), "entries": self.count})

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def discard_if_empty(self) -> None:
        """Close, and delete the file if no entry was written (a run that changed nothing)."""
        self.close()
        if self.count == 0:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass

    @property
    def opened(self) -> bool:
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


def read_journal(path: Path) -> Journal:
    journal = Journal(path, {})
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle):
            try:
                record = json.loads(line)
            except ValueError:
                continue  # a torn last line from a crash
            if not isinstance(record, dict):
                continue
            if number == 0 and "version" in record:
                journal.header = record
            elif "action" in record and "src" in record and "dst" in record:
                journal.entries.append({**record, "src": to_native(str(record["src"])),
                                        "dst": to_native(str(record["dst"])), "size": int(record.get("size", -1))})
            elif "finished" in record:
                journal.finished = str(record["finished"])
            elif "undone" in record:
                journal.undone = str(record["undone"])
    return journal


def list_journals(journal_dir: Path | None) -> list[Path]:
    """Journal files, newest first (only journal-<stamp>.jsonl names)."""
    if journal_dir is None or not journal_dir.is_dir():
        return []
    found = [p for p in journal_dir.iterdir() if p.is_file() and _NAME.match(p.name)]

    def key(p: Path) -> tuple[str, int]:
        m = _NAME.match(p.name)
        assert m is not None
        return m.group(1), int(m.group(2) or 1)

    return sorted(found, key=key, reverse=True)


def latest_undoable(journal_dir: Path | None) -> Path | None:
    """The newest journal that has entries and was not undone. Only that journal is ever offered."""
    for path in list_journals(journal_dir):
        try:
            journal = read_journal(path)
        except OSError:
            continue
        if journal.undone is None and journal.entries:
            return path
        if journal.undone is not None:
            return None  # never reach back past an undone run
    return None


def mark_undone(path: Path, restored: int, skipped: int) -> None:
    record = json.dumps({"undone": _now(), "restored": restored, "skipped": skipped}) + "\n"
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell():
            handle.seek(-1, 2)
            if handle.read(1) != b"\n":
                record = "\n" + record  # the last line was torn by a crash: start the record on its own line
        handle.seek(0, 2)
        handle.write(record.encode("utf-8"))


def prune_journals(journal_dir: Path | None, keep: int) -> list[Path]:
    removed = []
    for path in list_journals(journal_dir)[max(1, keep):]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            continue
    if removed:
        log_event("shots.journal_pruned", removed=[p.name for p in removed], keep=keep)
    return removed
