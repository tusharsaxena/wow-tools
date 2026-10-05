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
    """progress(stage, current, total, detail) for a job's worker: forwards a report when the stage changes, when
    it has no count (total 0) or ends a stage (current >= total), or when `interval` seconds passed since the last
    one forwarded; the others are dropped. reset() forwards the next report whatever it is (a new flavor).

    Safe to call from several threads at once:
    the decision is taken under a lock, the forward itself runs outside it (so a slow UI never blocks the other
    workers' decisions)."""

    def __init__(self, forward: Callable[..., None], interval: float = PROGRESS_INTERVAL,
                 clock: Callable[[], float] = time.monotonic):
        self.forward = forward
        self.interval = interval
        self.clock = clock
        self._lock = threading.Lock()
        self._stage: object = None
        self._last = 0.0
        self._fresh = True

    def reset(self) -> None:
        with self._lock:
            self._fresh = True

    def __call__(self, *args: Any) -> None:
        stage = args[0] if args else None
        current, total = (args[1], args[2]) if len(args) >= 3 else (0, 0)
        with self._lock:
            now = self.clock()
            due = (self._fresh or stage != self._stage or not total or current >= total
                   or now - self._last >= self.interval)
            if not due:
                return
            self._fresh, self._stage, self._last = False, stage, now
        self.forward(*args)
