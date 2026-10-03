"""Suite updater: check GitHub Releases on launch and update the whole suite in place."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from wowtools import __version__
from wowtools.core.bootstrap import REPO_ROOT
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


# --- applying an update ---------------------------------------------------------------------
MANAGED_DIRS = ("wowtools", "vendor", "scripts", "docs")
MANAGED_FILES = ("wow-tools.cmd", "wow-tools.sh", "requirements.txt", ".gitattributes", "LICENSE")
# Program files earlier versions shipped that no longer exist; a zip update removes them (and backs them up).
RETIRED_FILES = ("wtf-cleaner.cmd", "wtf-cleaner.sh")
BACKUP_DIR_NAME = ".update-backup"
_VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def install_kind(root: Path = REPO_ROOT) -> str:
    return "git" if (root / ".git").exists() else "zip"


def apply_update(release: ReleaseInfo, *, root: Path = REPO_ROOT, current: str = __version__,
                 runner=subprocess.run, download: Callable[[str, Path], None] | None = None) -> str:
    kind = install_kind(root)
    try:
        if kind == "git":
            _apply_git(root, release.tag, runner)
        else:
            _apply_zip(root, release, current, download or _download)
    except UpdateError as exc:
        log_event("update.failed", method=kind, error=str(exc))
        raise
    log_event("update.applied", method=kind, **{"from": current, "to": release.version})
    return f"Updated Ka0s WoW Tools to v{release.version}. Restart to use the new version."


def _git(root: Path, runner, *args: str) -> str:
    try:
        proc = runner(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise UpdateError("git is not available. Install git, or download the release zip instead.") from exc
    if proc.returncode != 0:
        raise UpdateError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout


def _apply_git(root: Path, tag: str, runner) -> None:
    if _git(root, runner, "status", "--porcelain").strip():
        raise UpdateError("You have local changes in the wow-tools folder. Commit or stash them, then update again.")
    _git(root, runner, "fetch", "--tags", "--force", "origin")
    _git(root, runner, "merge", "--ff-only", tag)


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, dest.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except (OSError, urllib.error.URLError) as exc:
        raise UpdateError(f"download failed: {exc}") from exc


def _managed_names(folder: Path) -> list[str]:
    names = [name for name in (*MANAGED_DIRS, *MANAGED_FILES, *RETIRED_FILES) if (folder / name).exists()]
    names += sorted(p.name for p in folder.glob("*.md") if p.is_file())
    return names


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _rollback(root: Path, backup: Path) -> None:
    saved = {p.name for p in backup.iterdir()}
    for name in set(_managed_names(root)) | saved:
        try:
            _remove(root / name)
        except OSError:
            pass
    for name in saved:
        _copy(backup / name, root / name)


def _apply_zip(root: Path, release: ReleaseInfo, current: str, download: Callable[[str, Path], None]) -> None:
    if not release.zipball_url:
        raise UpdateError("the release has no download URL")
    with tempfile.TemporaryDirectory(prefix="wowtools-update-") as tmp:
        work = Path(tmp)
        archive = work / "release.zip"
        download(release.zipball_url, archive)
        try:
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(work / "extract")
        except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError, EOFError) as exc:
            raise UpdateError(f"the downloaded file is not a valid zip: {exc}") from exc
        tops = [p for p in (work / "extract").iterdir() if p.is_dir()]
        if len(tops) != 1:
            raise UpdateError("unexpected release layout")
        staging = tops[0]
        init = staging / "wowtools" / "__init__.py"
        match = _VERSION_RE.search(init.read_text(encoding="utf-8")) if init.is_file() else None
        if not match or match.group(1) != release.version:
            raise UpdateError(f"the download does not contain version {release.version}")

        backup = root / BACKUP_DIR_NAME / current
        if backup.exists():
            shutil.rmtree(backup)
        backup.mkdir(parents=True)
        old_names = _managed_names(root)
        try:
            for name in old_names:
                _copy(root / name, backup / name)
        except OSError as exc:
            raise UpdateError(f"could not back up the current version: {exc}") from exc
        try:
            for name in old_names:
                _remove(root / name)
            for name in _managed_names(staging):
                _copy(staging / name, root / name)
        except OSError as exc:
            try:
                _rollback(root, backup)
            except OSError as rollback_exc:
                raise UpdateError(f"update failed ({exc}) and the rollback also failed ({rollback_exc}). "
                                  f"Your previous version is saved in {backup}") from exc
            raise UpdateError(f"update failed and was rolled back: {exc}") from exc


def run_update_command(argv: list[str], cfg: Config, *, stdout=None, stderr=None,
                       check=check_for_update, apply=apply_update) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = argparse.ArgumentParser(prog="wow-tools update",
                                     description="Check for and apply Ka0s WoW Tools updates.")
    parser.add_argument("--check", action="store_true", help="only report whether an update is available")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code in (0, None) else 1
    try:
        release = check(cfg, force=True, raise_errors=True)
    except UpdateError as exc:
        print(f"Could not check for updates: {exc}", file=stderr)
        return 1
    if release is None:
        print(f"Ka0s WoW Tools v{__version__} is up to date.", file=stdout)
        return 0
    if args.check:
        print(f"Update available: v{release.version} (you have v{__version__}). "
              "Run: wow-tools update", file=stdout)
        return 10
    log_event("ui.selection", screen="cli", control="update", value="accepted")
    try:
        print(apply(release), file=stdout)
    except UpdateError as exc:
        print(f"Update failed: {exc}", file=stderr)
        return 1
    return 0
