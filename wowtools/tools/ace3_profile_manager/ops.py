"""Staged changes to AceDB databases, on a byte-free model (spec §7). UI-free.

Each database gets a DbState: the staged profileKeys mapping (None = entry removed), the staged profile table
(name -> Original(name in the file) or CopyOf(original name)), the staged names of module-only profiles (a
namespaces[*].profiles entry with no main `profiles` entry: original name -> staged name, None = deleted) and the
staged LibDualSpec spec values. Operations
only change these; compile_file() turns them into byte edits. Changes() is always the difference from the
file, so operations compose and discard() is just a reset.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.core.luasv import Field, Table, encode_string, line_start, newline_of, splice
from wowtools.core.svfiles import SvFile
from wowtools.tools.ace3_profile_manager.model import DEFAULT, AceDb
from wowtools.tools.ace3_profile_manager.scanner import ScanResult

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
    module_only: dict[str, str | None] = field(default_factory=dict)

    @classmethod
    def fresh(cls, file: SvFile, db: AceDb, leftovers: frozenset[str]) -> DbState:
        module_only = {n: n for ns in db.namespaces.values() for n in ns.entries if n not in db.profiles}
        return cls(DbKey(file.path, db.sv_name), file, db, leftovers, dict(db.profile_keys),
                   {name: Original(name) for name in db.profiles},
                   {(c, i): f.value.value for c, entry in db.lds.items() for i, f in entry.specs.items()},
                   module_only)

    def users(self, name: str) -> list[str]:
        return [c for c, p in self.keys.items() if p == name]

    def names(self) -> list[str]:
        referenced = sorted({p for p in self.keys.values() if p is not None and p not in self.profiles})
        return list(self.profiles) + referenced

    def taken(self, name: str) -> bool:
        """name is a profile, a referenced profile or a module-only profile (a new name would collide)."""
        return name in self.names() or name in self.module_only.values()

    def module_profiles(self, ns_entries: Iterable[str]) -> dict[str, Source]:
        """The staged profile table of one namespace: the main table plus its module-only profiles."""
        staged = dict(self.profiles)
        for original in ns_entries:
            new = self.module_only.get(original)
            if new is not None:
                staged[new] = Original(original)
        return staged

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
        for name, new in self.module_only.items():
            if new is None:
                out.deleted.append(name)
            elif new != name:
                out.renamed.append((name, new))
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

    def _drop_module_only(self, name: str) -> None:
        for original, staged in self.module_only.items():
            if staged == name:
                self.module_only[original] = None

    def _rename_module_only(self, old: str, new: str) -> None:
        for original, staged in self.module_only.items():
            if staged == old:
                self.module_only[original] = new


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


Locked = Callable[[str, str], bool]  # (flavor folder, addon) -> blacklisted and not unlocked


def _never_locked(flavor: str, addon: str) -> bool:
    return False


class Staging:
    def __init__(self, states: dict[DbKey, DbState], locked: Locked = _never_locked) -> None:
        self.states = states
        self.locked = locked

    @classmethod
    def from_scan(cls, scan: ScanResult, *, locked: Locked = _never_locked) -> Staging:
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

    def _is_locked(self, state: DbState) -> bool:
        return self.locked(state.file.flavor.folder, state.file.addon)

    def _refuse_locked(self, key: DbKey, result: OpResult) -> bool:
        state = self.states[key]
        if self._is_locked(state):
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
                state._drop_module_only(name)
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
            if state.taken(new):
                return f'"{new}" is already a profile of this database'
            if old in state.profiles:
                state.profiles = {(new if name == old else name): src for name, src in state.profiles.items()}
            state._rename_module_only(old, new)
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
            if state.taken(new):
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

    def drop_locked(self) -> list[str]:
        """Reset the staged changes of every addon that is locked now (blacklisted after they were staged).
        Returns the addons whose changes were dropped."""
        dropped: list[str] = []
        for key, state in self.states.items():
            if state.changed and self._is_locked(state):
                self.states[key] = DbState.fresh(state.file, state.db, state.leftovers)
                if state.file.addon not in dropped:
                    dropped.append(state.file.addon)
        if dropped:
            log_event("ace.staged", operation="drop_locked", applied=0, refused=len(dropped))
        return dropped

    def _live(self) -> list[DbState]:
        """The states that may be written: a locked (blacklisted) addon never is, even with changes staged."""
        return [state for state in self.states.values() if not self._is_locked(state)]

    def changed(self) -> list[DbState]:
        return [state for state in self._live() if state.changed]

    def summary(self) -> Summary:
        out = Summary()
        files = set()
        for state in self._live():
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


@dataclass
class Expected:
    """What a database must read back as after the edit (verify.verify_edit)."""
    profile_keys: dict[str, str]
    profiles: dict[str, bytes]
    namespaces: dict[str, dict[str, bytes]]
    lds: dict[str, dict[int, str]]


@dataclass
class FileEdit:
    file: SvFile | None
    data: bytes
    changes: list[str]
    expected: dict[str, Expected]


def _table_edits(data: bytes, table: Table | None, entries: dict[str, Field], staged: dict[str, Source],
                 nl: bytes) -> tuple[list[tuple[int, int, bytes]], dict[str, bytes]]:
    """Edits that turn this profiles table into the staged one, and the expected {name: value bytes}."""
    if table is None:
        return [], {}
    edits: list[tuple[int, int, bytes]] = []
    placed = {src.name: name for name, src in staged.items() if isinstance(src, Original)}
    for original, item in entries.items():
        if original not in placed:
            edits.append((item.remove_span[0], item.remove_span[1], b""))
        elif placed[original] != original:
            edits.append((item.key_span[0], item.key_span[1], b"[" + encode_string(placed[original]) + b"]"))
    expected = {}
    for name, src in staged.items():
        item = entries.get(src.name)
        if item is not None:
            expected[name] = data[item.value.start:item.value.end]
    inserts = [b"[" + encode_string(name) + b"] = " + expected[name] + b"," + nl
               for name, src in staged.items() if isinstance(src, CopyOf) and name in expected]
    if inserts:
        kept = [item for name, item in entries.items() if name in placed]
        last = kept[-1] if kept else None
        if last is not None and data[last.entry_end - 1:last.entry_end] not in (b",", b";"):
            edits.append((last.value.end, last.value.end, b","))
        at = line_start(data, table.close)
        if data[at:table.close].strip(b" \t"):
            edits.append((table.close, table.close, nl + b"".join(inserts)))
        else:
            edits.append((at, at, b"".join(inserts)))
    return edits, expected


def compile_file(states: list[DbState], data: bytes) -> FileEdit:
    """Byte edits for every changed database of one file, applied in one splice."""
    nl = newline_of(data)
    edits: list[tuple[int, int, bytes]] = []
    changes: list[str] = []
    expected: dict[str, Expected] = {}
    file = states[0].file if states else None
    for state in states:
        db = state.db
        for char, item in db.key_fields.items():
            new = state.keys.get(char)
            if new is None:
                edits.append((item.remove_span[0], item.remove_span[1], b""))
            elif new != db.profile_keys[char]:
                edits.append((item.value.start, item.value.end, encode_string(new)))
        main_edits, main_expected = _table_edits(
            data, db.profiles_table, {n: e.field for n, e in db.profiles.items()}, state.profiles, nl)
        edits += main_edits
        namespaces = {}
        for ns in db.namespaces.values():
            ns_edits, namespaces[ns.name] = _table_edits(data, ns.table, ns.entries,
                                                         state.module_profiles(ns.entries), nl)
            edits += ns_edits
        lds: dict[str, dict[int, str]] = {}
        for (char, spec), new in state.lds.items():
            item = db.lds[char].specs[spec]
            if new != item.value.value:
                edits.append((item.value.start, item.value.end, encode_string(new)))
            lds.setdefault(char, {})[spec] = new
        expected[db.sv_name] = Expected({c: p for c, p in state.keys.items() if p is not None}, main_expected,
                                        namespaces, lds)
        changes += [f"{db.sv_name}: {line}" for line in state.changes().lines()]
    return FileEdit(file, splice(data, edits), changes, expected)
