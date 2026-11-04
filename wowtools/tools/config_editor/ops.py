"""Staged CVar edits and the bytes they write (config tools spec CE4-CE6, CE8). UI-free; never writes a file.

ConfigStaged holds, per file, the CVars to set and the CVars to remove; a CVar is in at most one of the two. Names
match in any case, as the client reads them, and a CVar the file sets keeps the file's spelling. Staging folds as
the user works: setting a CVar back to the file's own value, or removing one the file doesn't set, leaves nothing
staged for it. Reset to default is remove (CE5): a missing SET line means the client default. Toggle flips a
boolean ("0"/"1") from its value as staged, or from its default when it is not set, and a toggle back to a default
the file doesn't set drops the change again.

build_changes splices each file with core.cvarfile.apply_cvar_changes, so every line not changed keeps its bytes and
its place, and added lines are appended with the file's own line ending (CE8).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.client_apply import ClientChange
from wowtools.core.cvarfile import apply_cvar_changes, parse_cvars
from wowtools.core.kb import CvarInfo, Recommendation
from wowtools.tools.config_editor.model import ConfigTarget, Row

__all__ = ["ADD_LIST_CAP", "BOOLEAN_VALUES", "ConfigStaged", "RecommendRow", "add_candidates",
           "applicable_recommendations", "build_changes", "effective_value", "is_boolean", "match_candidates", "rows",
           "same_value", "stage_remove", "stage_reset", "stage_set", "stage_toggle"]

BOOLEAN_VALUES = ("0", "1")
ADD_LIST_CAP = 200  # Add's list shows at most this many matches (CF6), then how many more there are
_EMPTY = parse_cvars(b"")


@dataclass
class ConfigStaged:
    """Pending changes per file path: CVars to set (name -> value) and CVars to remove (names)."""
    sets: dict[Path, dict[str, str]] = field(default_factory=dict)
    removes: dict[Path, set[str]] = field(default_factory=dict)

    def count(self) -> int:
        return sum(map(len, self.sets.values())) + sum(map(len, self.removes.values()))

    def clear(self) -> None:
        self.sets.clear()
        self.removes.clear()

    def touches(self, path: Path, name: str) -> bool:
        key = name.casefold()
        return any(n.casefold() == key for n in (*self.sets.get(path, {}), *self.removes.get(path, ())))

    def _prune(self, path: Path) -> None:
        if not self.sets.get(path):
            self.sets.pop(path, None)
        if not self.removes.get(path):
            self.removes.pop(path, None)

    def _drop(self, path: Path, name: str) -> None:
        key = name.casefold()
        for found in [n for n in self.sets.get(path, {}) if n.casefold() == key]:
            del self.sets[path][found]
        for found in [n for n in self.removes.get(path, ()) if n.casefold() == key]:
            self.removes[path].discard(found)


def _file_values(target: ConfigTarget) -> dict[str, tuple[str, str]]:
    """casefolded name -> (the file's first spelling, the value the client reads: the last line's)."""
    out: dict[str, tuple[str, str]] = {}
    for line in target.parsed.lines if target.parsed is not None else ():
        key = line.name.casefold()
        out[key] = (out[key][0] if key in out else line.name, line.value)
    return out


def _values(staged: ConfigStaged | None, target: ConfigTarget) -> dict[str, tuple[str, str | None, bool]]:
    """casefolded name -> (spelling, value as staged (None: not set), whether a staged change touches it)."""
    out: dict[str, tuple[str, str | None, bool]] = {k: (n, v, False) for k, (n, v) in _file_values(target).items()}
    if staged is not None:
        for name in staged.removes.get(target.path, ()):
            key = name.casefold()
            out[key] = (out[key][0] if key in out else name, None, True)
        for name, value in staged.sets.get(target.path, {}).items():
            key = name.casefold()
            out[key] = (out[key][0] if key in out else name, value, True)
    return out


def effective_value(staged: ConfigStaged | None, target: ConfigTarget, name: str) -> str | None:
    """The CVar's value in the target as staged so far; None when it is not set there."""
    found = _values(staged, target).get(name.casefold())
    return None if found is None else found[1]


def is_boolean(value: str | None) -> bool:
    return value in BOOLEAN_VALUES


def same_value(a: str, b: str) -> bool:
    """Whether two CVar values are the same setting: equal text, or the same number ("1.0" and "1")."""
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except ValueError:
        return False


def _check(target: ConfigTarget, name: str, value: str = "") -> None:
    if target.read_only:
        raise ValueError(f"{target.label} is read-only: {target.problem}")
    apply_cvar_changes(b"", _EMPTY, {name: value}, ())  # the file layout's own rules for a name and value, once


def stage_set(staged: ConfigStaged, target: ConfigTarget, name: str, value: str) -> None:
    """Stage `SET name "value"` in the target (an unknown CVar too, CE5). Raises ValueError for a read-only target,
    a name that can't be written (empty, a space or a quote) or a value with a line break."""
    _check(target, name, value)
    staged._drop(target.path, name)
    current = _file_values(target).get(name.casefold())
    if current is None or current[1] != value:
        staged.sets.setdefault(target.path, {})[name if current is None else current[0]] = value
    staged._prune(target.path)


def stage_remove(staged: ConfigStaged, target: ConfigTarget, name: str) -> None:
    """Stage the removal of every SET line of the CVar; a CVar the file doesn't set just loses its staged set."""
    _check(target, name)
    staged._drop(target.path, name)
    current = _file_values(target).get(name.casefold())
    if current is not None:
        staged.removes.setdefault(target.path, set()).add(current[0])
    staged._prune(target.path)


def stage_reset(staged: ConfigStaged, target: ConfigTarget, name: str) -> None:
    """Reset to default (CE5): remove the line, since a CVar the file doesn't set takes the client default."""
    stage_remove(staged, target, name)


def stage_toggle(staged: ConfigStaged, target: ConfigTarget, name: str, info: CvarInfo | None) -> str:
    """Flip a boolean CVar between "0" and "1" from its value as staged (its default when not set) and return the new
    value. Raises ValueError when that value is not "0" or "1", or the CVar is not set and has no known default."""
    current = effective_value(staged, target, name)
    if current is None:
        current = info.default if info is not None else None
    if not is_boolean(current):
        raise ValueError(f"{name} is not a boolean (its value is {current!r})")
    new = "1" if current == "0" else "0"
    if name.casefold() not in _file_values(target) and info is not None and info.default == new:
        stage_remove(staged, target, name)  # back to the default the file already gives it
    else:
        stage_set(staged, target, name, new)
    return new


def _changed(value: str | None, default: str | None) -> bool | None:
    if value is None:
        return False
    if default is None:
        return None
    return not same_value(value, default)


def _matches(search: str, name: str, info: CvarInfo | None) -> bool:
    if not search:
        return True
    texts = [name] if info is None else [name, info.help, info.description]
    return any(search in text.casefold() for text in texts)


def rows(target: ConfigTarget, cvars: Mapping[str, CvarInfo], *, show_all_known: bool, category: str | None,
         changed_only: bool, search: str, staged: ConfigStaged | None = None) -> list[Row]:
    """The CVar list of a target (CE4, CE6), sorted by name (case ignored): every CVar the file sets or a staged
    change touches and, with `show_all_known`, every CVar the KB knows for the file's level (scope) that it doesn't
    set. Filters: `category` (a CATEGORIES group, None for all), `changed_only` (set and known to differ from the
    default), `search` (in the name, Blizzard's help and our description, case ignored)."""
    index = {name.casefold(): info for name, info in cvars.items()}
    values = _values(staged, target)
    if show_all_known:
        for info in cvars.values():
            if info.scope == target.level:
                values.setdefault(info.name.casefold(), (info.name, None, False))
    needle = search.strip().casefold()
    out: list[Row] = []
    for key, (name, value, touched) in values.items():
        info = index.get(key)
        default = info.default if info is not None else None
        row = Row(name=name, value=value, default=default, changed=_changed(value, default), info=info,
                  scope_mismatch=info is not None and info.scope is not None and info.scope != target.level,
                  staged=touched)
        if category is not None and row.category != category:
            continue
        if changed_only and row.changed is not True:
            continue
        if _matches(needle, name, info):
            out.append(row)
    return sorted(out, key=lambda r: (r.name.casefold(), r.name))


def add_candidates(targets: Sequence[ConfigTarget], cvars: Mapping[str, Mapping[str, CvarInfo]],
                   staged: ConfigStaged | None = None) -> list[CvarInfo]:
    """Add's list (feedback spec CF6): every CVar the knowledge base of a target's flavor (`cvars`: flavor folder ->
    its CVars) knows for that target's level, as Show all known lists them, that none of the targets sets (as staged:
    a CVar staged to be added leaves the list, one staged to be removed comes back). Once per name (case ignored,
    the first target's flavor wins), sorted by name."""
    taken = {key for target in targets for key, (_, value, _) in _values(staged, target).items() if value is not None}
    found: dict[str, CvarInfo] = {}
    for target in targets:
        for info in cvars.get(target.flavor.folder, {}).values():
            key = info.name.casefold()
            if info.scope == target.level and key not in taken:
                found.setdefault(key, info)
    return sorted(found.values(), key=lambda i: (i.name.casefold(), i.name))


def match_candidates(candidates: Sequence[CvarInfo], typed: str,
                     cap: int = ADD_LIST_CAP) -> tuple[list[CvarInfo], int]:
    """The candidates whose name holds `typed` (case ignored; all for an empty text), those starting with it first,
    each part in the candidates' order: at most `cap` of them, and how many more matched."""
    needle = typed.strip().casefold()
    starts: list[CvarInfo] = []
    inside: list[CvarInfo] = []
    for info in candidates:
        name = info.name.casefold()
        if name.startswith(needle):
            starts.append(info)
        elif needle in name:
            inside.append(info)
    matched = starts + inside
    return matched[:cap], max(len(matched) - cap, 0)


def _lines(target: ConfigTarget, sets: Mapping[str, str], removes: set[str]) -> tuple[str, ...]:
    current = _file_values(target)
    out: list[str] = []
    for name, value in sets.items():
        old = current.get(name.casefold())
        out.append(f'{target.file_name}: added {name} "{value}"' if old is None
                   else f'{target.file_name}: {name} "{old[1]}" -> "{value}"')
    out += [f"{target.file_name}: removed {name}" for name in sorted(removes, key=str.casefold)]
    return tuple(out)


def build_changes(staged: ConfigStaged, targets: Sequence[ConfigTarget]) -> list[ClientChange]:
    """One ClientChange per target (in `targets` order) whose staged changes alter its bytes: the file spliced by
    apply_cvar_changes (CE8), the SHA-256 the scan read (None: the run creates the file) and one line per change.
    Raises ValueError for a staged file not in `targets`, or one that is read-only."""
    by_path = {target.path: target for target in targets}
    missing = [path for path in (*staged.sets, *staged.removes) if path not in by_path]
    if missing:
        raise ValueError(f"staged changes for a file that was not passed: {', '.join(map(str, missing))}")
    out: list[ClientChange] = []
    for target in targets:
        sets, removes = staged.sets.get(target.path, {}), staged.removes.get(target.path, set())
        if not sets and not removes:
            continue
        if target.read_only:
            raise ValueError(f"{target.label} is read-only: {target.problem}")
        data = target.data if target.data is not None else b""
        new = apply_cvar_changes(data, target.parsed if target.parsed is not None else _EMPTY, sets, removes)
        if new == data and (target.exists or not new):
            continue
        out.append(ClientChange(target.path, new, target.sha256, _lines(target, sets, removes)))
    return out


@dataclass(frozen=True)
class RecommendRow:
    """One recommendation as Recommend… lists it for a file: `current` is the CVar's value there as staged (None:
    not set), `done` whether that already is the recommended value, or, not set, the KB's default is (listed, never
    staged again)."""
    recommendation: Recommendation
    current: str | None
    done: bool


def applicable_recommendations(target: ConfigTarget, recommendations: Sequence[Recommendation],
                               cvars: Mapping[str, CvarInfo], staged: ConfigStaged | None = None) -> list[RecommendRow]:
    """The recommendations (already the target's flavor's, core.kb.load_recommendations) that belong in this file:
    every one whose CVar the KB keeps at the file's level, or whose scope the KB does not know (no data yet: the
    file is the user's call). In the given order."""
    index = {name.casefold(): info for name, info in cvars.items()}
    out: list[RecommendRow] = []
    for rec in recommendations:
        info = index.get(rec.cvar.casefold())
        if info is not None and info.scope is not None and info.scope != target.level:
            continue
        current = effective_value(staged, target, rec.cvar)
        in_force = current if current is not None else (info.default if info is not None else None)
        out.append(RecommendRow(rec, current, in_force is not None and same_value(in_force, rec.value)))
    return out
