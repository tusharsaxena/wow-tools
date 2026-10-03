"""One running copy of Ka0s WoW Tools at a time: a lock file next to the program.

The lock file holds who took it (pid, host, start time, a random token). A second copy finds the file and
asks the user whether to quit or take the lock over (the file may be left over from a crash). The lock is
removed on exit, but only by the copy that holds it.
"""
from __future__ import annotations

import json
import os
import platform
import secrets
import socket
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from wowtools.core.bootstrap import REPO_ROOT

LOCK_PATH = REPO_ROOT / "wow-tools.lock"


@dataclass(frozen=True)
class LockInfo:
    pid: int | None
    host: str
    started: str
    platform: str
    token: str = ""

    @property
    def stale(self) -> bool | None:
        """True when the holder is known to be gone, False when it is known to be running, None if unknown.

        Only checked on POSIX for a lock taken on this host (Windows pids, or another host, cannot be checked)."""
        if self.pid is None or self.host != socket.gethostname() or os.name != "posix" \
                or self.platform != _platform():
            return None
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return False  # exists but belongs to someone else
        return False

    def describe(self) -> str:
        who = f"process {self.pid}" if self.pid is not None else "an unknown process"
        return f"{who} on {self.host or 'an unknown computer'} ({self.platform or 'unknown'}), started {self.started or 'at an unknown time'}"


def _platform() -> str:
    return "wsl" if "microsoft" in platform.release().lower() else platform.system().lower()


class InstanceLock:
    def __init__(self, path: Path = LOCK_PATH) -> None:
        self.path = path
        self.info = LockInfo(os.getpid(), socket.gethostname(), datetime.now().isoformat(timespec="seconds"),
                             _platform(), secrets.token_hex(8))
        self.held = False

    def acquire(self) -> LockInfo | None:
        """Take the lock. Returns None on success, or the current holder's details if the lock file exists."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            return self.read() or LockInfo(None, "", "", "")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(self.info)))
        self.held = True
        return None

    def take_over(self) -> None:
        """Overwrite whatever lock file is there with ours (the user chose to proceed anyway)."""
        partial = self.path.with_name(self.path.name + ".partial")
        partial.write_text(json.dumps(asdict(self.info)), encoding="utf-8")
        partial.replace(self.path)
        self.held = True

    def read(self) -> LockInfo | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            pid = data.get("pid")
            return LockInfo(pid if isinstance(pid, int) else None, str(data.get("host") or ""),
                            str(data.get("started") or ""), str(data.get("platform") or ""),
                            str(data.get("token") or ""))
        except (OSError, ValueError, AttributeError):
            return None

    def release(self) -> None:
        """Remove the lock file if it is still ours (another copy may have taken it over)."""
        if not self.held:
            return
        self.held = False
        current = self.read()
        if current is not None and current.token == self.info.token:
            try:
                self.path.unlink()
            except OSError:
                pass
