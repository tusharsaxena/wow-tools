"""Find installed and enabled addons and group every SavedVariables file by addon."""
from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.core.fsutil import is_link
from wowtools.core.install import ACCOUNT_WIDE, Account, Character, Flavor
from wowtools.core.svfiles import LOCK_PROBE_SUFFIX

PROTECTED_PREFIXES = ("blizzard_",)
_LUA = re.compile(r"\.lua", re.IGNORECASE)
# LOCK_PROBE_SUFFIX (core.svfiles): the cleaner's lock check renames each selected file to <name><suffix> and
# straight back. A file still carrying it was left by a crash between the two renames: never an addon file to
# propose, and the next real clean renames it back (cleaner.recover_probe_leftovers).


ScanProgress = Callable[[int, int, str], None]
"""Called as (current, total, label); total is the number of SavedVariables folders to read."""


class ScanError(Exception):
    """The flavor cannot be scanned safely. `short` is the reason in a few words, for a review tree's flavor line
    (the whole message, with its path, goes to the log)."""

    def __init__(self, message: str, short: str = "") -> None:
        super().__init__(message)
        self.short = short or message


@dataclass(frozen=True)
class ScanWarning:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True)
class SVFile:
    path: Path
    size: int
    mtime: float
    canonical: bool

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class SVGroup:
    account: str
    character: Character | None
    addon: str
    files: list[SVFile] = field(default_factory=list)

    @property
    def scope(self) -> str:
        return "character" if self.character else "account"

    @property
    def owner_label(self) -> str:
        return self.character.label if self.character else ACCOUNT_WIDE

    @property
    def key(self) -> str:
        return f"{self.account}|{self.owner_label}|{self.addon.casefold()}"

    @property
    def newest_mtime(self) -> float:
        return max(f.mtime for f in self.files)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)


@dataclass
class ScanResult:
    flavor: Flavor
    installed: dict[str, str]
    enabled: set[str]
    groups: list[SVGroup]
    accounts: int
    characters: int
    warnings: list[ScanWarning]
    account: str | None = None
    account_names: tuple[str, ...] = ()  # every account scanned, including ones with nothing to clean

    @property
    def sv_files(self) -> int:
        return sum(len(g.files) for g in self.groups)


def addon_name_for(filename: str) -> str | None:
    """Everything before the first '.lua' (any case); None if there is no addon name."""
    match = _LUA.search(filename)
    if not match or match.start() == 0:
        return None
    return filename[:match.start()]


def is_canonical(filename: str, addon: str) -> bool:
    """True for the only two names WoW itself writes: <Addon>.lua and <Addon>.lua.bak."""
    return filename.casefold() in {f"{addon}.lua".casefold(), f"{addon}.lua.bak".casefold()}


def installed_addons(addons_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        entries = list(addons_dir.iterdir())
    except OSError:
        return result
    for folder in entries:
        try:
            if folder.is_dir() and any(p.suffix.lower() == ".toc" for p in folder.iterdir()):
                result[folder.name.casefold()] = folder.name
        except OSError:
            continue
    return result


def parse_addons_txt(path: Path, warnings: list[ScanWarning] | None = None) -> dict[str, bool]:
    """Parse 'Name: enabled|disabled' lines. Keys are casefolded addon names."""
    text = path.read_bytes().decode("utf-8", errors="replace")
    states: dict[str, bool] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        name, sep, state = line.rpartition(":")
        state = state.strip().lower()
        if not sep or not name.strip() or state not in ("enabled", "disabled"):
            if warnings is not None:
                warnings.append(ScanWarning(str(path), f"line {lineno} not understood: {raw!r}"))
            continue
        states[name.strip().casefold()] = state == "enabled"
    return states


def enabled_addons(characters: Iterable[Character], installed: dict[str, str],
                   warnings: list[ScanWarning], *, scope: str = "") -> set[str]:
    """Global union: enabled on any character. Unlisted or no AddOns.txt means WoW's default (on).
    With no characters at all there is no evidence either way, so every installed addon counts as
    enabled (and a warning naming `scope` says the "not enabled" rule was not applied)."""
    characters = list(characters)
    if not characters:
        warnings.append(ScanWarning(scope or "WTF/Account",
                                    "no character folders: the 'not enabled' rule is not applied"))
        return set(installed)
    enabled: set[str] = set()
    for character in characters:
        if not character.addons_txt.is_file():
            enabled.update(installed)
            continue
        try:
            states = parse_addons_txt(character.addons_txt, warnings)
        except OSError as exc:
            warnings.append(ScanWarning(str(character.addons_txt), f"cannot read: {exc}"))
            enabled.update(installed)
            continue
        enabled.update(name for name, on in states.items() if on)
        enabled.update(name for name in installed if name not in states)
    return enabled


def _linked_folder(sv_dir: Path, account: Account, cache: dict[Path, bool]) -> Path | None:
    """The first folder from WTF/Account down to sv_dir that is a link (symlink or junction), or None. The WTF
    backup taken before a clean never goes into a link, so files under one could not be put back. cache: one
    lstat per folder per scan (an account's folders are shared by its characters)."""
    folder = account.path.parent
    for name in (account.path.name, *sv_dir.relative_to(account.path).parts, None):
        if folder not in cache:
            cache[folder] = is_link(folder)
        if cache[folder]:
            return folder
        if name is not None:
            folder = folder / name
    return None


def _scan_sv_dir(sv_dir: Path, account: Account, character: Character | None,
                 warnings: list[ScanWarning], links: dict[Path, bool] | None = None) -> list[SVGroup]:
    if not sv_dir.is_dir():
        return []
    linked = _linked_folder(sv_dir, account, {} if links is None else links)
    if linked is not None:
        warnings.append(ScanWarning(str(sv_dir), f"skipped: {linked} is a link, and the WTF backup does not follow "
                                                 "links, so nothing under it is cleaned"))
        return []
    try:
        entries = sorted(sv_dir.iterdir(), key=lambda p: p.name.casefold())
    except OSError as exc:
        warnings.append(ScanWarning(str(sv_dir), f"cannot read folder: {exc}"))
        return []
    groups: dict[str, SVGroup] = {}
    for path in entries:
        if path.name.endswith(LOCK_PROBE_SUFFIX):
            original = path.name[:-len(LOCK_PROBE_SUFFIX)]
            if (sv_dir / original).exists():
                note = f"{original} exists too, so this copy is left alone; delete it if you don't need it"
            else:
                note = f"the next clean renames it back to {original}, or rename it yourself"
            warnings.append(ScanWarning(str(path), f"left over from an interrupted lock check: {note}"))
            continue
        addon = addon_name_for(path.name)
        if addon is None or addon.casefold().startswith(PROTECTED_PREFIXES):
            continue
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError as exc:
            warnings.append(ScanWarning(str(path), f"cannot read file: {exc}"))
            continue
        group = groups.setdefault(addon.casefold(), SVGroup(account.name, character, addon))
        group.files.append(SVFile(path, stat.st_size, stat.st_mtime, is_canonical(path.name, addon)))
    return list(groups.values())


def _report(progress: ScanProgress | None, current: int, total: int, label: str) -> None:
    """Call the progress callback; a callback that raises must never break the scan."""
    if progress is None:
        return
    try:
        progress(current, total, label)
    except Exception:  # noqa: BLE001, S110 - progress is cosmetic
        pass


def scan(flavor: Flavor, *, account: str | None = None, progress: ScanProgress | None = None) -> ScanResult:
    """Scan one flavor. With `account`, only that account (any case) is scanned and "enabled" comes
    from its characters alone. `progress(current, total, label)` is called with (0, total, ...) before
    the SavedVariables folders are read and once after each folder; errors it raises are ignored."""
    started = time.monotonic()
    log_event("scan.started", flavor=flavor.folder, wow_path=str(flavor.path.parent), account=account)
    installed = installed_addons(flavor.addons_dir)
    if not installed:
        raise ScanError(f"No addons found in {flavor.addons_dir}. Refusing to scan: every "
                        "SavedVariables file would look uninstalled.",
                        short="no addons installed")
    warnings: list[ScanWarning] = []

    def on_error(path: Path, exc: OSError) -> None:
        warnings.append(ScanWarning(str(path), f"cannot read folder: {exc}"))

    accounts = flavor.accounts(on_error)
    if account is not None:
        wanted = [a for a in accounts if a.name.casefold() == account.casefold()]
        if not wanted:
            available = ", ".join(sorted((a.name for a in accounts), key=str.casefold)) or "none"
            raise ScanError(f"Unknown account {account!r} in {flavor.display_name}; available: {available}")
        accounts = wanted[:1]
        account = accounts[0].name
    characters = [c for acct in accounts for c in acct.characters(on_error)]
    scope = str(accounts[0].path) if account is not None else str(flavor.account_dir)
    enabled = enabled_addons(characters, installed, warnings, scope=scope)
    log_event("scan.addons", installed=sorted(installed.values(), key=str.casefold), enabled=sorted(enabled))

    total = len(accounts) + len(characters)
    done = 0
    _report(progress, done, total, "Reading AddOns")
    groups: list[SVGroup] = []
    links: dict[Path, bool] = {}
    for acct in accounts:
        groups += _scan_sv_dir(acct.saved_variables_dir, acct, None, warnings, links)
        done += 1
        _report(progress, done, total, acct.name)
        for character in (c for c in characters if c.account == acct.name):
            groups += _scan_sv_dir(character.saved_variables_dir, acct, character, warnings, links)
            done += 1
            _report(progress, done, total, f"{acct.name} · {character.label}")

    for warning in warnings:
        log_event("scan.warning", path=warning.path, message=warning.message)
    result = ScanResult(flavor, installed, enabled, groups, len(accounts), len(characters), warnings, account,
                        tuple(a.name for a in accounts))
    log_event("scan.completed", flavor=flavor.folder, account=account, installed=len(installed),
              enabled=len(enabled), accounts=len(accounts), characters=len(characters),
              sv_files=result.sv_files, groups=len(groups), duration_s=round(time.monotonic() - started, 3))
    return result
