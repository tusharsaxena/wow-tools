"""Check an edited SavedVariables file says exactly what was planned before it is written (spec D19). UI-free.

verify_edit(edit, old) is the shared pipeline's verify callback (core/sv_apply.py): it re-parses the new bytes (only
down the tables that hold an edited key, found by their new keys: a renamed table or an array entry moved down by a
delete is looked up where it is now) and checks, with the core helpers (core/sv_verify.py), that the file holds the
same assignments in the same order with the same text between them and that no assignment without an edit changed;
that every touched table reads back as exactly the expected ordered list of (key, value), built from the old table
and the plan (a deleted key gone, a renamed one under its new key, a set value of the planned type and value, every
other entry with its old bytes, array entries numbered again); a top-level value set reads back as planned; and that
every byte outside the edit spans is unchanged. It returns the problems ([] when the edit checks out).
"""
from __future__ import annotations

from wowtools.core.luasv import Assignment, LuaParseError, Opaque, Scalar, Table, key_id, parse
from wowtools.core.sv_verify import NOT_THE_SAME, check_assignments, same_outside
from wowtools.tools.sv_browser.compile import FieldIndex, SvEdit, descend_into, locate, table_paths
from wowtools.tools.sv_browser.ops import FieldEdit, TypedPath, new_keys, path_text

TABLE = ("table",)  # an entry that is itself a touched table (checked as one of its own)
OUTSIDE = "bytes outside the edits changed"


def _typed_value(value: object) -> tuple:
    return ("value", type(value).__name__, value)


def _expected(old: bytes, table: Table, prefix: TypedPath, local: dict[tuple, FieldEdit],
              tables: set[TypedPath], moved: dict[TypedPath, TypedPath]) -> list[tuple]:
    """The (typed key, value) list table must read back as, local being the edits of its own keys (by typed key);
    records where each touched child table moves to."""
    rows = []
    for item, key in zip(table.fields, new_keys(table.fields, local)):
        if key is None:
            continue
        child = prefix + (key_id(item.key),)
        planned = local.get(child[-1])
        if child in tables:
            moved[child] = moved[prefix] + (key,)
            rows.append((key, TABLE))
        elif planned is not None and planned.set_value:
            rows.append((key, _typed_value(planned.value)))
        else:
            rows.append((key, old[item.value.start:item.value.end]))
    return rows


def _row(data: bytes, value: Table | Opaque | Scalar, want: object) -> object:
    """A new entry's value in the form of the expected one."""
    if want == TABLE:
        return TABLE if isinstance(value, (Table, Opaque)) else ("not a table",)
    if isinstance(want, tuple):
        return _typed_value(value.value) if isinstance(value, Scalar) else ("not a value",)
    return data[value.start:value.end]


def verify_edit(edit: SvEdit, old: bytes) -> list[str]:
    if edit.problems:
        return list(edit.problems)
    new = edit.data
    edits = {item.typed: item for item in edit.plan.edits}
    by_table: dict[TypedPath, dict[tuple, FieldEdit]] = {}  # the edits of each table's own keys
    for typed, item in edits.items():
        by_table.setdefault(typed[:-1], {})[typed[-1]] = item
    tables = table_paths(item.path for item in edit.plan.edits)
    labels = {item.typed[:n]: item.path[:n] for item in edit.plan.edits for n in range(1, len(item.path) + 1)}
    try:
        old_chunk = parse(old, descend_into(tables))
    except LuaParseError as exc:
        return [f"the file is not readable Lua ({exc})"]
    moved = {prefix: prefix for prefix in tables if len(prefix) == 1}
    expected: dict[TypedPath, list[tuple]] = {}
    old_index = FieldIndex(old_chunk)
    for prefix in sorted(tables, key=len):
        target, _, problem = locate(old_index, prefix, labels[prefix])
        if problem is None and not isinstance(target.value, Table):
            problem = f"{path_text(labels[prefix])} is not a table"
        if problem:
            return [problem]
        expected[prefix] = _expected(old, target.value, prefix, by_table.get(prefix, {}), tables, moved)
    try:
        new_chunk = parse(new, descend_into(set(moved.values())))
    except LuaParseError as exc:
        return [f"the edited file does not read back: {exc}"]

    def top_level(before: Assignment, after: Assignment) -> list[str]:
        planned = edits.get((key_id(before.name),))
        if planned is None or not planned.set_value:
            return []
        if isinstance(after.value, Scalar) and _typed_value(after.value.value) == _typed_value(planned.value):
            return []
        return [f"{before.name} does not read back as planned"]

    names = {item.path[0] for item in edit.plan.edits}
    problems = check_assignments(old, old_chunk, new, new_chunk, names, on_planned=top_level)
    if problems[:1] == [NOT_THE_SAME]:
        return problems
    new_index = FieldIndex(new_chunk)
    for prefix, rows in expected.items():
        label = path_text(labels[prefix])
        target, _, problem = locate(new_index, moved[prefix], labels[prefix])
        if problem is None and not isinstance(target.value, Table):
            problem = f"{label} is not a table"
        if problem:
            problems.append(f"the edited file: {problem}")
            continue
        fields = target.value.fields
        got = [(key_id(f.key), _row(new, f.value, want)) for f, (_, want) in zip(fields, rows)]
        if len(fields) != len(rows) or got != rows:
            problems.append(f"{label} does not read back as planned")
    if not same_outside(old, [o for o, _ in edit.spans], new, [n for _, n in edit.spans]):
        problems.append(OUTSIDE)
    return problems
