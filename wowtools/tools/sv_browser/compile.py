"""Turn one file's plan (ops.FilePlan) into its edited bytes (spec D19). UI-free.

compile_file(file, plan, data) is the shared pipeline's compile callback (core/sv_apply.py): data is the file as
Apply read it, already checked against the SHA-256 the edits were made on, and every target is found again from its
path in those bytes (never from spans remembered earlier). The whole file must be readable Lua (D4: a fault in a
table no edit touches still refuses the file, as search does); it is then parsed only down the tables that hold an
edited key. Each edit becomes byte splices: a value's span replaced with luasv.encode_value (strings double-quoted
with Lua escapes; numbers as Python writes them), a key's span with luasv.encode_key (always bracket form), a deleted
key's whole entry taken out by its remove span (its line and `-- [n]` comment when it has the line to itself). Every
other byte stays as it was. A plan that does not fit the bytes (a key not there, or there twice, a rename that would
leave a key twice, an edit inside a deleted key) is not spliced: the edit carries its problems, which verify reports.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from wowtools.core.luasv import (Assignment, Chunk, Field, LuaParseError, Scalar, Table, encode_key, encode_value,
                                 iter_scalars, key_id, parse, splice)
from wowtools.core.svfiles import SvFile
from wowtools.tools.sv_browser.model import key_text, scalar_text
from wowtools.tools.sv_browser.ops import (ARRAY_RENAME, TOP_LEVEL, FieldEdit, FilePlan, TypedPath, new_duplicates,
                                           path_text, typed_path)

Span = tuple[int, int]
Splice = tuple[int, int, bytes]


@dataclass
class SvEdit:
    """One file's edit (core/sv_apply.Edit): the new bytes, one line per edited key, the plan, and each splice's
    span in the old bytes paired with the span that replaced it in the new (for verify's outside check). problems:
    why the plan could not be compiled (data is then the old bytes)."""
    file: SvFile
    data: bytes
    changes: list[str]
    plan: FilePlan
    spans: list[tuple[Span, Span]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def table_paths(paths: Iterable[Sequence]) -> set[TypedPath]:
    """The typed paths of every table holding an edited key, and of the tables above them."""
    out: set[TypedPath] = set()
    for path in paths:
        typed = typed_path(path)
        out.update(typed[:n] for n in range(1, len(typed)))
    return out


def descend_into(tables: set[TypedPath]) -> Callable[[tuple], bool]:
    """A parse descend() that builds only the given tables."""
    return lambda path: typed_path(path) in tables


class FieldIndex:
    """A chunk's assignments by name and each table's fields by typed key, built once per table on first use, so
    finding thousands of edits in one file is a dict lookup per key, not a scan of the table (never quadratic)."""

    def __init__(self, chunk: Chunk) -> None:
        self.tops: dict[str, list[Assignment]] = {}
        for item in chunk.assignments:
            self.tops.setdefault(item.name, []).append(item)
        self._tables: dict[int, tuple[Table, dict[tuple, list[Field]]]] = {}  # id -> (table kept alive, index)

    def fields(self, table: Table, key: tuple) -> list[Field]:
        known = self._tables.get(id(table))
        if known is None:
            index: dict[tuple, list[Field]] = {}
            for item in table.fields:
                index.setdefault(key_id(item.key), []).append(item)
            known = self._tables[id(table)] = (table, index)
        return known[1].get(key, [])


def locate(chunk: Chunk | FieldIndex, typed: TypedPath, path: Sequence,
           ) -> tuple[Assignment | Field | None, Table | None, str | None]:
    """The assignment or field at typed (path: the same keys, for messages), its table (None at the top level), or
    why it can't be found: (target, table, problem). Pass a FieldIndex of the chunk to look up many paths."""
    index = chunk if isinstance(chunk, FieldIndex) else FieldIndex(chunk)
    tops = index.tops.get(typed[0][1], [])
    if len(tops) != 1:
        return None, None, f"{path_text(path[:1])} is {'not in the file' if not tops else 'in the file twice'}"
    target: Assignment | Field = tops[0]
    table = None
    for depth in range(1, len(typed)):
        table = target.value
        if not isinstance(table, Table):
            return None, None, f"{path_text(path[:depth])} is not a table"
        found = index.fields(table, typed[depth])
        if len(found) != 1:
            where = "not in the file" if not found else "in the file twice"
            return None, None, f"{path_text(path[:depth + 1])} is {where}"
        target = found[0]
    return target, table, None


def _value_text(data: bytes, scalar: Scalar) -> str:
    return scalar_text(scalar.value, data[scalar.start:scalar.end])


def _new_text(value: object) -> str:
    return scalar_text(value, encode_value(value))


def _splices(data: bytes, target: Assignment | Field, item: FieldEdit, label: str) -> tuple[list[Splice], str]:
    """The splices and the change line for one edit. Raises ValueError with the problem."""
    if isinstance(target, Assignment):
        if item.rename or item.delete:
            raise ValueError(f"{label}: {TOP_LEVEL}")
    elif item.delete:
        start, end = target.remove_span
        shift = " (later entries move down)" if target.key_span is None else ""
        return [(start, end, b"")], f"{label}: deleted{shift}"
    out: list[Splice] = []
    parts = []
    if item.rename:
        if target.key_span is None:
            raise ValueError(f"{label}: {ARRAY_RENAME}")
        out.append((*target.key_span, encode_key(item.new_key)))
        parts.append(f"renamed to {key_text(item.new_key)}")
    if item.set_value:
        if not isinstance(target.value, Scalar):
            raise ValueError(f"{label} is a table: only a value that is not a table can be edited")
        out.append((target.value.start, target.value.end, encode_value(item.value)))
        parts.append(f"{_value_text(data, target.value)} → {_new_text(item.value)}")
    return out, f"{label}: {', '.join(parts)}"


def _duplicates(tables: dict[TypedPath, tuple[Table, Sequence, dict]]) -> list[str]:
    problems = []
    for table, path, edits in tables.values():
        for key in new_duplicates(table.fields, edits):
            problems.append(f"{path_text(path)} would hold the key {key_text(key[1])} twice")
    return problems


def compile_file(file: SvFile, plan: FilePlan, data: bytes) -> SvEdit:
    """The edit of one file: plan's edits spliced into data (the bytes Apply read), or the problems."""
    edit = SvEdit(file, data, [], plan)
    try:
        deque(iter_scalars(data), maxlen=0)  # the whole file must be readable Lua (D4), not just the edited tables
        chunk = parse(data, descend_into(table_paths(item.path for item in plan.edits)))
    except LuaParseError as exc:
        edit.problems.append(f"{file.path.name} is not readable Lua ({exc})")
        return edit
    index = FieldIndex(chunk)
    deleted = {item.typed for item in plan.edits if item.delete}
    splices: list[Splice] = []
    lines: list[tuple[int, str]] = []
    tables: dict[TypedPath, tuple[Table, Sequence, dict]] = {}
    for item in plan.edits:
        typed, label = item.typed, path_text(item.path)
        if any(typed[:n] in deleted for n in range(1, len(typed))):
            edit.problems.append(f"{label} is inside a deleted key")
            continue
        target, table, problem = locate(index, typed, item.path)
        if problem:
            edit.problems.append(problem)
            continue
        try:
            found, line = _splices(data, target, item, label)
        except ValueError as exc:
            edit.problems.append(str(exc))
            continue
        splices += found
        lines.append((min(s[0] for s in found), line))
        if table is not None and (item.rename or item.delete):
            tables.setdefault(typed[:-1], (table, item.path[:-1], {}))[2][typed[-1]] = item
    edit.problems += _duplicates(tables)
    if edit.problems:
        return edit
    try:
        edit.data = splice(data, splices)
    except ValueError as exc:
        edit.problems.append(f"the edits overlap ({exc})")
        return edit
    edit.changes = [line for _, line in sorted(lines)]
    shift = 0
    for start, end, new in sorted(splices, key=lambda s: (s[0], s[1])):
        edit.spans.append(((start, end), (start + shift, start + shift + len(new))))
        shift += len(new) - (end - start)
    return edit
