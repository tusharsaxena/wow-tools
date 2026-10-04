"""Scan a flavor's SavedVariables for AceDB databases (spec §6). UI-free.

Every account-wide and per-character SavedVariables/*.lua is read once. A file without the bytes "profileKeys" is
not parsed. Files are parsed with model.ace_descend, so only profile data is built. Blizzard_* files, *.lua.bak
(anything not ending in exactly ".lua") and SavedVariables folders under a symlink or junction are skipped.
"""
from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.core.fsutil import is_link
from wowtools.core.install import Account, Character, Flavor
from wowtools.tools.ace_profiles.luasv import LuaParseError, parse
from wowtools.tools.ace_profiles.model import AceDb, ace_descend, find_dbs, has_profile_keys

ScanProgress = Callable[[int, int, str], None]
PROTECTED_PREFIX = "blizzard_"
ACCOUNT_WIDE = "Account-wide"


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class SvFile:
    path: Path
    flavor: Flavor
    account: str
    character: Character | None
    size: int
    mtime: float
    sha256: str

    @property
    def addon(self) -> str:
        return self.path.name[:-4]

    @property
    def rel(self) -> str:
        return self.path.relative_to(self.flavor.path).as_posix()

    @property
    def owner(self) -> str:
        return ACCOUNT_WIDE if self.character is None else self.character.label


@dataclass
class AddonFile:
    file: SvFile
    dbs: list[AceDb]


@dataclass
class AccountScan:
    flavor: Flavor
    account: str
    characters: dict[str, str] = field(default_factory=dict)
    files: list[AddonFile] = field(default_factory=list)

    def is_leftover(self, char_key: str) -> bool:
        return char_key.casefold() not in self.characters


@dataclass(frozen=True)
class ScanWarning:
    path: Path | None
    message: str


@dataclass
class FlavorScan:
    flavor: Flavor
    accounts: list[AccountScan] = field(default_factory=list)
    warnings: list[ScanWarning] = field(default_factory=list)
    error: str | None = None

    def files(self) -> list[AddonFile]:
        return [f for account in self.accounts for f in account.files]


@dataclass
class ScanResult:
    flavors: list[FlavorScan]

    @property
    def warnings(self) -> list[ScanWarning]:
        return [w for f in self.flavors for w in f.warnings]


def candidate_files(sv_dir: Path) -> list[Path]:
    """Regular files directly in sv_dir whose name ends in exactly ".lua" and doesn't start with Blizzard_."""
    found = []
    with os.scandir(sv_dir) as entries:
        for entry in entries:
            name = entry.name
            if not name.endswith(".lua") or name.casefold().startswith(PROTECTED_PREFIX) or len(name) <= 4:
                continue
            if entry.is_file(follow_symlinks=False) and not is_link(entry):
                found.append(Path(entry.path))
    return sorted(found, key=lambda p: p.name.casefold())


def _under_link(sv_dir: Path, account_dir: Path) -> bool:
    current = sv_dir
    while True:
        if is_link(current):
            return True
        if current == account_dir or current.parent == current:
            return False
        current = current.parent


def scan_flavor(flavor: Flavor, *, account: str | None = None, progress: ScanProgress | None = None) -> FlavorScan:
    started = time.monotonic()
    result = FlavorScan(flavor)
    log_event("ace.scan_started", flavor=flavor.folder, account=account or "all")
    if not flavor.account_dir.is_dir():
        result.error = f"{flavor.display_name} has no WTF/Account folder"
        return result

    def on_error(path: Path, exc: OSError) -> None:
        result.warnings.append(ScanWarning(path, f"could not read {path.name}: {exc.strerror or exc}"))
        log_event("ace.file_unreadable", path=str(path), error=str(exc))

    accounts: list[Account] = flavor.accounts(on_error)
    if account is not None:
        accounts = [a for a in accounts if a.name.casefold() == account.casefold()]
    work: list[tuple[AccountScan, Character | None, Path]] = []
    for acct in accounts:
        scan = AccountScan(flavor, acct.name)
        result.accounts.append(scan)
        characters = acct.characters(on_error)
        for char in characters:
            key = f"{char.name} - {char.realm}"
            scan.characters[key.casefold()] = key
        for owner, sv_dir in [(None, acct.saved_variables_dir)] + [(c, c.saved_variables_dir) for c in characters]:
            if not sv_dir.is_dir():
                continue
            if _under_link(sv_dir, acct.path):
                result.warnings.append(ScanWarning(sv_dir, "skipped: this SavedVariables folder is under a link"))
                continue
            try:
                for path in candidate_files(sv_dir):
                    work.append((scan, owner, path))
            except OSError as exc:
                on_error(sv_dir, exc)
    for index, (scan, owner, path) in enumerate(work, 1):
        _read_one(result, scan, owner, path)
        if progress is not None:
            progress(index, len(work), path.name)
    if progress is not None and not work:
        progress(0, 0, "")
    dbs = [db for f in result.files() for db in f.dbs]
    log_event("ace.scan_completed", flavor=flavor.folder, files=len(result.files()), dbs=len(dbs),
              profiles=sum(len(db.profile_names()) for db in dbs),
              characters=sum(len(db.profile_keys) for db in dbs),
              leftovers=sum(1 for a in result.accounts for f in a.files for db in f.dbs
                            for c in db.profile_keys if a.is_leftover(c)),
              warnings=len(result.warnings), seconds=round(time.monotonic() - started, 2))
    return result


def _read_one(result: FlavorScan, scan: AccountScan, owner: Character | None, path: Path) -> None:
    try:
        data = path.read_bytes()
        info = path.stat()
    except OSError as exc:
        result.warnings.append(ScanWarning(path, f"could not read {path.name}: {exc.strerror or exc}"))
        log_event("ace.file_unreadable", path=str(path), error=str(exc))
        return
    if not has_profile_keys(data):
        return
    try:
        chunk = parse(data, ace_descend)
    except LuaParseError as exc:
        result.warnings.append(ScanWarning(path, f"{path.name} is not readable Lua ({exc}); it is left alone"))
        log_event("ace.parse_failed", path=str(path), offset=exc.offset, error=str(exc))
        return
    dbs, notes = find_dbs(chunk, data)
    for note in notes:
        log_event("ace.lookalike", path=str(path), note=note)
    if dbs:
        sv = SvFile(path, scan.flavor, scan.account, owner, len(data), info.st_mtime, sha256_of(data))
        scan.files.append(AddonFile(sv, dbs))


def scan_flavors(flavors: list[Flavor], *, account: str | None = None,
                 progress: Callable[[Flavor, int, int, str], None] | None = None) -> ScanResult:
    scans = []
    for flavor in flavors:
        report = None if progress is None else (lambda i, n, label, f=flavor: progress(f, i, n, label))
        scans.append(scan_flavor(flavor, account=account, progress=report))
    return ScanResult(scans)
