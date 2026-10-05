"""Progress reporting shared by every tool's workers. UI-free (the forward callback is what reaches the UI):
ThrottledProgress for reports forwarded to the UI thread, ProgressBoard for the state a progress popup reads.

safe_progress, which keeps an error in a progress callback from disturbing a run, is in fsutil."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

# Seconds between two progress reports a worker sends to the UI thread (ThrottledProgress): each one is a blocking
# call_from_thread (~0.6 ms), and an Interface folder of tens of thousands of files reported per file spent most of
# a backup or restore in those round trips.
PROGRESS_INTERVAL = 0.1

class ThrottledProgress:
    """progress(stage, current, total, detail) for a job's workers: forwards a report when the stage changes, when
    it has no count (total 0) or ends a stage (current >= total), or when `interval` seconds passed since the last
    one forwarded; the others are dropped. reset() forwards the next report whatever it is (a new flavor).

    Several worker threads may share one. The stage, the time of the last report forwarded and the reset flag are
    kept per thread, so each worker is throttled on its own (at most one report per `interval` each, plus its stage
    changes and ends) and two workers on different stages do not turn each other's reports into stage changes.
    Workers that share one should report distinct stages (a unit's label in it), or their counts mix in one bar.
    The decision and the forward both run under one lock, so reports reach the UI in the order they were decided:
    a report decided earlier never lands after a later stage end. `forward` must not call this object again (the
    lock is not re-entrant); a blocking call_from_thread is fine, the UI thread never reports progress.

    tagged=True takes core/parallel.py's unit-tagged reports, progress(unit, stage, current, total, detail): the
    unit and the stage together are the stage it tracks, the counts are the next two arguments, and every argument,
    the unit included, is forwarded. Pass it as run_units(progress=...)."""

    def __init__(self, forward: Callable[..., None], interval: float = PROGRESS_INTERVAL,
                 clock: Callable[[], float] = time.monotonic, *, tagged: bool = False):
        self.forward = forward
        self.tagged = tagged
        self.interval = interval
        self.clock = clock
        self._lock = threading.Lock()
        self._state: dict[int, tuple[object, float]] = {}  # thread id -> (stage, time of its last forward)

    def reset(self) -> None:
        with self._lock:
            self._state.clear()

    def __call__(self, *args: Any) -> None:
        lead = 2 if self.tagged else 1  # leading arguments that name the stage: (unit, stage) or (stage,)
        stage = tuple(args[:lead])
        current, total = (args[lead], args[lead + 1]) if len(args) >= lead + 2 else (0, 0)
        thread = threading.get_ident()
        with self._lock:
            now = self.clock()
            last = self._state.get(thread)
            due = (last is None or stage != last[0] or not total or current >= total
                   or now - last[1] >= self.interval)
            if not due:
                return
            self._state[thread] = (stage, now)
            self.forward(*args)


_PLACEHOLDER = object()  # the unit of untagged reports before (or without) any unit start: an unnamed run


@dataclass(frozen=True)
class RowView:
    """One unit row of a progress display: the unit it shows (label), its stage and counts. `used` is False for a
    row no unit has taken yet; `finished` is True once its unit ended (the row keeps showing it until reused)."""
    label: str = ""
    stage: str = ""
    current: int = 0
    total: int = 0
    used: bool = False
    finished: bool = False


@dataclass(frozen=True)
class BoardView:
    """What a progress display shows at one moment: the rows, `done` of `units` units finished and the newest
    detail (with the label of the unit that reported it)."""
    rows: tuple[RowView, ...]
    done: int
    units: int
    detail: str = ""
    detail_label: str = ""


class ProgressBoard:
    """The progress of a run over `units` units (game versions), shown in a fixed number of `rows`. UI-free and
    thread-safe: every worker thread writes to it under one lock, and the display reads snapshot() on its own timer
    (ui/dialogs.py ProgressScreen, ~10 Hz), so no worker waits for the UI thread on a report.

    A unit takes a row when it starts (start(), or its first report_unit()): a row no unit used yet first, then the
    row of the unit that finished first. A thread runs one unit at a time, so a thread starting a unit finishes the
    one it ran before (a serial run that only says which unit starts next). Untagged report()s go to the unit the
    calling thread runs; with none, to an unnamed placeholder unit (row 0), which the first named start replaces.
    `first_stage` puts that placeholder up at once, so the display has a stage before the first report."""

    def __init__(self, rows: int = 1, units: int = 1, *, label: Callable[[Any], str] = str,
                 first_stage: str = "") -> None:
        self.label = label
        self._lock = threading.Lock()
        self._rows = [RowView() for _ in range(max(1, rows))]
        self._running: dict[Any, int] = {}  # unit -> its row
        self._by_thread: dict[int, Any] = {}  # thread id -> the unit it runs
        self._finished: set[Any] = set()
        self._freed: list[int] = []  # rows of finished units, oldest first
        self._units = max(1, units)
        self._detail = ("", "")
        self._version = 0
        if first_stage:
            self._take(_PLACEHOLDER, "")
            self._set(self._running[_PLACEHOLDER], stage=first_stage)

    # --- writes (any thread) ---------------------------------------------------------------------------
    def start(self, unit: Any, index: int | None = None, total: int | None = None) -> None:
        """`unit` starts (index and total as run_units' on_start and the tools' on_flavor give them: total, when
        given, is the run's unit count)."""
        with self._lock:
            if total:
                self._units = max(total, len(self._finished))
            self._start(unit)
            self._version += 1

    def finish(self, unit: Any = None) -> None:
        """`unit` (by default the calling thread's) ended, well or not: its row shows it done until reused."""
        with self._lock:
            if unit is None:
                unit = self._by_thread.get(threading.get_ident())
            if unit is not None and unit in self._running:
                self._finish(unit)
                self._version += 1

    def finish_all(self) -> None:
        """The run ended: every unit still running (the last one of a serial run, the placeholder) is done, so the
        board ends at `units` of `units`."""
        with self._lock:
            for unit in list(self._running):
                self._finish(unit)
            self._version += 1

    def report(self, stage: str, current: int = 0, total: int = 0, detail: str | None = None) -> None:
        """progress(stage, current, total, detail) of the unit the calling thread runs."""
        with self._lock:
            unit = self._by_thread.get(threading.get_ident())
            if unit is None or unit not in self._running:
                unit = _PLACEHOLDER
                if unit not in self._running:
                    self._finished.discard(unit)
                    self._take(unit, "")
                self._by_thread[threading.get_ident()] = unit
            self._report(unit, stage, current, total, detail)

    def report_unit(self, unit: Any, stage: str, current: int = 0, total: int = 0,
                    detail: str | None = None) -> None:
        """progress(unit, stage, current, total, detail): run_units' unit-tagged reports. A unit not started yet
        starts; a report of a unit already finished (late, from its thread) is dropped."""
        with self._lock:
            if unit in self._finished:
                return
            if unit not in self._running:
                self._start(unit)
            self._by_thread[threading.get_ident()] = unit
            self._report(unit, stage, current, total, detail)

    # --- reads -------------------------------------------------------------------------------------------
    def snapshot(self) -> tuple[int, BoardView]:
        """(version, view): the version changes with every write, so a display redraws only what changed."""
        with self._lock:
            return self._version, BoardView(tuple(self._rows), len(self._finished),
                                            max(self._units, len(self._finished)), *self._detail)

    # --- under the lock ------------------------------------------------------------------------------------
    def _start(self, unit: Any) -> None:
        thread = threading.get_ident()
        before = self._by_thread.get(thread)
        if before is not None and before is not _PLACEHOLDER and before != unit and before in self._running:
            self._finish(before)  # a thread runs one unit at a time
        if _PLACEHOLDER in self._running:
            self._rows[self._running.pop(_PLACEHOLDER)] = RowView()  # a named unit replaces the placeholder
            self._unbind(_PLACEHOLDER)
        self._finished.discard(unit)
        if unit not in self._running:
            self._take(unit, self.label(unit))
        self._by_thread[thread] = unit

    def _take(self, unit: Any, label: str) -> None:
        unused = [i for i, row in enumerate(self._rows) if not row.used]
        if unused:
            row = unused[0]
        elif self._freed:
            row = self._freed.pop(0)
        else:  # more units running than rows (the caller ran more threads than it said): reuse the oldest's row
            oldest = next(iter(self._running))
            row = self._running.pop(oldest)
        self._running[unit] = row
        self._rows[row] = RowView(label=label, used=True)

    def _finish(self, unit: Any) -> None:
        row = self._running.pop(unit)
        self._finished.add(unit)
        view = self._rows[row]
        self._rows[row] = RowView(view.label, view.stage, view.total or 1, view.total or 1, used=True, finished=True)
        self._freed.append(row)
        self._unbind(unit)

    def _unbind(self, unit: Any) -> None:
        for thread, running in list(self._by_thread.items()):
            if running is unit or (unit is not _PLACEHOLDER and running == unit):
                del self._by_thread[thread]

    def _report(self, unit: Any, stage: str, current: int, total: int, detail: str | None) -> None:
        row = self._running[unit]
        self._set(row, stage=stage, current=current, total=total)
        if detail is not None:
            self._detail = (detail, self._rows[row].label)
        self._version += 1

    def _set(self, row: int, **changes: Any) -> None:
        self._rows[row] = replace(self._rows[row], **changes)
