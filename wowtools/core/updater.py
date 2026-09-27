"""Suite updater: check GitHub Releases on launch and update the whole suite in place."""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from wowtools import __version__
from wowtools.core.config import GENERAL, Config
from wowtools.core.events import log_event

REPO = "tusharsaxena/wow-tools"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_INTERVAL = timedelta(hours=24)
USER_AGENT = f"ka0s-wow-tools/{__version__}"


class UpdateError(Exception):
    """Checking for or applying an update failed."""


def parse_version(text: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", text.strip())
    if not match:
        raise ValueError(f"not a version: {text!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_newer(candidate: str, current: str) -> bool:
    try:
        return parse_version(candidate) > parse_version(current)
    except ValueError:
        return False


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    notes: str = ""
    zipball_url: str = ""
    html_url: str = ""

    @classmethod
    def from_version(cls, version: str) -> ReleaseInfo:
        tag = f"v{version}"
        return cls(version, tag, "", f"https://api.github.com/repos/{REPO}/zipball/{tag}",
                   f"https://github.com/{REPO}/releases/tag/{tag}")


def fetch_latest(*, timeout: float = 3.0, opener=urllib.request.urlopen) -> ReleaseInfo | None:
    """The latest published (non-draft, non-prerelease) release, or None if there is none."""
    request = urllib.request.Request(LATEST_URL, headers={"Accept": "application/vnd.github+json",
                                                          "User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if payload.get("draft") or payload.get("prerelease"):
        return None
    tag = str(payload.get("tag_name", ""))
    version = tag[1:] if tag.startswith("v") else tag
    parse_version(version)
    return ReleaseInfo(version, tag, payload.get("body") or "", payload.get("zipball_url") or "",
                       payload.get("html_url") or "")


def check_for_update(cfg: Config, *, current: str = __version__, now: datetime | None = None,
                     fetch: Callable[[], ReleaseInfo | None] | None = None, force: bool = False,
                     raise_errors: bool = False) -> ReleaseInfo | None:
    """Return the newer release, if any. Throttled to once per CHECK_INTERVAL unless force=True."""
    now = now or datetime.now(timezone.utc)
    fetch = fetch or fetch_latest
    last = cfg.last_update_check
    if not force and last is not None and now - last < CHECK_INTERVAL:
        cached = cfg.latest_seen_version
        log_event("update.checked", current=current, latest=cached, throttled=True)
        if cached and is_newer(cached, current):
            log_event("update.available", current=current, latest=cached)
            return ReleaseInfo.from_version(cached)
        return None
    try:
        release = fetch()
    except Exception as exc:  # offline, rate limited, bad JSON: never bother the user
        log_event("update.check_failed", error=f"{type(exc).__name__}: {exc}")
        if raise_errors:
            raise UpdateError(f"could not reach GitHub: {exc}") from exc
        return None
    cfg.set(GENERAL, "last_update_check", now.isoformat(timespec="seconds"), log=False)
    if release is not None:
        cfg.set(GENERAL, "latest_seen_version", release.version, log=False)
    cfg.save_if_exists()
    log_event("update.checked", current=current, latest=release.version if release else None, throttled=False)
    if release is not None and is_newer(release.version, current):
        log_event("update.available", current=current, latest=release.version)
        return release
    return None


class UpdateCheck:
    """Run check_for_update in a daemon thread so launch never waits on the network."""

    def __init__(self, cfg: Config, *, check: Callable[[Config], ReleaseInfo | None] = check_for_update) -> None:
        self.cfg = cfg
        self.release: ReleaseInfo | None = None
        self._check = check
        self._thread = threading.Thread(target=self._run, name="wowtools-update-check", daemon=True)

    def start(self) -> UpdateCheck:
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            self.release = self._check(self.cfg)
        except Exception:
            self.release = None

    def notice(self, timeout: float = 0.5) -> str | None:
        self._thread.join(timeout)
        if self.release is None:
            return None
        return (f"Ka0s WoW Tools v{self.release.version} is available (you have v{__version__}). "
                "Update with: python -m wowtools update")
