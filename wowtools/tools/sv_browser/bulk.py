"""Bulk Edit value / Rename key on the search results (spec D39). UI-free.

The review's Edit value and Rename key act, in the Results view, on every ticked hit (else the highlighted one). OK
stages one edit per hit into the review's Staging (ops.Staging.stage_hit_value / stage_hit_rename), the same staging
Browse edits go to, so Apply writes them with the rest. A hit that can't take the edit is left out and counted by its
reason (BulkResult): already staged, under a staged delete, from other bytes, or a D5 refusal (a top-level or array
entry rename, a key its table would hold twice). A value equal to the one there stages nothing (D29).

Edit value sets one typed value on every hit, or, after a value Contains search, may replace only the matched text
(MATCHED: search.replace_matched, every occurrence, the search's Match case). A rename needs each key's table for the
duplicate check: read_tables() reads each file once (in the review's worker), checks its bytes are the ones the
search read, and parses only the tables that hold a hit (compile.locate).
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.core.luasv import LuaParseError, Table, parse
from wowtools.core.svfiles import sha256_of
from wowtools.core.text import plural
from wowtools.tools.sv_browser.compile import FieldIndex, descend_into, locate, table_paths
from wowtools.tools.sv_browser.ops import FILE_CHANGED, OpResult, Staging, TypedPath
from wowtools.tools.sv_browser.search import Hit, Replacement, SearchSpec, replace_matched

MATCHED, WHOLE = "matched", "whole"  # Edit value after a value Contains search: the matched text, or the whole value
MODES = ((MATCHED, "Replace only the matched text"), (WHOLE, "Whole value"))
TableKey = tuple[Path, TypedPath]  # a file and the typed path of a table in it
Progress = Callable[[int, int, str], None]


@dataclass
class BulkResult:
    """What a bulk edit staged: how many edits, how many hits already held the value (or key), and the hits left
    out per reason."""
    operation: str  # "set" or "rename"
    staged: int = 0
    unchanged: int = 0
    left_out: Counter = field(default_factory=Counter)

    @property
    def left(self) -> int:
        return sum(self.left_out.values())

    def add(self, result: OpResult) -> None:
        if not result.ok:
            self.left_out[result.message] += 1
        elif result.message == "unchanged":
            self.unchanged += 1
        else:
            self.staged += 1

    def text(self) -> str:
        """The notice after a bulk edit: what was staged, then how many were left out and why."""
        lines = [f"Staged {plural(self.staged, 'edit')}."]
        if self.unchanged:
            lines.append(f"{plural(self.unchanged, 'result')} already had it (nothing to change).")
        if self.left_out:
            lines.append(f"{plural(self.left, 'result')} left out:")
            lines += [f"{n} · {reason}" for reason, n in self.left_out.most_common()]
        return "\n".join(lines)

    def log(self) -> None:
        log_event("svb.bulk_staged", operation=self.operation, staged=self.staged, unchanged=self.unchanged,
                  left_out=self.left, reasons=dict(self.left_out))


def new_value(spec: SearchSpec | None, mode: str, value: Replacement, hit: Hit) -> Replacement:
    """The value a bulk Edit value sets on hit: value itself, or (MATCHED, a value Contains search) the hit's string
    with every match of the search replaced by value."""
    if mode == MATCHED and spec is not None and spec.contains_value and isinstance(hit.old, str) \
            and isinstance(value, str):
        return replace_matched(spec, hit.old, value)
    return value


def stage_values(staging: Staging, hits: Iterable[Hit], value_for: Callable[[Hit], Replacement],
                 shas: Mapping[Path, str] = {}) -> BulkResult:
    """Stage value_for(hit) on every hit. shas: the SHA-256 of each file the review has loaded."""
    result = BulkResult("set")
    for hit in hits:
        result.add(staging.stage_hit_value(hit, value_for(hit), shas.get(hit.file.path)))
    result.log()
    return result


def stage_renames(staging: Staging, hits: Iterable[Hit], new_key: object, tables: Mapping[TableKey, Table | str],
                  shas: Mapping[Path, str] = {}) -> BulkResult:
    """Stage a rename to new_key on every hit; tables: read_tables(hits) (a str is why that table can't be read)."""
    result = BulkResult("rename")
    for hit in hits:
        table = tables.get(table_key(hit)) if len(hit.path) > 1 else None
        if isinstance(table, str):
            result.add(OpResult(False, table))
            continue
        result.add(staging.stage_hit_rename(hit, new_key, table, shas.get(hit.file.path)))
    result.log()
    return result


def table_key(hit: Hit) -> TableKey:
    """The file and typed path of the table holding the hit's key."""
    return hit.file.path, hit.typed_path[:-1]


def read_tables(hits: Sequence[Hit], progress: Progress | None = None) -> dict[TableKey, Table | str]:
    """The table holding each hit's key below the top level, as the bytes the search read have it: each file read
    once and parsed only down those tables. A file whose bytes changed since, or that can't be read, gives every one
    of its tables the reason (a str). progress(done, total, file name) follows each file."""
    by_file: dict[Path, list[Hit]] = {}
    for hit in hits:
        if len(hit.path) > 1:
            by_file.setdefault(hit.file.path, []).append(hit)
    out: dict[TableKey, Table | str] = {}
    for done, (path, file_hits) in enumerate(by_file.items(), 1):
        out.update(_file_tables(path, file_hits))
        if progress is not None:
            progress(done, len(by_file), path.name)
    return out


def _file_tables(path: Path, hits: list[Hit]) -> dict[TableKey, Table | str]:
    keys = {table_key(h): h.path[:-1] for h in hits}
    try:
        data = path.read_bytes()
    except OSError as exc:
        return dict.fromkeys(keys, f"Could not read {path.name}: {exc.strerror or exc}.")
    if sha256_of(data) != hits[0].sha256:
        return dict.fromkeys(keys, FILE_CHANGED)
    try:
        index = FieldIndex(parse(data, descend_into(table_paths(h.path for h in hits))))
    except LuaParseError as exc:
        return dict.fromkeys(keys, f"{path.name} is not readable Lua ({exc}).")
    out: dict[TableKey, Table | str] = {}
    for key, parent in keys.items():
        target, _, problem = locate(index, key[1], parent)
        value = getattr(target, "value", None)
        out[key] = value if isinstance(value, Table) else f"{problem or 'Its table is not in the file'}."
    return out
