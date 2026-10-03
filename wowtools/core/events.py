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
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, Any, Callable, Iterator

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
    "config.created": EventSpec("info", "A config file in config/ was written for the first time."),
    "config.changed": EventSpec("info", "A config value changed, or was overridden for one run."),
    "config.migrated": EventSpec("info", "The old shared wow-tools.cfg was split into config/ (one file per tool)."),
    "config.renamed": EventSpec("info", "A renamed tool's config file was moved to its new name (merged into the new "
                                        "file when both existed)."),
    "folder.renamed": EventSpec("info", "A renamed tool's folder (logs/<tool>/ or <WoW>/wow-tools/<tool>/) was moved "
                                        "to its new name; logged as a warning when entries clashed or failed to move."),
    "lock.conflict": EventSpec("warning", "Another copy of Ka0s WoW Tools appears to be running (its lock file exists)."),
    "lock.overridden": EventSpec("warning", "The user took over an existing lock file and carried on."),
    "ui.selection": EventSpec("info", "The user made a choice in the TUI or CLI."),
    "ui.quit_refused": EventSpec("info", "Ctrl+Q was pressed while a run was in progress and was refused."),
    "ui.item_toggled": EventSpec("debug", "The user ticked or unticked a single item."),
    "update.checked": EventSpec("debug", "The GitHub release check ran or was throttled."),
    "update.check_failed": EventSpec("debug", "The release check failed (offline, rate limited, bad data)."),
    "update.available": EventSpec("info", "A newer suite release exists."),
    "update.applied": EventSpec("info", "The suite was updated."),
    "update.failed": EventSpec("error", "Applying an update failed."),
    "wow.running_warning": EventSpec("warning", "World of Warcraft appears to be running."),
    "error": EventSpec("error", "An unexpected or fatal error."),
}
REGISTRY: dict[str, EventSpec] = dict(CORE_EVENTS)
TOOL_REGISTRIES: dict[str, dict[str, EventSpec]] = {"core": dict(CORE_EVENTS)}

_LOG_NAME = re.compile(r"^(?:events|logfile)-(\d{4}-\d{2}-\d{2})\.log$")
# The flat layout used before per-tool folders: logs/events-<day>.jsonl and logs/wow-tools-<day>.log.
_FLAT_LOG_NAME = re.compile(r"^(events|wow-tools)-(\d{4}-\d{2}-\d{2})\.(jsonl|log)$")
_TEXT_TOOL = re.compile(r"^\S+ \S+ \S+\s+\[([^\]]+)\] ")
_SAFE_TOOL = re.compile(r"^[A-Za-z0-9._-]+$")


def log_paths(log_dir: Path, tool: str, day: str) -> tuple[Path, Path]:
    """(events file, readable log file) for one tool and day: logs/<tool>/events-<day>.log, logfile-<day>.log."""
    folder = log_dir / (tool if _SAFE_TOOL.match(tool or "") and tool not in (".", "..") else "suite")
    return folder / f"events-{day}.log", folder / f"logfile-{day}.log"


def migrate_flat_logs(log_dir: Path | None) -> list[Path]:
    """Move logs from the old flat layout into per-tool folders, splitting each file by the tool on each line.

    Old lines go before anything already in the new file. Returns the old files that were moved (and removed).
    Never raises: a file that cannot be moved stays where it is."""
    if log_dir is None or not log_dir.is_dir():
        return []
    moved: list[Path] = []
    for path in sorted(log_dir.iterdir()):
        match = _FLAT_LOG_NAME.match(path.name)
        if not match or not path.is_file():
            continue
        kind, day = match.group(1), match.group(2)
        try:
            by_tool: dict[str, list[str]] = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                tool = "suite"
                if kind == "events":
                    with contextlib.suppress(ValueError, TypeError, AttributeError):
                        tool = str(json.loads(line).get("tool") or "suite")
                else:
                    found = _TEXT_TOOL.match(line)
                    if found:
                        tool = found.group(1)
                by_tool.setdefault(tool, []).append(line)
            for tool, lines in by_tool.items():
                events_path, text_path = log_paths(log_dir, tool, day)
                target = events_path if kind == "events" else text_path
                target.parent.mkdir(parents=True, exist_ok=True)
                existing = target.read_text(encoding="utf-8") if target.exists() else ""
                partial = target.with_name(target.name + ".partial")
                partial.write_text("\n".join(lines) + "\n" + existing, encoding="utf-8")
                partial.replace(target)
            path.unlink()
            moved.append(path)
        except (OSError, UnicodeDecodeError):
            continue
    return moved


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
        self._lock = threading.Lock()  # workers log too
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
        """Delete dated log files older than retention_days in every tool folder. Returns what was removed."""
        if self.log_dir is None or not self.log_dir.is_dir():
            return []
        cutoff = (self._clock() - timedelta(days=self.retention_days)).date()
        removed: list[Path] = []
        files = sorted(p for folder in self.log_dir.iterdir() if folder.is_dir() for p in folder.iterdir())
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
    """Install the process-wide log (called once by the launcher), move any old flat-layout logs into the
    per-tool folders, and prune old files."""
    global _current
    _current.close()
    _current = EventLog(log_dir, **kwargs)
    migrate_flat_logs(_current.log_dir)
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
