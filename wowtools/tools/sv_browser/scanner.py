"""List the SavedVariables files of one flavor or several (spec D3, D4, D18). UI-free.

Every `*.lua` directly in a SavedVariables folder, account-wide and per character, every account, including
Blizzard_* (core.svfiles.walk_sv_files with is_sv_file: never .lua.bak/.old, never a link, never a folder under a
link). Files are only listed with their size and mtime: nothing is read or parsed here (the model reads a file when it
is opened, the search when it searches it), so SvFile.sha256 is "" until then. Lock-probe leftovers a crash left
behind (<name>.wowtools-lockcheck) are renamed back first, so the file shows again.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.core.install import Account, Character, Flavor
from wowtools.core.svfiles import (OWNER_ACCOUNT_WIDE, SvFile, SvScanWarning, is_sv_file, lstat_or_none,
                                   recover_probe_leftovers, under_link, walk_sv_files)
from wowtools.tools.sv_browser.events import SV_TOOL

ScanProgress = Callable[[Flavor, int, int, str], None]


@dataclass
class OwnerFiles:
    """One SavedVariables folder: the account's own (character None) or a character's."""
    character: Character | None
    files: list[SvFile] = field(default_factory=list)

    @property
    def label(self) -> str:
        return OWNER_ACCOUNT_WIDE if self.character is None else self.character.label


@dataclass
class AccountFiles:
    name: str
    owners: list[OwnerFiles] = field(default_factory=list)  # account-wide first, then characters; only with files

    def files(self) -> list[SvFile]:
        return [f for owner in self.owners for f in owner.files]


@dataclass
class FlavorFiles:
    flavor: Flavor
    accounts: list[AccountFiles] = field(default_factory=list)
    warnings: list[SvScanWarning] = field(default_factory=list)
    error: str | None = None

    def files(self) -> list[SvFile]:
        return [f for account in self.accounts for f in account.files()]


@dataclass
class ScanResult:
    flavors: list[FlavorFiles]

    def files(self) -> list[SvFile]:
        return [f for flavor in self.flavors for f in flavor.files()]

    @property
    def warnings(self) -> list[SvScanWarning]:
        return [w for f in self.flavors for w in f.warnings]


def _probe_folders(flavor: Flavor) -> list[Path]:
    """Every SavedVariables folder of the flavor that is not under a link (a leftover there is never touched)."""
    folders = []
    for acct in flavor.accounts():
        candidates = [acct.saved_variables_dir] + [c.saved_variables_dir for c in acct.characters()]
        folders += [d for d in candidates if d.is_dir() and not under_link(d, acct.path)]
    return folders


def scan_flavor(flavor: Flavor) -> FlavorFiles:
    result = FlavorFiles(flavor)
    if not flavor.account_dir.is_dir():
        result.error = f"{flavor.display_name} has no WTF/Account folder"
        return result
    recover_probe_leftovers(_probe_folders(flavor), on_recovered=lambda p: log_event(
        SV_TOOL.event("probe_recovered"), flavor=flavor.folder, path=p.relative_to(flavor.path).as_posix()))

    def unreadable(path: Path, exc: OSError) -> None:
        result.warnings.append(SvScanWarning(path, f"could not read {path.name}: {exc.strerror or exc}"))
        log_event("svb.file_unreadable", flavor=flavor.folder, path=str(path), error=str(exc))

    def on_link(sv_dir: Path) -> None:
        result.warnings.append(SvScanWarning(sv_dir, "skipped: this SavedVariables folder is under a link"))

    accounts: dict[str, AccountFiles] = {}

    def on_account(acct: Account, characters: list[Character]) -> None:
        accounts[acct.name] = AccountFiles(acct.name)
        result.accounts.append(accounts[acct.name])

    for acct, owner, path in walk_sv_files(flavor, accept=is_sv_file, on_error=unreadable, on_account=on_account,
                                           on_link=on_link):
        info = lstat_or_none(path)
        if info is None:
            unreadable(path, OSError(f"{path.name} is gone"))
            continue
        owners = accounts[acct.name].owners
        if not owners or owners[-1].character != owner:
            owners.append(OwnerFiles(owner))
        owners[-1].files.append(SvFile(path, flavor, acct.name, owner, info.st_size, info.st_mtime, ""))
    return result


def scan_flavors(flavors: list[Flavor], *, progress: ScanProgress | None = None) -> ScanResult:
    """List the files of each flavor (one, or every one for All flavors). progress(flavor, index, total, label)
    follows each flavor."""
    started = time.monotonic()
    scans = []
    for index, flavor in enumerate(flavors, 1):
        scans.append(scan_flavor(flavor))
        if progress is not None:
            progress(flavor, index, len(flavors), flavor.display_name)
    result = ScanResult(scans)
    files = result.files()
    log_event("svb.scan_completed", flavors=len(scans), accounts=sum(len(s.accounts) for s in scans),
              files=len(files), bytes=sum(f.size for f in files), warnings=len(result.warnings),
              seconds=round(time.monotonic() - started, 2))
    return result

