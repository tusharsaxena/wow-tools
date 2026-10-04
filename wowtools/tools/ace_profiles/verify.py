"""Re-read an edited SavedVariables file and check it says exactly what was staged (spec §8.2). UI-free."""
from __future__ import annotations

from wowtools.tools.ace_profiles.luasv import Chunk, LuaParseError, Table, parse
from wowtools.tools.ace_profiles.model import ace_descend, find_dbs, lds_chars, namespace_profiles
from wowtools.tools.ace_profiles.ops import FileEdit

PROFILE_SECTIONS = ("profileKeys", "profiles", "namespaces")


def _gaps(data: bytes, chunk: Chunk) -> list[bytes]:
    """The bytes between and around the top-level assignments (blank lines, comments)."""
    out, pos = [], 0
    for item in chunk.assignments:
        out.append(data[pos:item.start])
        pos = item.end
    out.append(data[pos:])
    return out


def _namespaces_rest(data: bytes, table: Table) -> bytes | None:
    """The bytes of the namespaces section with only what the tool may change cut out: the inside of each
    module's profiles table (checked entry by entry against the expected model) and each LibDualSpec spec value.
    Everything else in it (a module's global or char data, LibDualSpec's enabled flags) must stay as it was."""
    holder = table.get("namespaces")
    if holder is None:
        return None
    cuts = [(ns.table.start + 1, ns.table.close) for ns in namespace_profiles(table).values()]
    cuts += [(f.value.start, f.value.end) for entry in lds_chars(table).values() for f in entry.specs.values()]
    out, pos = [], holder.value.start
    for start, end in sorted(cuts):
        out.append(data[pos:start])
        pos = end
    out.append(data[pos:holder.value.end])
    return b"\0".join(out)


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
    problems: list[str] = []
    if [a.name for a in new_chunk.assignments] != [a.name for a in old_chunk.assignments]:
        return ["the edited file does not hold the same SavedVariables"]
    if _gaps(edit.data, new_chunk) != _gaps(old, old_chunk):
        problems.append("text between the SavedVariables changed")
    for before, after in zip(old_chunk.assignments, new_chunk.assignments):
        if before.name in edit.expected:
            if isinstance(before.value, Table) and isinstance(after.value, Table):
                old_other, new_other = _other_sections(old, before.value), _other_sections(edit.data, after.value)
                for key in sorted(set(old_other) | set(new_other), key=str):
                    if old_other.get(key) != new_other.get(key):
                        problems.append(f"{before.name}: section {key} changed")
            continue
        if old[before.start:before.end] != edit.data[after.start:after.end]:
            problems.append(f"{before.name} changed but nothing was planned for it")
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
