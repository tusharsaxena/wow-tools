"""Run one function over independent units (usually game versions), several at a time. UI-free.

run_units() maps `fn(unit, report)` over `units` with at most `parallelism` running at once ([general] parallelism,
Config.parallelism). With 1 (or a single unit) it is a plain loop in the calling thread, in input order, so a run
with parallelism 1 behaves as before this module existed. Results always come back in input order.

A unit that raises does not stop the others: its exception is kept in its UnitResult (and logged as
parallel.unit_failed), like Interface Backup's back_up_all always kept one flavor's failure from stopping the next.
A BaseException that is not an Exception (KeyboardInterrupt, SystemExit) still propagates, after every unit already
started has finished.

Where it runs: inside the tool's one Textual thread worker (run_worker(thread=True)), so Textual still sees a single
job. run_units returns only once every pool thread is done, so the caller's single `with activity.running():`
around it covers them all and quit's wait_idle still waits for every one. The runner does not enter
activity.running() itself: a read-only scan does not hold up quit.

What several units may share, and is safe to share: log_event (EventLog holds a lock), a JournalWriter (locked),
ThrottledProgress (locked, throttled per thread) and the `progress` callback here (called from the unit's own
thread; it must be thread-safe, for example a ThrottledProgress that forwards through call_from_thread).
"""
from __future__ import annotations

import time
import traceback
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Generic, TypeVar

from wowtools.core.config import MAX_PARALLELISM, MIN_PARALLELISM
from wowtools.core.events import log_event
from wowtools.core.fsutil import safe_progress

U = TypeVar("U")
R = TypeVar("R")

THREAD_PREFIX = "wowtools-unit"

Report = Callable[..., None]


@dataclass
class UnitResult(Generic[U, R]):
    """What one unit gave: its value, or the exception that stopped it (value is then None)."""
    unit: U
    value: R | None = None
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def clamp_parallelism(value: int) -> int:
    """Keep a parallelism inside MIN_PARALLELISM..MAX_PARALLELISM."""
    return max(MIN_PARALLELISM, min(MAX_PARALLELISM, int(value)))


def workers_for(parallelism: int, units: int) -> int:
    """Threads a run of `units` units uses: the clamped parallelism, never more than there are units (at least 1)."""
    return max(1, min(clamp_parallelism(parallelism), units))


def run_units(units: Sequence[U], fn: Callable[[U, Report], R], *, parallelism: int, what: str = "units",
              label: Callable[[U], str] = str, progress: Callable[..., None] | None = None,
              on_start: Callable[[U, int, int], None] | None = None,
              on_done: Callable[[UnitResult[U, R]], None] | None = None) -> list[UnitResult[U, R]]:
    """Call fn(unit, report) for every unit, at most `parallelism` at once; return one UnitResult per unit, in
    input order.

    `report(*args)` is the unit's progress callback: it calls progress(unit, *args), so a progress display can tell
    the units apart. on_start(unit, index, total) runs when a unit starts and on_done(result) when it ends, both in
    the unit's thread. Errors in progress, on_start and on_done are swallowed (safe_progress): a broken display never
    stops a run. `what` and `label` name the run and its units in the log."""
    items = list(units)
    workers = workers_for(parallelism, len(items))
    total = len(items)
    tell_start, tell_done, tell = safe_progress(on_start), safe_progress(on_done), safe_progress(progress)
    log_event("parallel.started", what=what, units=[label(u) for u in items], workers=workers)
    started = time.monotonic()

    def one(index: int, unit: U) -> UnitResult[U, R]:
        tell_start(unit, index, total)
        result: UnitResult[U, R] = UnitResult(unit)
        try:
            result.value = fn(unit, lambda *args: tell(unit, *args))
        except Exception as exc:  # noqa: BLE001 - one unit's failure is its own; the others carry on
            result.error = exc
            log_event("parallel.unit_failed", what=what, unit=label(unit), type=type(exc).__name__,
                      message=str(exc),
                      traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        tell_done(result)
        return result

    if workers == 1:
        results = [one(index, unit) for index, unit in enumerate(items)]
    else:
        # The with block waits for every thread (shutdown(wait=True)), also when a BaseException propagates.
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=THREAD_PREFIX) as pool:
            futures = [pool.submit(one, index, unit) for index, unit in enumerate(items)]
            try:
                results = [future.result() for future in futures]
            except BaseException:
                for future in futures:
                    future.cancel()  # units not started yet never start; running ones finish first
                raise
    log_event("parallel.finished", what=what, units=total, failed=sum(not r.ok for r in results), workers=workers,
              seconds=round(time.monotonic() - started, 3))
    return results

