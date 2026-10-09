"""Suite-wide structured event log. The reference is docs/events.md (generated).

Every event name is registered once with a fixed level. Each tool logs to its own folder,
logs/<tool>/ (the launcher itself uses logs/suite/). log_event() writes one JSON line to
events-YYYY-MM-DD.log (all levels) and one readable line to logfile-YYYY-MM-DD.log (filtered by
[general] log_level). Logging never raises into the caller because of I/O.

Each log file stays open while it is in use and every line is flushed as it is written: opening and closing the
file per event cost about 2.75 ms on a Windows drive under WSL. Moving to a new day closes the previous day's
files; close() (also run at exit) closes the rest.
"""
from __future__ import annotations

import atexit
import contextlib
import json
import re
import secrets
import sys
import threading
import traceback
import weakref
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, Any

from wowtools import __version__

SCHEMA_VERSION = 1
LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}


@dataclass(frozen=True)
class EventSpec:
    level: str
    description: str


class UnknownEventError(KeyError):
    """An event name that no registry declares."""


CORE_EVENTS: dict[str, EventSpec] = {
    "session.start": EventSpec("info", "The launcher or a tool started."),
    "session.end": EventSpec("info", "The process is exiting (waited_for_worker is set when it first waited for a "
                                     "running clean, organize or undo to finish)."),
    "session.waiting_for_worker": EventSpec("warning", "The app closed while a clean, organize or undo was still "
                                                       "running; the lock is kept until it finishes."),
    "changelog.unreadable": EventSpec("warning", "CHANGELOG.md was missing, unreadable or malformed, so the changelog "
                                                 "screen showed nothing (the reason is in `reason`)."),
    "config.created": EventSpec("info", "A config file in config/ was written for the first time."),
    "config.changed": EventSpec("info", "A config value changed or was removed, or was overridden for one run."),
    "config.renamed": EventSpec("info", "A renamed tool's config file was moved to its new name (merged into the new "
                                        "file when both existed)."),
    "folder.renamed": EventSpec("info", "A renamed tool's folder (logs/<tool>/ or <WoW>/wow-tools/<tool>/) was moved "
                                        "to its new name; logged as a warning when entries clashed or failed to move."),
    "lock.conflict": EventSpec("warning", "Another copy of Ka0s WoW Tools appears to be running (its lock file exists)."),
    "lock.overridden": EventSpec("warning", "The user took over an existing lock file and carried on."),
    "parallel.started": EventSpec("debug", "A run over several units (game versions) started (core/parallel.py): "
                                  "what, the units, and the threads it uses (1 = one after another)."),
    "parallel.finished": EventSpec("debug", "A run over several units ended: how many, how many failed, how "
                                   "many never started (an earlier unit failed and the run stops on one), seconds."),
    "parallel.unit_failed": EventSpec("error", "One unit of a run over several raised an unexpected error; the "
                                      "units already running carried on (what, unit, type, message, traceback)."),
    "ui.selection": EventSpec("info", "The user made a choice in the TUI or CLI."),
    "ui.quit_refused": EventSpec("info", "q or Ctrl+Q was pressed while a run was in progress and was refused."),
    "ui.tool_menu_refused": EventSpec("info", "t was pressed while a run was in progress and was refused: "
                                      "the tool menu waits for the run to finish."),
    "ui.item_toggled": EventSpec("debug", "The user ticked or unticked a single item."),
    "update.checked": EventSpec("debug", "The GitHub release check ran or was throttled."),
    "update.check_failed": EventSpec("debug", "The release check failed (offline, rate limited, bad data)."),
    "update.available": EventSpec("info", "A newer suite release exists."),
    "update.applied": EventSpec("info", "The suite was updated."),
    "update.failed": EventSpec("error", "Applying an update failed."),
    "update.verified": EventSpec("info", "A zip update's download matched the release's published SHA-256 (SHA256SUMS)."),
    "update.unverified": EventSpec("warning", "A zip update was applied without a checksum (allow_unverified_updates = true and the release has no SHA256SUMS)."),
    "update.backups_pruned": EventSpec("info", "After a zip update, older .update-backup folders were deleted (kept: the one just made plus the newest other)."),
    "update.leftovers_kept": EventSpec("info", "Before an old .update-backup folder was pruned, files the user had added inside the app's own folders were moved to update-leftovers/<version>/."),
    "update.cleanup_stopped": EventSpec("warning", "Ctrl+C after a zip update had put the new version in place, while it was removing the temporary download (step temp) or pruning old .update-backup folders (step prune); the update counts as applied and the next update prunes again."),
    "update.backup_kept": EventSpec("warning", "An old .update-backup folder was not pruned because a file the user had added could not be moved out of it; the next update tries again."),
    "wow.running_warning": EventSpec("warning", "World of Warcraft appears to be running."),
    "error": EventSpec("error", "An unexpected or fatal error."),
}
REGISTRY: dict[str, EventSpec] = dict(CORE_EVENTS)
TOOL_REGISTRIES: dict[str, dict[str, EventSpec]] = {"core": dict(CORE_EVENTS)}

_LOG_NAME = re.compile(r"^(?:events|logfile)-(\d{4}-\d{2}-\d{2})\.log$")
_SAFE_TOOL = re.compile(r"^[A-Za-z0-9._-]+$")


def log_paths(log_dir: Path, tool: str, day: str) -> tuple[Path, Path]:
    """(events file, readable log file) for one tool and day: logs/<tool>/events-<day>.log, logfile-<day>.log."""
    folder = log_dir / (tool if _SAFE_TOOL.match(tool or "") and tool not in (".", "..") else "suite")
    return folder / f"events-{day}.log", folder / f"logfile-{day}.log"


def register_events(owner: str, events: dict[str, EventSpec]) -> None:
    """Declare a tool's events. Re-registering the same spec is fine; a different spec is a bug."""
    for name, spec in events.items():
        if spec.level not in LEVELS:
            raise ValueError(f"event {name!r} has unknown level {spec.level!r}")
        existing = REGISTRY.get(name)
        if existing is not None and existing != spec:
            raise ValueError(f"event {name!r} is already registered with a different spec")
    REGISTRY.update(events)
    TOOL_REGISTRIES.setdefault(owner, {}).update(events)


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _render_value(value: Any) -> str:
    if isinstance(value, (list, tuple, set, frozenset)):
        return ",".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, default=_json_default, ensure_ascii=False)
    return str(value)


def format_text(record: dict) -> str:
    """One readable line for the .log file."""
    ts = datetime.fromisoformat(record["ts"]).strftime("%Y-%m-%d %H:%M:%S")
    parts = [f"{key}={_render_value(value)}" for key, value in record["data"].items()]
    if record.get("dry_run"):
        parts.insert(0, "DRY-RUN")
    return f"{ts} {record['level'].upper():<7} [{record['tool']}] {record['event']}  " + " ".join(parts)


class EventLog:
    def __init__(self, log_dir: Path | None = None, *, tool: str = "suite", mode: str = "cli",
                 text_level: str = "info", retention_days: int = 90, strict: bool = False,
                 memory: bool = False, clock: Callable[[], datetime] | None = None,
                 on_sink_error: Callable[[str], None] | None = None) -> None:
        self.log_dir = Path(log_dir) if log_dir is not None else None
        self.tool = tool
        self.mode = mode
        self.text_level = text_level if text_level in LEVELS else "info"
        self.retention_days = retention_days
        self.strict = strict
        self.records: list[dict] | None = [] if memory else None
        self.session = secrets.token_hex(4)
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._on_sink_error = on_sink_error or (lambda message: print(message, file=sys.stderr))
        self._disabled: set[str] = set()
        self._handles: dict[Path, IO[str]] = {}
        self._lock = threading.RLock()  # workers log too; re-entrant: emit holds it around _append
        _OPEN_LOGS.add(self)

    def set_context(self, *, tool: str | None = None, mode: str | None = None) -> None:
        if tool is not None:
            self.tool = tool
        if mode is not None:
            self.mode = mode

    def emit(self, name: str, *, dry_run: bool | None = None, level: str | None = None, **data: Any) -> dict:
        spec = REGISTRY.get(name)
        if spec is None:
            if self.strict:
                raise UnknownEventError(name)
            data = {"unregistered_event": name, **data}
            name, spec = "error", REGISTRY["error"]
        final_level = spec.level
        if level in LEVELS and LEVELS[level] > LEVELS[final_level]:
            final_level = level
        # One lock around the time stamp and both sinks: parallel workers log too (core/parallel.py), and each
        # file then gets its lines in time order, in the same order in the events and the text file.
        with self._lock:
            now = self._clock()
            record = {
                "v": SCHEMA_VERSION,
                "ts": now.isoformat(timespec="milliseconds"),
                "session": self.session,
                "suite_version": __version__,
                "tool": self.tool,
                "mode": self.mode,
                "event": name,
                "level": final_level,
                "dry_run": dry_run,
                "data": data,
            }
            if self.records is not None:
                self.records.append(record)
            if self.log_dir is not None:
                events_path, text_path = log_paths(self.log_dir, self.tool, now.strftime("%Y-%m-%d"))
                self._append("events", events_path, json.dumps(record, default=_json_default, ensure_ascii=False))
                if LEVELS[final_level] >= LEVELS[self.text_level]:
                    self._append("text", text_path, format_text(record))
        return record

    def _append(self, sink: str, path: Path, line: str) -> None:
        with self._lock:
            if sink in self._disabled:
                return
            try:
                handle = self._handles.get(path)
                if handle is None:
                    self._close_other_days(path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    handle = self._handles[path] = path.open("a", encoding="utf-8")
                handle.write(line + "\n")
                handle.flush()  # each line reaches the file at once, as before
            except (OSError, ValueError) as exc:
                self._disabled.add(sink)
                stale = self._handles.pop(path, None)
                if stale is not None:
                    with contextlib.suppress(OSError, ValueError):
                        stale.close()
                self._on_sink_error(f"Ka0s WoW Tools: {sink} log disabled for this session ({exc})")

    def _close_other_days(self, path: Path) -> None:
        """A new file is being opened: close the ones from another day (yesterday's, after midnight)."""
        match = _LOG_NAME.match(path.name)
        day = match.group(1) if match else None
        for other in [p for p in self._handles if (m := _LOG_NAME.match(p.name)) is None or m.group(1) != day]:
            with contextlib.suppress(OSError, ValueError):
                self._handles.pop(other).close()

    def close(self) -> None:
        """Close every open log file. Logging again reopens them."""
        with self._lock:
            handles, self._handles = list(self._handles.values()), {}
        for handle in handles:
            with contextlib.suppress(OSError, ValueError):
                handle.close()

    def prune(self) -> list[Path]:
        """Delete dated log files older than retention_days in every tool folder. Returns what was removed.

        Never raises: a folder that cannot be listed is skipped."""
        if self.log_dir is None or not self.log_dir.is_dir():
            return []
        cutoff = (self._clock() - timedelta(days=self.retention_days)).date()
        removed: list[Path] = []
        try:
            folders = list(self.log_dir.iterdir())
        except OSError:
            return []
        files: list[Path] = []
        for folder in folders:
            try:
                if folder.is_dir():
                    files.extend(folder.iterdir())
            except OSError:
                continue
        files.sort()
        for path in files:
            match = _LOG_NAME.match(path.name)
            if not match:
                continue
            try:
                day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < cutoff:
                try:
                    path.unlink()
                    removed.append(path)
                except OSError:
                    pass
        return removed


_OPEN_LOGS: weakref.WeakSet[EventLog] = weakref.WeakSet()


def close_all_logs() -> None:
    """Close the files of every EventLog in this process (at exit, and in tests before a temp folder goes)."""
    for log in list(_OPEN_LOGS):
        log.close()


atexit.register(close_all_logs)
_current = EventLog(strict=True)


def init_event_log(log_dir: Path | None, **kwargs: Any) -> EventLog:
    """Install the process-wide log (called once by the launcher) and prune old files."""
    global _current
    _current.close()
    _current = EventLog(log_dir, **kwargs)
    _current.prune()
    return _current


def get_event_log() -> EventLog:
    return _current


def log_event(name: str, *, dry_run: bool | None = None, level: str | None = None, **data: Any) -> dict:
    return _current.emit(name, dry_run=dry_run, level=level, **data)


def log_exception(where: str, exc: BaseException) -> dict:
    return log_event("error", where=where, type=type(exc).__name__, message=str(exc),
                     traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))


@contextlib.contextmanager
def capture_events(**kwargs: Any) -> Iterator[list[dict]]:
    """Tests: route log_event() into a strict in-memory log and yield its records."""
    global _current
    previous = _current
    _current = EventLog(strict=True, memory=True, **kwargs)
    try:
        yield _current.records  # type: ignore[misc]
    finally:
        _current = previous
