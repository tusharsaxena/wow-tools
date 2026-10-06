"""Run one function over independent units (usually game versions), several at a time. UI-free.

run_units() maps `fn(unit, report)` over `units` with at most `parallelism` running at once ([general] parallelism,
Config.parallelism). With 1 (or a single unit) it is a plain loop in the calling thread, in input order, so a run
with parallelism 1 behaves as before this module existed. Results always come back in input order.

A unit that raises does not stop the others: its exception is kept in its UnitResult (and logged as
parallel.unit_failed), like Interface Backup's back_up_all always kept one flavor's failure from stopping the next.
With stop_on_error=True a unit's exception instead keeps the units not started yet from starting (their UnitResult
has started=False); the units already running finish. With parallelism 1 that is a serial loop that stops at the
first failure, as the per-flavor loops did before they ran here (Ace3 undo's snapshots, the scans' unexpected
errors).
A BaseException that is not an Exception (KeyboardInterrupt, SystemExit) still propagates, after every unit already
started has finished; a unit that had not started by the time it was raised never starts (parallel.finished is then
not logged).

Where it runs: inside the tool's one Textual thread worker (run_worker(thread=True)), so Textual still sees a single
job. run_units returns only once every pool thread is done, so the caller's single `with activity.running():`
around it covers them all and quit's wait_idle still waits for every one. The runner does not enter
activity.running() itself: a read-only scan does not hold up quit.

What several units may share, and is safe to share: log_event (EventLog holds a lock), a JournalWriter (locked),
ThrottledProgress (locked, throttled per thread) and the `progress` callback here (called from the unit's own
thread as progress(unit, stage, current, total, detail); it must be thread-safe: a ProgressScreen's report_unit
(ui/dialogs.py, which writes a locked ProgressBoard the UI thread draws on a timer, with on_start=start_unit)).
"""
from __future__ import annotations

import threading
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
    started: bool = False  # False only for a unit stop_on_error (or a BaseException) kept from starting

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
              on_done: Callable[[UnitResult[U, R]], None] | None = None,
              stop_on_error: bool = False) -> list[UnitResult[U, R]]:
    """Call fn(unit, report) for every unit, at most `parallelism` at once; return one UnitResult per unit, in
    input order.

    `report(*args)` is the unit's progress callback: it calls progress(unit, *args), so a progress display can tell
    the units apart. on_start(unit, index, total) runs when a unit starts and on_done(result) when it ends, both in
    the unit's thread. Errors in progress, on_start and on_done are swallowed (safe_progress): a broken display never
    stops a run. `what` and `label` name the run and its units in the log. stop_on_error: a unit's exception keeps
    the units not started yet from starting (on_start and on_done are not called for them)."""
    items = list(units)
    workers = workers_for(parallelism, len(items))
    total = len(items)
    tell_start, tell_done, tell = safe_progress(on_start), safe_progress(on_done), safe_progress(progress)
    log_event("parallel.started", what=what, units=[label(u) for u in items], workers=workers)
    started = time.monotonic()
    stopping = threading.Event()  # set by a unit's BaseException: a unit not yet started never starts
    failed = threading.Event()  # set by a unit's Exception: with stop_on_error, a unit not yet started never starts

    def one(index: int, unit: U) -> UnitResult[U, R]:
        result: UnitResult[U, R] = UnitResult(unit)
        if stopping.is_set():
            return result  # never read: run_units raises the earlier unit's BaseException
        if stop_on_error and failed.is_set():
            return result  # not started: an earlier unit failed
        result.started = True
        tell_start(unit, index, total)
        try:
            result.value = fn(unit, lambda *args: tell(unit, *args))
        except Exception as exc:  # noqa: BLE001 - one unit's failure is its own; the others carry on
            result.error = exc
            failed.set()
            log_event("parallel.unit_failed", what=what, unit=label(unit), type=type(exc).__name__,
                      message=str(exc),
                      traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        except BaseException:
            stopping.set()
            raise
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
                    future.cancel()  # queued units never start (`stopping` covers the ones a thread already took)
                raise
    log_event("parallel.finished", what=what, units=total, failed=sum(not r.ok for r in results),
              not_started=sum(not r.started for r in results), workers=workers,
              seconds=round(time.monotonic() - started, 3))
    return results

