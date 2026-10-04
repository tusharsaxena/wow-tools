"""Staged changes to AceDB databases, on a byte-free model (spec §7). UI-free.

Each database gets a DbState: the staged profileKeys mapping (None = entry removed), the staged profile table
(name -> Original(name in the file) or CopyOf(original name)) and the staged LibDualSpec spec values. Operations
only change these; compile_file() (Task 7) turns them into byte edits. Changes() is always the difference from the
file, so operations compose and discard() is just a reset.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.tools.ace_profiles.model import DEFAULT, AceDb
from wowtools.tools.ace_profiles.scanner import ScanResult, SvFile

MAX_NAME = 100
CREATED_AT_LOGIN = "will be created by the addon at its next login, with its defaults"


@dataclass(frozen=True)
class DbKey:
    path: Path
    sv_name: str


@dataclass(frozen=True)
class Original:
    name: str


@dataclass(frozen=True)
class CopyOf:
    name: str


Source = Original | CopyOf


def valid_name(name: str) -> str | None:
    if not name or not name.strip():
        return "A profile name can't be empty."
    if len(name) > MAX_NAME:
        return f"A profile name can be at most {MAX_NAME} characters."
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        return "A profile name can't contain tabs, new lines or other control characters."
    return None


@dataclass
class Changes:
    deleted: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    copied: list[tuple[str, str]] = field(default_factory=list)
    reassigned: list[tuple[str, str, str]] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    lds: list[tuple[str, int, str, str]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return (len(self.deleted) + len(self.renamed) + len(self.copied) + len(self.reassigned)
                + len(self.removed) + len(self.lds))

    def lines(self) -> list[str]:
        out = [f'delete profile "{n}"' for n in self.deleted]
        out += [f'rename profile "{a}" to "{b}"' for a, b in self.renamed]
        out += [f'copy profile "{a}" as "{b}"' for a, b in self.copied]
        out += [f'"{c}": "{a}" to "{b}"' for c, a, b in self.reassigned]
        out += [f'remove leftover character "{c}"' for c in self.removed]
        out += [f'"{c}" spec {i} (LibDualSpec): "{a}" to "{b}"' for c, i, a, b in self.lds]
        return out


@dataclass
class DbState:
    key: DbKey
    file: SvFile
    db: AceDb
    leftovers: frozenset[str]
    keys: dict[str, str | None]
    profiles: dict[str, Source]
    lds: dict[tuple[str, int], str]

    @classmethod
    def fresh(cls, file: SvFile, db: AceDb, leftovers: frozenset[str]) -> DbState:
        return cls(DbKey(file.path, db.sv_name), file, db, leftovers, dict(db.profile_keys),
                   {name: Original(name) for name in db.profiles},
                   {(c, i): f.value.value for c, entry in db.lds.items() for i, f in entry.specs.items()})

    def users(self, name: str) -> list[str]:
        return [c for c, p in self.keys.items() if p == name]

    def names(self) -> list[str]:
        referenced = sorted({p for p in self.keys.values() if p is not None and p not in self.profiles})
        return list(self.profiles) + referenced

    def exists(self, name: str) -> bool:
        return name in self.profiles

    def missing(self, name: str) -> bool:
        return name not in self.profiles and name in self.keys.values()

    def changes(self) -> Changes:
        out = Changes()
        placed = {src.name: name for name, src in self.profiles.items() if isinstance(src, Original)}
        for name in self.db.profiles:
            if name not in placed:
                out.deleted.append(name)
            elif placed[name] != name:
                out.renamed.append((name, placed[name]))
        out.copied = [(src.name, name) for name, src in self.profiles.items() if isinstance(src, CopyOf)]
        for char, old in self.db.profile_keys.items():
            new = self.keys.get(char)
            if new is None:
                out.removed.append(char)
            elif new != old:
                out.reassigned.append((char, old, new))
        for (char, spec), new in self.lds.items():
            old = self.db.lds[char].specs[spec].value.value
            if new != old:
                out.lds.append((char, spec, old, new))
        return out

    @property
    def changed(self) -> bool:
        return self.changes().count > 0

    def _move_users(self, old: str, new: str) -> None:
        for char, profile in self.keys.items():
            if profile == old:
                self.keys[char] = new
        for spot, profile in self.lds.items():
            if profile == old:
                self.lds[spot] = new


@dataclass
class OpResult:
    applied: list[DbKey] = field(default_factory=list)
    refused: list[tuple[DbKey, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.applied)


@dataclass
class Summary:
    deleted: int = 0
    renamed: int = 0
    copied: int = 0
    reassigned: int = 0
    removed: int = 0
    lds: int = 0
    files: int = 0

    @property
    def total(self) -> int:
        return self.deleted + self.renamed + self.copied + self.reassigned + self.removed + self.lds


class Staging:
    def __init__(self, states: dict[DbKey, DbState], locked: Callable[[str], bool] = lambda addon: False) -> None:
        self.states = states
        self.locked = locked

    @classmethod
    def from_scan(cls, scan: ScanResult, *, locked: Callable[[str], bool] = lambda addon: False) -> Staging:
        states: dict[DbKey, DbState] = {}
        for flavor in scan.flavors:
            for account in flavor.accounts:
                for addon_file in account.files:
                    for db in addon_file.dbs:
                        leftovers = frozenset(c for c in db.profile_keys if account.is_leftover(c))
                        state = DbState.fresh(addon_file.file, db, leftovers)
                        states[state.key] = state
        return cls(states, locked)

    def state(self, key: DbKey) -> DbState:
        return self.states[key]

    def _refuse_locked(self, key: DbKey, result: OpResult) -> bool:
        state = self.states[key]
        if self.locked(state.file.addon):
            result.refused.append((key, f"{state.file.addon} is blacklisted (press u to unlock it)"))
            return True
        return False

    def _each(self, keys: Iterable[DbKey], result: OpResult, apply: Callable[[DbState], str | None],
              operation: str) -> OpResult:
        for key in keys:
            if self._refuse_locked(key, result):
                continue
            problem = apply(self.states[key])
            if problem is None:
                result.applied.append(key)
            else:
                result.refused.append((key, problem))
        log_event("ace.staged", operation=operation, applied=len(result.applied), refused=len(result.refused))
        return result

    def delete(self, selection: dict[DbKey, list[str]], target: str) -> OpResult:
        result = OpResult()
        problem = valid_name(target)
        if problem is not None:
            result.refused = [(key, problem) for key in selection]
            return result

        def apply(state: DbState) -> str | None:
            names = [n for n in selection[state.key] if n in state.names()]
            if target in names:
                return f'"{target}" is being deleted itself; choose another profile for its characters'
            if not names:
                return "none of those profiles is in this database any more"
            for name in names:
                state.profiles.pop(name, None)
                state._move_users(name, target)
            if not state.exists(target) and state.users(target):
                result.notes.append(f'{state.file.addon}: "{target}" {CREATED_AT_LOGIN}.')
            return None
        return self._each(selection, result, apply, "delete")

    def assign(self, selection: dict[DbKey, list[str]], target: str) -> OpResult:
        result = OpResult()
        problem = valid_name(target)
        if problem is not None:
            result.refused = [(key, problem) for key in selection]
            return result

        def apply(state: DbState) -> str | None:
            chars = [c for c in selection[state.key] if state.keys.get(c) is not None]
            if not chars:
                return "none of those characters is in this database any more"
            for char in chars:
                state.keys[char] = target
            if not state.exists(target):
                result.notes.append(f'{state.file.addon}: "{target}" {CREATED_AT_LOGIN}.')
            if any(state.db.lds_enabled(c) for c in chars):
                result.notes.append(f"{state.file.addon}: LibDualSpec switches the profile by spec for some of "
                                    f"these characters; it will override this at login.")
            return None
        return self._each(selection, result, apply, "assign")

    def rename(self, key: DbKey, old: str, new: str) -> OpResult:
        result = OpResult()

        def apply(state: DbState) -> str | None:
            if old not in state.names():
                return f'"{old}" is not a profile of this database'
            problem = valid_name(new)
            if problem is not None:
                return problem
            if new in state.names():
                return f'"{new}" is already a profile of this database'
            if old in state.profiles:
                state.profiles = {(new if name == old else name): src for name, src in state.profiles.items()}
            state._move_users(old, new)
            return None
        return self._each([key], result, apply, "rename")

    def copy(self, key: DbKey, source: str, new: str) -> OpResult:
        result = OpResult()

        def apply(state: DbState) -> str | None:
            if source not in state.profiles:
                return f'"{source}" has no data in the file to copy'
            problem = valid_name(new)
            if problem is not None:
                return problem
            if new in state.names():
                return f'"{new}" is already a profile of this database'
            state.profiles[new] = CopyOf(state.profiles[source].name)
            return None
        return self._each([key], result, apply, "copy")

    def remove_leftovers(self, selection: dict[DbKey, list[str]]) -> OpResult:
        result = OpResult()

        def apply(state: DbState) -> str | None:
            chars = [c for c in selection[state.key] if c in state.leftovers and state.keys.get(c) is not None]
            skipped = [c for c in selection[state.key] if c not in state.leftovers]
            if skipped:
                result.notes.append(f"{state.file.addon}: {len(skipped)} character(s) have a folder in WTF and "
                                    f"were kept.")
            if not chars:
                return "no leftover characters selected here"
            for char in chars:
                state.keys[char] = None
            return None
        return self._each(selection, result, apply, "remove_leftovers")

    def keep_only_default(self, keys: list[DbKey]) -> OpResult:
        selection = {k: [n for n in self.states[k].names() if n != DEFAULT] for k in keys}
        selection = {k: names for k, names in selection.items() if names}
        return self.delete(selection, DEFAULT)

    def everyone_to_default(self, keys: list[DbKey]) -> OpResult:
        return self.assign({k: [c for c, p in self.states[k].keys.items() if p is not None] for k in keys},
                           DEFAULT)

    def discard(self) -> None:
        for key, state in self.states.items():
            self.states[key] = DbState.fresh(state.file, state.db, state.leftovers)

    def changed(self) -> list[DbState]:
        return [state for state in self.states.values() if state.changed]

    def summary(self) -> Summary:
        out = Summary()
        files = set()
        for state in self.states.values():
            changes = state.changes()
            if not changes.count:
                continue
            files.add(state.file.path)
            out.deleted += len(changes.deleted)
            out.renamed += len(changes.renamed)
            out.copied += len(changes.copied)
            out.reassigned += len(changes.reassigned)
            out.removed += len(changes.removed)
            out.lds += len(changes.lds)
        out.files = len(files)
        return out
