"""Is file-changing work running right now? A process-wide counter that worker threads enter and leave.

Workers wrap a clean, organize or undo in `with running():`. Before the suite releases the instance lock it calls
`wait_idle()`, so a second copy can never take the lock while this one is still changing files (for example after
an exit that bypassed the quit guard). A plain thread primitive is used because Textual's event loop is gone by the
time the suite gets there.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

_condition = threading.Condition()
_active = 0


@contextmanager
def running() -> Iterator[None]:
    """Mark file-changing work as running until the block ends (normally or by an exception)."""
    global _active
    with _condition:
        _active += 1
    try:
        yield
    finally:
        with _condition:
            _active -= 1
            if _active == 0:
                _condition.notify_all()


def wait_idle(timeout: float | None = None) -> bool:
    """Wait until no work is running, at most `timeout` seconds (None: forever). True if idle at the end."""
    with _condition:
        return _condition.wait_for(lambda: _active == 0, timeout=timeout)
