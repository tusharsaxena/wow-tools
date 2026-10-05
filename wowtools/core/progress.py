"""Progress reporting shared by every tool's workers. UI-free (the forward callback is what reaches the UI).

safe_progress, which keeps an error in a progress callback from disturbing a run, is in fsutil."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
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
