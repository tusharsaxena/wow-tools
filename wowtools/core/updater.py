"""Suite updater: check GitHub Releases on launch and update the whole suite in place."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wowtools import __version__
from wowtools.core.bootstrap import REPO_ROOT
from wowtools.core.config import GENERAL, Config
from wowtools.core.events import log_event

REPO = "tusharsaxena/wow-tools"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_INTERVAL = timedelta(hours=24)
USER_AGENT = f"ka0s-wow-tools/{__version__}"
GIT_TIMEOUT_S = 120  # a git step that takes longer is stuck (a prompt, a dead connection): give up


# Ctrl+C during an update, before the new version was fully in place: a zip install still has the version it had
# (nothing was replaced yet, or _apply_zip put a half-done swap back; a failed rollback is RollbackFailed instead);
# a git checkout is left to git. A Ctrl+C after the swap is not an interruption: the update is applied.
UPDATE_STOPPED = ("Update stopped before it finished. A zip install still has the version you had; "
                  "in a git checkout, check `git status`.")


class UpdateError(Exception):
    """Checking for or applying an update failed."""


class RollbackFailed(UpdateError):
    """A zip update failed or was interrupted and putting the old version back failed too: the install is broken
    and the message names the .update-backup/<version> folder that holds the old version."""


class AssetMissing(UpdateError):
    """A release asset was not found (HTTP 404): the release did not publish it."""


SUMS_ASSET = "SHA256SUMS"


def release_zip_name(version: str) -> str:
    """The release's program zip asset, built by scripts/build_release.py (docs/releasing.md)."""
    return f"wow-tools-v{version}.zip"


def _asset_url(tag: str, name: str) -> str:
    return f"https://github.com/{REPO}/releases/download/{tag}/{name}"


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
    assets: dict[str, str] = field(default_factory=dict, compare=False, hash=False)  # name -> download URL

    @classmethod
    def from_version(cls, version: str) -> ReleaseInfo:
        """A release known only by its version (the throttled check's cache). The asset URLs follow GitHub's fixed
        pattern; if the release did not publish them, the download says so (AssetMissing)."""
        tag = f"v{version}"
        assets = {name: _asset_url(tag, name) for name in (release_zip_name(version), SUMS_ASSET)}
        return cls(version, tag, "", f"https://api.github.com/repos/{REPO}/zipball/{tag}",
                   f"https://github.com/{REPO}/releases/tag/{tag}", assets)


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
    version = tag.removeprefix("v")
    parse_version(version)
    assets = {str(a["name"]): str(a["browser_download_url"]) for a in payload.get("assets") or []
              if isinstance(a, dict) and a.get("name") and a.get("browser_download_url")}
    return ReleaseInfo(version, tag, payload.get("body") or "", payload.get("zipball_url") or "",
                       payload.get("html_url") or "", assets)


def persist_check_state(cfg: Config, values: dict[str, str]) -> None:
    """Store what an update check learned ([general] last_update_check, latest_seen_version) and save the file
    if it already exists (the check never creates a config before setup)."""
    for key, value in values.items():
        cfg.set(GENERAL, key, value, log=False)
    cfg.save_if_exists()


def check_for_update(cfg: Config, *, current: str = __version__, now: datetime | None = None,
                     fetch: Callable[[], ReleaseInfo | None] | None = None, force: bool = False,
                     raise_errors: bool = False, verify_cached: bool = False,
                     persist: Callable[[dict[str, str]], None] | None = None) -> ReleaseInfo | None:
    """Return the newer release, if any. Throttled to once per CHECK_INTERVAL unless force=True.

    verify_cached=True asks GitHub again whenever the throttled path would offer the cached version, so a
    release deleted since it was seen is neither announced nor installed (D16). The throttle then still saves
    the request when no update is pending.

    What the check learned is stored with persist(values). The default stores it in cfg right away, which is
    right for single-threaded callers; a check running in a worker thread passes a persist that hands the values
    to the UI thread, so the config is only ever changed and saved on one thread."""
    now = now or datetime.now(timezone.utc)
    fetch = fetch or fetch_latest
    last = cfg.last_update_check
    # A stamp in the future (clock skew, a hand edit, a config from another machine) never throttles (F-026).
    if not force and last is not None and timedelta(0) <= now - last < CHECK_INTERVAL:
        # Only a cached version newer than this one is offered: an empty, hand-edited or older value is not.
        cached = (cfg.latest_seen_version or "").strip()
        log_event("update.checked", current=current, latest=cached or None, throttled=True)
        if not (cached and is_newer(cached, current)):
            return None
        if not verify_cached:
            log_event("update.available", current=current, latest=cached)
            return ReleaseInfo.from_version(".".join(map(str, parse_version(cached))))  # "v1.2.3" -> "1.2.3"
    try:
        release = fetch()
    except Exception as exc:  # offline, rate limited, bad JSON: never bother the user
        log_event("update.check_failed", error=f"{type(exc).__name__}: {exc}")
        if raise_errors:
            raise UpdateError(f"could not reach GitHub: {exc}") from exc
        return None
    # A check that finds no release clears the cache: a release that was deleted (or turned back into a draft)
    # must stop being offered by the throttled checks that follow (D16).
    values = {"last_update_check": now.isoformat(timespec="seconds"),
              "latest_seen_version": release.version if release is not None else ""}
    if persist is None:
        persist_check_state(cfg, values)
    else:
        persist(values)
    log_event("update.checked", current=current, latest=release.version if release else None, throttled=False)
    if release is not None and is_newer(release.version, current):
        log_event("update.available", current=current, latest=release.version)
        return release
    return None


# --- applying an update ---------------------------------------------------------------------
MANAGED_DIRS = ("wowtools", "vendor", "scripts", "docs")
MANAGED_FILES = ("wow-tools.cmd", "wow-tools.sh", "requirements.txt", "requirements.lock", ".gitattributes",
                 "LICENSE")
# Program files earlier versions shipped that no longer exist; a zip update removes them (and backs them up).
RETIRED_FILES = ("wtf-cleaner.cmd", "wtf-cleaner.sh")
BACKUP_DIR_NAME = ".update-backup"
KEEP_UPDATE_BACKUPS = 2  # .update-backup/<version> folders kept after an update (the newest by version)
# Before an old .update-backup/<version> is pruned, the files a user added inside its managed folders are moved here,
# to <root>/update-leftovers/<version>/<same relative path> (#7). An update never touches this folder.
LEFTOVERS_DIR_NAME = "update-leftovers"
_VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def install_kind(root: Path = REPO_ROOT) -> str:
    return "git" if (root / ".git").exists() else "zip"


def apply_update(release: ReleaseInfo, *, root: Path = REPO_ROOT, current: str = __version__,
                 runner=None, download: Callable[[str, Path], None] | None = None,
                 allow_unverified: bool = False) -> str:
    """allow_unverified ([general] allow_unverified_updates) lets a zip install update from a release that has no
    SHA256SUMS asset. A release that has one is always verified."""
    kind = install_kind(root)
    try:
        if kind == "git":
            _apply_git(root, release.tag, runner or _run_bounded)
        else:
            _apply_zip(root, release, current, download or _download, allow_unverified)
    except BaseException as exc:  # logged, then re-raised (an interrupted update is a failed one too)
        log_event("update.failed", method=kind, error=str(exc) or type(exc).__name__)
        raise
    log_event("update.applied", method=kind, **{"from": current, "to": release.version})
    return f"Updated Ka0s WoW Tools to v{release.version}. Restart to use the new version."


def _run_bounded(args: list[str], *, cwd, capture_output: bool = True, text: bool = True, check: bool = False,
                 timeout: float, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """subprocess.run for git, but a timeout really ends it: output goes to temp files (no pipes for a helper such as
    git-remote-https to hold open; on Windows subprocess.run waits for those after a timeout) and the whole process
    tree is killed. stdin is closed so nothing can wait for typed input. Same call shape as subprocess.run."""
    del capture_output, check  # always captured, never raises on a non-zero exit (the caller checks returncode)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        if os.name == "nt":
            proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    start_new_session=True)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            raise
        outputs = []
        for handle in (out, err):
            handle.seek(0)
            data = handle.read()
            outputs.append(data.decode("utf-8", errors="replace") if text else data)
    return subprocess.CompletedProcess(args, proc.returncode, stdout=outputs[0], stderr=outputs[1])


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
        else:
            os.killpg(proc.pid, 9)  # start_new_session: the group is git and everything it started
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
        proc.wait(timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def _git_env(root: Path, runner) -> dict[str, str]:
    """Never let git wait for a password or passphrase nobody can see behind the TUI (F-011). BatchMode is only
    added when the user has no SSH program of their own (GIT_SSH_COMMAND, GIT_SSH or core.sshCommand): setting
    GIT_SSH_COMMAND would override theirs (a specific key, or PuTTY's plink on Windows)."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if env.get("GIT_SSH_COMMAND") or env.get("GIT_SSH"):
        return env
    try:
        proc = runner(["git", "config", "--get", "core.sshCommand"], cwd=root, capture_output=True, text=True,
                      check=False, timeout=GIT_TIMEOUT_S, env=env)
        configured = proc.returncode == 0 and bool((proc.stdout or "").strip())
    except (OSError, subprocess.SubprocessError):
        configured = False  # the next git call reports the problem
    if not configured:
        env["GIT_SSH_COMMAND"] = "ssh -oBatchMode=yes"
    return env


def _git(root: Path, runner, env: dict[str, str], *args: str) -> str:
    try:
        proc = runner(["git", *args], cwd=root, capture_output=True, text=True, check=False,
                      timeout=GIT_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(f"git {args[0]} timed out after {GIT_TIMEOUT_S} seconds. "
                          "Check your network and git credentials, then update again.") from exc
    except OSError as exc:
        raise UpdateError("git is not available. Install git, or download the release zip instead.") from exc
    if proc.returncode != 0:
        raise UpdateError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout


def _apply_git(root: Path, tag: str, runner) -> None:
    # Untracked files (notes, leftovers) never block: a fast-forward only fails if a tracked path conflicts.
    env = _git_env(root, runner)
    if _git(root, runner, env, "status", "--porcelain", "--untracked-files=no").strip():
        raise UpdateError("You have local changes in the wow-tools folder. Commit or stash them, then update again.")
    _git(root, runner, env, "fetch", "--tags", "--force", "origin")
    _git(root, runner, env, "merge", "--ff-only", tag)


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, dest.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise AssetMissing(url) from exc
        raise UpdateError(f"download failed: {exc}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise UpdateError(f"download failed: {exc}") from exc


def _expected_sum(sums_text: str, name: str) -> str:
    """The SHA-256 that SHA256SUMS (sha256sum format: '<hex>  <name>' or '<hex> *<name>') lists for name."""
    for line in sums_text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    raise UpdateError(f"the release's {SUMS_ASSET} does not list {name}, so the download can't be verified")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unverifiable(release: ReleaseInfo) -> UpdateError:
    where = release.html_url or f"https://github.com/{REPO}/releases"
    return UpdateError(f"v{release.version} has no published checksum ({SUMS_ASSET}), so the download can't be "
                       f"verified and nothing was changed. Download it by hand from {where}, or, with the app "
                       "closed, set allow_unverified_updates = true under [general] in config/wow-tools.cfg to "
                       "update anyway (the app does not keep comments in that file when it saves it).")


def _download_release(release: ReleaseInfo, archive: Path, download: Callable[[str, Path], None],
                      allow_unverified: bool) -> None:
    """Download the release's program zip to archive and check it against SHA256SUMS (F-010). Without a SHA256SUMS
    asset this refuses, unless allow_unverified (then the zip asset, or the source zipball, is used as is)."""
    zip_name = release_zip_name(release.version)
    zip_url, sums_url = release.assets.get(zip_name), release.assets.get(SUMS_ASSET)
    expected = None
    if zip_url and sums_url:
        sums = archive.with_name(SUMS_ASSET)
        try:
            download(sums_url, sums)
            expected = _expected_sum(sums.read_text(encoding="utf-8", errors="replace"), zip_name)
        except AssetMissing:
            expected = None
    if expected is None:
        if not allow_unverified:
            raise _unverifiable(release)
        url = zip_url or release.zipball_url
        if not url:
            raise UpdateError("the release has no download URL")
        try:
            download(url, archive)
        except AssetMissing:
            if url == release.zipball_url or not release.zipball_url:
                raise UpdateError(f"the release's download was not found: {url}") from None
            url = release.zipball_url
            download(url, archive)
        log_event("update.unverified", version=release.version, url=url)
        return
    try:
        download(zip_url, archive)
    except AssetMissing:
        raise UpdateError(f"the release lists {zip_name} in {SUMS_ASSET} but does not publish it") from None
    actual = _sha256(archive)
    if actual != expected:
        raise UpdateError(f"the download does not match its published checksum ({zip_name}: expected {expected}, "
                          f"got {actual}). Nothing was changed.")
    log_event("update.verified", version=release.version, asset=zip_name, sha256=actual)


def _shipped_names(staging: Path) -> list[str]:
    """What the release ships at its top level: the managed folders and files, plus its root *.md files."""
    names = [name for name in (*MANAGED_DIRS, *MANAGED_FILES) if (staging / name).exists()]
    names += sorted(p.name for p in staging.glob("*.md") if p.is_file())
    return names


def _replaced_names(root: Path, shipped: list[str]) -> list[str]:
    """The install's program files an update replaces: the managed and retired names, plus the root *.md files
    the release ships. Other root *.md files are the user's (notes, a copied guide) and stay untouched (F-019)."""
    fixed = [name for name in (*MANAGED_DIRS, *MANAGED_FILES, *RETIRED_FILES) if (root / name).exists()]
    return fixed + [name for name in shipped if name not in fixed and (root / name).exists()]


def prune_update_backups(backup_root: Path, keep: int = KEEP_UPDATE_BACKUPS, current: str | None = None) -> list[Path]:
    """Delete all but `keep` .update-backup/<version> folders: the one this update just made (`current`, whatever
    its version: after a downgrade it is the lowest) plus the highest other versions. Anything whose name is not a
    version is left alone. Returns what was removed (F-018).

    Before a folder is deleted, the files a user added inside its managed folders are moved out to
    <root>/update-leftovers/<version>/ (#7, `_carry_user_files`). A folder whose files could not all be moved out is
    kept, whole, for the next update to try again: a prune never loses a file."""
    try:
        found = [(parse_version(p.name), p) for p in backup_root.iterdir()
                 if p.is_dir() and _is_version(p.name) and p.name != current]
    except OSError:
        return []
    keep_others = max(1, keep) - (1 if current is not None and (backup_root / current).is_dir() else 0)
    root = backup_root.parent
    live: set[str] | None = None
    removed: list[Path] = []
    for _, path in sorted(found, reverse=True)[keep_others:]:
        if live is None:
            live = _managed_files(root)
        if not _carry_user_files(path, root, live):
            continue
        try:
            shutil.rmtree(path)
            removed.append(path)
        except OSError:
            pass
    return removed


def _managed_files(root: Path) -> set[str]:
    """Relative posix paths of every file under the managed folders of `root` (an install or a backup), leaving out
    __pycache__ folders and *.pyc files (Python writes those, nobody adds them). One os.walk per folder: scandir,
    no stat per file."""
    found: set[str] = set()
    for name in MANAGED_DIRS:
        top = root / name
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            rel = Path(dirpath).relative_to(root).as_posix()
            found.update(f"{rel}/{f}" for f in filenames if not f.endswith(".pyc"))
    return found


def _carry_user_files(backup: Path, root: Path, live: set[str]) -> bool:
    """Move the user's files out of an old .update-backup/<version> folder before it is pruned (#7).

    A user file is one in the backup's managed folders (wowtools, vendor, scripts, docs) with no file at the same
    path in the live install (`live`) and not listed as installed by one of the backup's own vendored libraries
    (`_vendored_files`: every vendor/*.dist-info folder and the files its RECORD lists, so a library a later release
    bumped, renamed or trimmed leaves nothing behind). The app's own folders have no manifest, so a wowtools, scripts
    or docs file that version had and a later release dropped is carried too: harmless, and it is better to keep one
    file too many than to lose one. A file the user edited, or one whose path the live install also has, is not
    carried. Each one goes to <root>/update-leftovers/<version>/<same path> (never back into the
    managed folders: the next update would replace them, and a stray module there could be imported); a name already
    taken gets " (2)", " (3)"... Returns False, after logging update.backup_kept, when a move failed: the caller
    then keeps the folder."""
    leftovers = sorted(_managed_files(backup) - live - _vendored_files(backup))
    if not leftovers:
        return True
    dest_root = root / LEFTOVERS_DIR_NAME / backup.name
    moved: list[str] = []
    try:
        for rel in leftovers:
            dst = _free_path(dest_root / rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(backup / rel), str(dst))
            moved.append(dst.relative_to(dest_root).as_posix())
    except OSError as exc:
        if moved:
            log_event("update.leftovers_kept", version=backup.name, folder=str(dest_root), files=moved)
        log_event("update.backup_kept", version=backup.name, folder=str(backup), error=str(exc))
        return False
    log_event("update.leftovers_kept", version=backup.name, folder=str(dest_root), files=moved)
    return True


def _vendored_files(root: Path) -> set[str]:
    """Relative posix paths (vendor/...) of what the vendored libraries in `root` installed: each
    vendor/<pkg>-X.Y.Z.dist-info folder's own files, plus every path its RECORD lists (relative to vendor/; a path
    leading outside vendor/ is ignored). An unreadable RECORD adds only its folder's files."""
    vendor = root / "vendor"
    found: set[str] = set()
    try:
        infos = [e for e in os.scandir(vendor) if e.name.endswith(".dist-info") and e.is_dir()]
    except OSError:
        return found
    for info in infos:
        for dirpath, _dirnames, filenames in os.walk(info.path):
            rel = Path(dirpath).relative_to(root).as_posix()
            found.update(f"{rel}/{f}" for f in filenames)
        try:
            with open(os.path.join(info.path, "RECORD"), encoding="utf-8", newline="") as fh:
                rows = list(csv.reader(fh))
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
        for row in rows:
            if not row or not row[0]:
                continue
            path = posixpath.normpath(row[0].replace("\\", "/"))
            if path.startswith("../") or path == ".." or posixpath.isabs(path):
                continue
            found.add(f"vendor/{path}")
    return found


def _free_path(path: Path) -> Path:
    """`path`, or `name (2).ext`, `name (3).ext`... beside it when that name is taken."""
    candidate, n = path, 2
    while os.path.lexists(candidate):
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return candidate


def _is_version(text: str) -> bool:
    try:
        parse_version(text)
    except ValueError:
        return False
    return True


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def _remove_tree(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _rollback(root: Path, backup: Path, shipped: list[str]) -> None:
    saved = {p.name for p in backup.iterdir()}
    for name in set(_replaced_names(root, shipped)) | saved:
        try:
            _remove_tree(root / name)
        except OSError:
            pass
    for name in saved:
        _copy(backup / name, root / name)


def _apply_zip(root: Path, release: ReleaseInfo, current: str, download: Callable[[str, Path], None],
               allow_unverified: bool = False) -> None:
    swapped = False
    try:
        with tempfile.TemporaryDirectory(prefix="wowtools-update-", ignore_cleanup_errors=True) as tmp:
            _download_and_swap(root, release, current, download, allow_unverified, Path(tmp))
            swapped = True
    except KeyboardInterrupt:
        if not swapped:
            raise
        # Ctrl+C while the temp download was being removed: the new version is already in place.
        log_event("update.cleanup_stopped", step="temp", to=release.version)
        return
    try:
        removed = prune_update_backups(root / BACKUP_DIR_NAME, current=current)
    except KeyboardInterrupt:
        # The new version is in place; a stopped prune only leaves old backups for the next update to prune.
        log_event("update.cleanup_stopped", step="prune", to=release.version)
        return
    if removed:
        log_event("update.backups_pruned", keep=KEEP_UPDATE_BACKUPS, removed=[p.name for p in removed])


def _download_and_swap(root: Path, release: ReleaseInfo, current: str, download: Callable[[str, Path], None],
                       allow_unverified: bool, work: Path) -> None:
    """Download, verify and extract the release in `work`, back the install up, then swap the program files in,
    rolling back on any exception. Returns only once the new version is fully in place."""
    archive = work / "release.zip"
    _download_release(release, archive, download, allow_unverified)
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
        # A backup of this version from an earlier update (an older version was reinstalled since): save the
        # user's files from it first, as a prune does (#7). The live install is this same version, so its files
        # are the program files; a failed move stops the update before anything is changed.
        if not _carry_user_files(backup, root, _managed_files(root)):
            raise UpdateError(f"could not move your files out of the old backup {backup}; nothing was changed")
        shutil.rmtree(backup)
    backup.mkdir(parents=True)
    shipped = _shipped_names(staging)
    old_names = _replaced_names(root, shipped)
    try:
        for name in old_names:
            _copy(root / name, backup / name)
    except Exception as exc:  # any error (a bad file name too), before the live install is touched
        raise UpdateError(f"could not back up the current version: {exc}") from exc
    try:
        for name in old_names:
            _remove_tree(root / name)
        for name in shipped:
            _copy(staging / name, root / name)
    except BaseException as exc:  # roll back on anything (even Ctrl+C), then re-raise (F-005)
        try:
            _rollback(root, backup, shipped)
        except BaseException as rollback_exc:  # noqa: BLE001 - a second Ctrl+C too: say where the backup is
            raise RollbackFailed(f"update failed ({exc or type(exc).__name__}) and the rollback also failed "
                                 f"({rollback_exc or type(rollback_exc).__name__}). "
                                 f"Your previous version is saved in {backup}") from exc
        if not isinstance(exc, Exception):
            raise
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
        print(apply(release, allow_unverified=cfg.allow_unverified_updates), file=stdout)
    except (UpdateError, OSError) as exc:
        print(f"Update failed: {exc}", file=stderr)
        return 1
    except KeyboardInterrupt:
        print(UPDATE_STOPPED, file=stderr)
        return 130
    return 0
