"""Re-read an edited SavedVariables file and check it says exactly what was staged (spec §8.2). UI-free."""
from __future__ import annotations

from wowtools.core.luasv import Assignment, LuaParseError, Table, parse
from wowtools.core.sv_verify import NOT_THE_SAME, check_assignments, rest_outside
from wowtools.tools.ace3_profile_manager.model import ace_descend, find_dbs, lds_chars, namespace_profiles
from wowtools.tools.ace3_profile_manager.ops import FileEdit

PROFILE_SECTIONS = ("profileKeys", "profiles", "namespaces")


def _namespaces_rest(data: bytes, table: Table) -> bytes | None:
    """The bytes of the namespaces section with only what the tool may change cut out: the inside of each
    module's profiles table (checked entry by entry against the expected model) and each LibDualSpec spec value.
    Everything else in it (a module's global or char data, LibDualSpec's enabled flags) must stay as it was."""
    holder = table.get("namespaces")
    if holder is None:
        return None
    cuts = [(ns.table.start + 1, ns.table.close) for ns in namespace_profiles(table).values()]
    cuts += [(f.value.start, f.value.end) for entry in lds_chars(table).values() for f in entry.specs.values()]
    return rest_outside(data, holder.value.start, holder.value.end, cuts)


def _other_sections(data: bytes, table: Table) -> dict:
    out = {f.key: data[f.value.start:f.value.end] for f in table.fields if f.key not in PROFILE_SECTIONS}
    out["namespaces"] = _namespaces_rest(data, table)
    return out


def verify_edit(edit: FileEdit, old: bytes) -> list[str]:
    try:
        new_chunk = parse(edit.data, ace_descend)
    except LuaParseError as exc:
        return [f"the edited file does not read back: {exc}"]
    old_chunk = parse(old, ace_descend)

    def sections(before: Assignment, after: Assignment) -> list[str]:
        if not (isinstance(before.value, Table) and isinstance(after.value, Table)):
            return []
        old_other, new_other = _other_sections(old, before.value), _other_sections(edit.data, after.value)
        return [f"{before.name}: section {key} changed" for key in sorted(set(old_other) | set(new_other), key=str)
                if old_other.get(key) != new_other.get(key)]

    problems = check_assignments(old, old_chunk, edit.data, new_chunk, edit.expected, on_planned=sections)
    if problems[:1] == [NOT_THE_SAME]:
        return problems
    dbs = {db.sv_name: db for db in find_dbs(new_chunk, edit.data)[0]}
    for name, expected in edit.expected.items():
        db = dbs.get(name)
        if db is None:
            problems.append(f"{name} no longer reads as an AceDB database")
            continue
        if db.profile_keys != expected.profile_keys:
            problems.append(f"{name}: the character to profile mapping is not what was planned")
        got = {n: edit.data[e.field.value.start:e.field.value.end] for n, e in db.profiles.items()}
        if got != expected.profiles:
            problems.append(f"{name}: the profiles are not what was planned")
        for ns_name, ns_expected in expected.namespaces.items():
            ns = db.namespaces.get(ns_name)
            ns_got = {} if ns is None else {n: edit.data[f.value.start:f.value.end] for n, f in ns.entries.items()}
            if ns_got != ns_expected:
                problems.append(f"{name}: module {ns_name}'s profiles are not what was planned")
        lds = {c: {i: f.value.value for i, f in entry.specs.items()} for c, entry in db.lds.items()}
        if {c: lds.get(c) for c in expected.lds} != expected.lds:
            problems.append(f"{name}: LibDualSpec spec profiles are not what was planned")
    return problems
