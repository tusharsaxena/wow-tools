"""Interpreter check, vendor/ path setup and the launcher log. Stdlib only: runs before any third-party import.

logs/suite/launcher.log holds what nothing else can log: the launchers' own lines (wow-tools.cmd / wow-tools.sh,
`launcher.*`) and Python failures before the event log opens (`bootstrap.failed`). It is written outside
log_event (STD-6.1, STD-6.6; the LN7 deviation in docs/standards.md), one line per record:
`<time> <event> key=value ...`. The launchers write the time as their shell gives it; Python writes ISO time.
"""
from __future__ import annotations

import contextlib
import os
import re
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDOR_DIR = REPO_ROOT / "vendor"
MIN_PYTHON = (3, 10)
LAUNCHER_LOG = REPO_ROOT / "logs" / "suite" / "launcher.log"
TRACEBACK_LINES = 10  # the last lines of a traceback kept under a bootstrap.failed line
UNDATED_KEEP_LINES = 2000  # when no line's date can be read, the trim keeps this many lines

# A leading date: ISO / year first (2026-11-04, 2026/11/04), or the cmd.exe %date% shapes with an optional weekday
# first (Wed 11/04/2026, 04.11.2026). Day and month order depends on the locale, so both readings are tried.
_YEAR_FIRST = re.compile(rb"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_YEAR_LAST = re.compile(rb"^(?:[^\s\d]+\s+)?(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")


def check_python(version_info: tuple[int, ...] | None = None) -> str | None:
    """Return a readable error if this Python is too old, else None."""
    major, minor = tuple(version_info or sys.version_info)[:2]
    if (major, minor) < MIN_PYTHON:
        return (f"Ka0s WoW Tools needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer "
                f"(found {major}.{minor}).")
    return None


def add_vendor_path(vendor_dir: Path = VENDOR_DIR) -> None:
    """Put vendor/ first on sys.path so bundled libraries win over anything installed."""
    path = str(vendor_dir)
    if path not in sys.path:
        sys.path.insert(0, path)


def _one_line(text: str) -> str:
    return " | ".join(part.strip() for part in str(text).splitlines() if part.strip())


def log_bootstrap_failure(where: str, problem: BaseException | str, *, path: Path | None = None,
                          now: datetime | None = None) -> None:
    """Append a `bootstrap.failed` record to the launcher log (path defaults to LAUNCHER_LOG, read at call time).

    An exception adds its type and the last TRACEBACK_LINES lines of its traceback, each indented so the trim keeps
    them with their record. Never raises: a folder that can't be written is skipped silently."""
    try:
        target = LAUNCHER_LOG if path is None else path
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        fields = f"where={where}"
        lines: list[str] = []
        if isinstance(problem, BaseException):
            fields += f" type={type(problem).__name__}"
            text = "".join(traceback.format_exception(type(problem), problem, problem.__traceback__))
            lines = ["    " + line.strip() for line in text.splitlines() if line.strip()][-TRACEBACK_LINES:]
        record = "\n".join([f"{stamp} bootstrap.failed {fields} message={_one_line(str(problem))}", *lines])
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", errors="backslashreplace") as handle:
            handle.write(record + "\n")
    except Exception:  # noqa: BLE001 - the last-resort log must never take the start-up down with it
        return


def _line_dates(line: bytes) -> list[date] | None:
    """Every date the start of a line can mean (two for an ambiguous day/month), or None when it has none."""
    if match := _YEAR_FIRST.match(line):
        readings = [(int(match[1]), int(match[2]), int(match[3]))]
    elif match := _YEAR_LAST.match(line):
        first, second, year = int(match[1]), int(match[2]), int(match[3])
        readings = [(year, second, first), (year, first, second)]
    else:
        return None
    dates = []
    for year, month, day in readings:
        with contextlib.suppress(ValueError):
            dates.append(date(year, month, day))
    return dates or None


def trim_launcher_log(path: Path, retention_days: int, now: datetime) -> None:
    """Drop the launcher log's records older than retention_days (LN6). Never raises.

    A record is a line with a leading date plus the indented lines under it. It is dropped only when every reading
    of its date is older than the cutoff; a line with no date is kept. When no line's date can be read at all, the
    last UNDATED_KEEP_LINES lines are kept instead. The file is rewritten (temp file, then replace) only when
    something was dropped; bytes are kept as written (cmd.exe writes in the console code page)."""
    try:
        if not path.is_file():
            return
        lines = path.read_bytes().splitlines(keepends=True)
        cutoff = now.date() - timedelta(days=retention_days)
        kept: list[bytes] = []
        dated = False
        keep = True
        for line in lines:
            if line[:1] in (b" ", b"\t"):
                if keep:
                    kept.append(line)
                continue
            dates = _line_dates(line)
            dated = dated or dates is not None
            keep = dates is None or any(day >= cutoff for day in dates)
            if keep:
                kept.append(line)
        if not dated:
            kept = lines[-UNDATED_KEEP_LINES:]
        if len(kept) == len(lines):
            return
        partial = path.with_name(path.name + ".partial")
        try:
            partial.write_bytes(b"".join(kept))
            os.replace(partial, path)
        finally:
            with contextlib.suppress(OSError):
                partial.unlink()
    except Exception:  # noqa: BLE001 - trimming a log is never worth failing the start-up for
        return
