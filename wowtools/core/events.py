"""Suite-wide structured event log. The reference is docs/events.md (generated).

Every event name is registered once with a fixed level. log_event() writes one JSON line to
logs/events-YYYY-MM-DD.jsonl (all levels) and one readable line to logs/wow-tools-YYYY-MM-DD.log
(filtered by [general] log_level). Logging never raises into the caller because of I/O.
"""
from __future__ import annotations

import contextlib
import json
import re
import secrets
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

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
    "session.end": EventSpec("info", "The process is exiting."),
    "config.created": EventSpec("info", "wow-tools.cfg was written for the first time."),
    "config.changed": EventSpec("info", "A config value changed, or was overridden for one run."),
    "ui.selection": EventSpec("info", "The user made a choice in the TUI or CLI."),
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

_LOG_NAME = re.compile(r"^(?:events|wow-tools)-(\d{4}-\d{2}-\d{2})\.(?:jsonl|log)$")


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
            day = now.strftime("%Y-%m-%d")
            self._append("jsonl", self.log_dir / f"events-{day}.jsonl",
                         json.dumps(record, default=_json_default, ensure_ascii=False))
            if LEVELS[final_level] >= LEVELS[self.text_level]:
                self._append("text", self.log_dir / f"wow-tools-{day}.log", format_text(record))
        return record

    def _append(self, sink: str, path: Path, line: str) -> None:
        if sink in self._disabled:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            self._disabled.add(sink)
            self._on_sink_error(f"Ka0s WoW Tools: {sink} log disabled for this session ({exc})")

    def prune(self) -> list[Path]:
        """Delete dated log files older than retention_days. Returns what was removed."""
        if self.log_dir is None or not self.log_dir.is_dir():
            return []
        cutoff = (self._clock() - timedelta(days=self.retention_days)).date()
        removed: list[Path] = []
        for path in sorted(self.log_dir.iterdir()):
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


_current = EventLog(strict=True)


def init_event_log(log_dir: Path | None, **kwargs: Any) -> EventLog:
    """Install the process-wide log (called once by the launcher) and prune old files."""
    global _current
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
