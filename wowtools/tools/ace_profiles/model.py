"""Which top-level SavedVariables are AceDB-3.0 databases, and their profiles, characters, module profiles and
LibDualSpec spec profiles (spec §2, §5.2). UI-free.

A database is recognised by its shape: `profileKeys` maps "Name - Realm" strings to profile-name strings, and
`profiles` (when present) maps names to tables. Look-alikes (GUID-keyed tables, arrays) are rejected with a note.
"""
from __future__ import annotations

from dataclasses import dataclass

from wowtools.tools.ace_profiles.luasv import Chunk, Field, Opaque, Scalar, Table, is_blank_table

LDS = "LibDualSpec-1.0"
DEFAULT = "Default"
CHAR_SEPARATOR = " - "


def ace_descend(path: tuple) -> bool:
    """Descend only where profile data lives: the database table, profileKeys, the keys of profiles, each
    namespace's profiles keys and LibDualSpec's per-character spec tables."""
    depth = len(path)
    if depth == 1:
        return True
    section = path[1]
    if depth == 2:
        return section in ("profileKeys", "profiles", "namespaces")
    if section != "namespaces":
        return False
    if depth == 3:
        return True
    if depth == 4:
        return path[3] == "profiles" or (path[2] == LDS and path[3] == "char")
    if depth == 5:
        return path[2] == LDS and path[3] == "char"
    return False


def has_profile_keys(data: bytes) -> bool:
    return b"profileKeys" in data


def split_char_key(key: str) -> tuple[str, str] | None:
    name, sep, realm = key.partition(CHAR_SEPARATOR)
    return (name, realm) if sep and name and realm else None


@dataclass
class ProfileEntry:
    name: str
    field: Field
    empty: bool
    size: int


@dataclass
class NamespaceProfiles:
    name: str
    table: Table
    entries: dict[str, Field]


@dataclass
class LdsChar:
    char: str
    enabled: bool
    specs: dict[int, Field]


@dataclass
class AceDb:
    sv_name: str
    keys_table: Table
    profile_keys: dict[str, str]
    key_fields: dict[str, Field]
    profiles_table: Table | None
    profiles: dict[str, ProfileEntry]
    namespaces: dict[str, NamespaceProfiles]
    lds: dict[str, LdsChar]

    def users(self, name: str) -> list[str]:
        return [char for char, profile in self.profile_keys.items() if profile == name]

    def profile_names(self) -> list[str]:
        referenced = sorted({p for p in self.profile_keys.values() if p not in self.profiles})
        return list(self.profiles) + referenced

    def missing(self, name: str) -> bool:
        return name not in self.profiles and name in self.profile_keys.values()

    def lds_enabled(self, char: str) -> bool:
        entry = self.lds.get(char)
        return entry is not None and entry.enabled


def _string_map(table: Table) -> dict[str, Field] | None:
    """{key: field} when every key is a string and every value a string scalar; else None."""
    out: dict[str, Field] = {}
    for item in table.fields:
        if not isinstance(item.key, str) or item.key in out:
            return None
        if not isinstance(item.value, Scalar) or not isinstance(item.value.value, str):
            return None
        out[item.key] = item
    return out


def _table_map(value) -> dict[str, Field] | None:
    """{key: field} when value is a table whose keys are strings and whose values are tables; else None."""
    if not isinstance(value, Table):
        return None
    out: dict[str, Field] = {}
    for item in value.fields:
        if not isinstance(item.key, str) or item.key in out or not isinstance(item.value, (Table, Opaque)):
            return None
        out[item.key] = item
    return out


def _namespaces(db_table: Table) -> dict[str, NamespaceProfiles]:
    found: dict[str, NamespaceProfiles] = {}
    holder = db_table.get("namespaces")
    if holder is None or not isinstance(holder.value, Table):
        return found
    for ns in holder.value.fields:
        if not isinstance(ns.key, str) or not isinstance(ns.value, Table):
            continue
        profiles = ns.value.get("profiles")
        entries = _table_map(profiles.value) if profiles is not None else None
        if entries is not None:
            found[ns.key] = NamespaceProfiles(ns.key, profiles.value, entries)
    return found


def _lds(db_table: Table) -> dict[str, LdsChar]:
    found: dict[str, LdsChar] = {}
    holder = db_table.get("namespaces")
    if holder is None or not isinstance(holder.value, Table):
        return found
    lds = holder.value.get(LDS)
    chars = lds.value.get("char") if lds is not None and isinstance(lds.value, Table) else None
    if chars is None or not isinstance(chars.value, Table):
        return found
    for entry in chars.value.fields:
        if not isinstance(entry.key, str) or not isinstance(entry.value, Table):
            continue
        enabled = entry.value.get("enabled")
        specs = {item.key: item for item in entry.value.fields
                 if isinstance(item.key, int) and not isinstance(item.key, bool)
                 and isinstance(item.value, Scalar) and isinstance(item.value.value, str)}
        found[entry.key] = LdsChar(entry.key, bool(enabled and isinstance(enabled.value, Scalar)
                                                    and enabled.value.value is True), specs)
    return found


def find_dbs(chunk: Chunk, data: bytes) -> tuple[list[AceDb], list[str]]:
    dbs: list[AceDb] = []
    notes: list[str] = []
    for assignment in chunk.assignments:
        table = assignment.value
        if not isinstance(table, Table):
            continue
        keys = table.get("profileKeys")
        if keys is None:
            continue
        name = assignment.name
        key_fields = _string_map(keys.value) if isinstance(keys.value, Table) else None
        if key_fields is None or any(split_char_key(k) is None for k in key_fields):
            notes.append(f"{name}: profileKeys is not an AceDB character map; left alone")
            continue
        profiles_field = table.get("profiles")
        profile_fields = _table_map(profiles_field.value) if profiles_field is not None else {}
        if profile_fields is None:
            notes.append(f"{name}: profiles is not an AceDB profile table; left alone")
            continue
        profiles = {n: ProfileEntry(n, f, is_blank_table(data, f.value), f.value.end - f.value.start)
                    for n, f in profile_fields.items()}
        dbs.append(AceDb(name, keys.value, {k: f.value.value for k, f in key_fields.items()}, key_fields,
                         profiles_field.value if profiles_field is not None else None, profiles,
                         _namespaces(table), _lds(table)))
    return dbs, notes
