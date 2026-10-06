"""Safety checks shared by tools that change or delete SavedVariables files.

UI-free. A guard that refuses any path outside <flavor>/WTF/Account or not directly inside a SavedVariables
folder; a lock probe (rename aside and straight back, which Windows refuses exactly when another program holds
the file open) and the refusal every tool gives before it changes a locked file (find_locked, locked_message); recovery of probe leftovers a crash left behind; and the list of SavedVariables folders in a scope.
"""
from __future__ import annotations

import os
import stat
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from wowtools.core.fsutil import rename_no_replace
from wowtools.core.install import Flavor

# The lock check renames each file to <name><LOCK_PROBE_SUFFIX> and straight back. A file still carrying this
# suffix was left by a crash during that check; recover_probe_leftovers() renames it back.
LOCK_PROBE_SUFFIX = ".wowtools-lockcheck"


class SvFileError(Exception):
    """A SavedVariables file may not be touched (outside the account folder), or could not be put back after a
    lock probe."""


class SvGuard:
    """Refuses any path outside <flavor>/WTF/Account or not directly inside a SavedVariables folder.

    Resolving a path is slow on some drives (about 13ms per file on a Windows drive under WSL), so the account
    folder is resolved once and each parent folder once. A file that is itself a link is resolved in full.
    """

    def __init__(self, flavor: Flavor) -> None:
        self.flavor = flavor
        self.root = flavor.account_dir.resolve()
        self.parents: dict[Path, Path] = {}

    def check(self, path: Path, info: os.stat_result | None) -> None:
        if info is not None and stat.S_ISLNK(info.st_mode):
            resolved = path.resolve()
        else:
            parent = self.parents.get(path.parent)
            if parent is None:
                parent = self.parents[path.parent] = path.parent.resolve()
            resolved = parent / path.name
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise SvFileError(f"Refusing to touch {path}: it is outside {self.flavor.account_dir}") from None
        if resolved.parent.name != "SavedVariables":
            raise SvFileError(f"Refusing to touch {path}: it is not inside a SavedVariables folder")


def lstat_or_none(path: Path) -> os.stat_result | None:
    """os.lstat(path), or None when it fails (gone, unreadable)."""
    try:
        return os.lstat(path)
    except OSError:
        return None


def probe_lock(path: Path) -> str | None:
    """Rename the file aside and straight back. Windows refuses the rename exactly when another process holds the
    file open without allowing deletion, so a failure here means a delete or replace would fail too. Returns the
    error, or None if the file is free (or is gone, which the caller's recheck reports). Raises SvFileError when
    the file cannot be put back (it is left at the aside name, never replacing a new file at its own name)."""
    aside = path.with_name(path.name + LOCK_PROBE_SUFFIX)
    try:
        rename_no_replace(path, aside)
    except (FileNotFoundError, FileExistsError):
        return None  # gone (the recheck reports it), or never overwrite anything; the write reports real problems
    except OSError as exc:
        return exc.strerror or str(exc)
    for attempt in range(5):
        try:
            rename_no_replace(aside, path)
            return None
        except OSError as exc:
            if attempt == 4 or isinstance(exc, FileExistsError):  # a new file at path: never replace it
                raise SvFileError(f"Could not put {path.name} back after a lock check ({exc}). It is at {aside}: "
                                  f"rename it back to {path.name}.") from exc
            time.sleep(0.1)
    return None


# Programs known to hold SavedVariables files open while WoW is closed: every lock refusal names them.
KNOWN_LOCKERS = "the Raider.IO client and WeakAuras Companion are known to do this"
LOCKED_LISTED = 10  # files a refusal lists by name; the rest are counted


def find_locked(files: Sequence[tuple[str, Path]], fail: Callable[[SvFileError], Exception],
                report: Callable[[str, int, int, str], None] | None = None) -> list[tuple[str, str]]:
    """probe_lock every (rel, path), in order: the (rel, error) of each locked one. report("lock_check", index,
    total, rel) follows each probe. A file the probe cannot put back raises fail(error), the tool's own error
    (which says what was not changed): nothing must go on then."""
    locked: list[tuple[str, str]] = []
    for index, (rel, path) in enumerate(files, 1):
        try:
            error = probe_lock(path)
        except SvFileError as exc:
            raise fail(exc) from exc
        if error is not None:
            locked.append((rel, error))
        if report is not None:
            report("lock_check", index, len(files), rel)
    return locked


def locked_message(locked: Iterable[tuple[str, str]], verb: str) -> str:
    """The refusal a tool raises when find_locked found files: how many, who is known to do it, "Close it and
    <verb> again", then the first LOCKED_LISTED files with their errors and how many more there are."""
    locked = list(locked)
    names = "\n".join(f"  {rel} ({error})" for rel, error in locked[:LOCKED_LISTED])
    more = f"\n  …and {len(locked) - LOCKED_LISTED} more" if len(locked) > LOCKED_LISTED else ""
    return (f"{len(locked)} files are locked by another program ({KNOWN_LOCKERS}). Close it and {verb} again.\n"
            f"{names}{more}")


def recover_probe_leftovers(folders: list[Path], on_recovered: Callable[[Path], None] | None = None) -> list[Path]:
    """Rename back every <name>.wowtools-lockcheck left in these SavedVariables folders by a crash during an
    earlier lock check, when <name> itself is absent (never overwriting). on_recovered(original) is called for
    each file put back. Returns the files put back; a leftover that cannot be renamed is left alone."""
    recovered: list[Path] = []
    for folder in folders:
        try:
            leftovers = sorted(p for p in folder.iterdir() if p.name.endswith(LOCK_PROBE_SUFFIX))
        except OSError:
            continue
        for leftover in leftovers:
            original = leftover.with_name(leftover.name[:-len(LOCK_PROBE_SUFFIX)])
            try:
                rename_no_replace(leftover, original)
            except OSError:
                continue  # the original exists again, or the rename failed: the scan keeps warning about it
            recovered.append(original)
            if on_recovered is not None:
                on_recovered(original)
    return recovered


def saved_variables_folders(flavor: Flavor, account: str | None = None) -> list[Path]:
    """Every SavedVariables folder a scan of this scope reads: each account's and each character's (one account,
    any case, when `account` is given). Unreadable folders are left out."""
    accounts = flavor.accounts()
    if account is not None:
        accounts = [a for a in accounts if a.name.casefold() == account.casefold()]
    folders: list[Path] = []
    for acct in accounts:
        folders.append(acct.saved_variables_dir)
        folders.extend(c.saved_variables_dir for c in acct.characters())
    return folders
