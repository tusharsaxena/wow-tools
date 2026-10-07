"""Staged edits of the Saved Variables Browser (spec D5, D12) and the per-file plans Apply writes. UI-free.

Nothing is written until Apply. Staging holds, per file, the edits made on the lazy tree's nodes (model.Node), each
keyed by the node's typed path (luasv.key_id per key, so true, 1 and "1" differ and [1.0] is [1]) and kept in the
coordinates of the bytes the document read (its SHA-256 is recorded with them, D17). An edit on one key may set its
value, rename it, or both; or delete it. D5's rules are enforced here:
- set value: any scalar (string, number, boolean; the type may change), never nil (that is a delete) and never a
  table; a top-level `Name = scalar` too. A number must read back in Lua as itself (search.number_problem).
- rename: never a top-level SavedVariable, never an array entry (no written key), never to a key the table would
  then hold twice (by Lua identity, counting the edits already staged in that table).
- delete: never a top-level SavedVariable; an array entry with a warning (later entries move down, as table.remove
  does, and their `-- [n]` comments go stale). Deleting a table drops the edits staged inside it, and nothing can be
  staged inside a deleted key.

Search hits are staged the same way (D39: a bulk Edit value or Rename key on the ticked results stages one edit per
hit, stage_hit_value / stage_hit_rename), keyed by the hit's typed path and the SHA-256 of the bytes the search read,
so Browse shows them as its own. A hit is refused (the bulk edit leaves it out) when its key already has a staged
edit, is on or under a staged delete, comes from other bytes than the file's staged edits or loaded document, or
breaks a D5 rule (a top-level or array-entry rename, a key its table would hold twice: the rename is given that
table, bulk.read_tables).

plans() is what Apply writes: the staged edits only (ticks select results, D39), one FilePlan per file, keyed by its
SvFile carrying the SHA-256 the edits were made against (the shared pipeline skips a file whose bytes changed since).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.core.luasv import Field, Table, encode_value, key_id
from wowtools.core.svfiles import SvFile
from wowtools.tools.sv_browser.model import VALUE, Node, SvDocument, key_text
from wowtools.tools.sv_browser.search import REPLACE_NUMBER, Hit, Replacement, number_problem, parse_replacement

TypedPath = tuple  # luasv.key_id of each key, the top-level name first

SHIFT_WARNING = ("This is an array entry: the entries after it move down one place (as table.remove does) and their "
                 "-- [n] comments no longer match.")
TOP_LEVEL = "A top-level SavedVariable can't be renamed or deleted."
ARRAY_RENAME = "An array entry has no written key to rename."
NOT_A_VALUE = "Only a value that is not a table can be edited."
NIL_VALUE = "A value can't be set to nil: delete the key instead."
INSIDE_DELETE = "It is staged for delete (or inside a key staged for delete)."
NOT_LOADED = "The file is not loaded."
CHANGED = "The file changed since its edits were staged; rescan."
NOTHING_STAGED = "Nothing is staged on it."
EMPTY_KEY = "A key can't be empty."
_NUMBER_START = re.compile(r"[-.\d]")

# Why a search hit can't be staged (a bulk edit leaves it out, D39), besides the D5 refusals above.
ALREADY_STAGED = "It already has a staged edit."
UNDER_DELETE = "It is staged for delete, or inside a key staged for delete."
FILE_CHANGED = "The file changed since the search; search again."
# The hit's bytes differ from the document Browse loaded or the file's staged edits (both kept until a rescan): a new
# search reads the file again, and only clears it when the search was the older read.
BYTES_DIFFER = ("The search read other bytes than the file opened in Browse (or its staged edits); search again, "
                "and rescan if that does not clear it.")


def typed_path(path: Sequence) -> TypedPath:
    return tuple(key_id(k) for k in path)


def path_text(path: Sequence) -> str:
    """A key path as the tree shows it: `ElvDB › profiles › [5]`."""
    return " › ".join(key_text(k) for k in path)


@dataclass(frozen=True, slots=True)
class FieldEdit:
    """What happens to one key: its value set (set_value, value), its key renamed (rename, new_key; new_key may be
    False, so a flag says whether it is set), or the key deleted. path: the top-level name, then each key as the
    file holds it now. positional: an array entry (no written key)."""
    path: tuple
    set_value: bool = False
    value: Replacement | None = None
    rename: bool = False
    new_key: object = None
    delete: bool = False
    positional: bool = False

    @property
    def typed(self) -> TypedPath:
        return typed_path(self.path)

    @property
    def empty(self) -> bool:
        return not (self.set_value or self.rename or self.delete)


def new_keys(fields: Sequence[Field], edits: Mapping[tuple, FieldEdit]) -> list[tuple | None]:
    """The typed key each field of a table has once edits (by the field's typed key) are written: None when deleted,
    the new key when renamed, the next index for an array entry (entries after a deleted one move down)."""
    out: list[tuple | None] = []
    index = 1
    for item in fields:
        edit = edits.get(key_id(item.key))
        if edit is not None and edit.delete:
            out.append(None)
        elif item.key_span is None:
            out.append(("int", index))
            index += 1
        elif edit is not None and edit.rename:
            out.append(key_id(edit.new_key))
        else:
            out.append(key_id(item.key))
    return out


def new_duplicates(fields: Sequence[Field], edits: Mapping[tuple, FieldEdit]) -> list[tuple]:
    """Typed keys the table would hold more than once after edits that it does not hold more than once now."""
    def twice(keys: Iterable[tuple | None]) -> set[tuple]:
        return {k for k, n in Counter(k for k in keys if k is not None).items() if n > 1}
    return sorted(twice(new_keys(fields, edits)) - twice(new_keys(fields, {})), key=repr)


def key_problem(key: object) -> str | None:
    """Why key can't be written as a table key, or None."""
    if key is None:
        return "A key can't be nil."
    if isinstance(key, str):
        return EMPTY_KEY if key == "" else None
    if isinstance(key, float) and not math.isfinite(key):
        return "Infinity and nan can't be keys."
    if isinstance(key, (int, float)) and not isinstance(key, bool):
        problem = number_problem(key)
        return f"Can't use {key!r} as a key: {problem}." if problem else None
    if isinstance(key, bool):
        return None
    return "A key must be a string, a number or a boolean."


def value_problem(value: object) -> str | None:
    """Why value can't be set, or None."""
    if value is None:
        return NIL_VALUE
    if isinstance(value, (str, bool)):
        return None
    if isinstance(value, (int, float)):
        problem = number_problem(value)
        return f"Can't use {value!r}: {problem}." if problem else None
    return "A value must be a string, a number or a boolean."


def _same_value(value: object, old: object) -> bool:
    """True when value is the value already there, by Lua identity (12.0 is 12; "12", 12 and true differ), however
    it is written."""
    if old is None or not isinstance(old, (str, int, float)) or not isinstance(value, (str, int, float)):
        return False  # nil, or a raw number (1.#INF) Python can't hold
    return key_id(value) == key_id(old) and (not isinstance(value, float) or value == old)


def parse_key(text: str) -> object:
    """A key typed as the tree shows it (model.key_text): `[5]`, `[2.5]`, `[true]`, `[false]` are a number or a
    boolean key; `["…"]` is the string between the quotes, as typed (no escapes); anything else is a string key, as
    typed. A number must read back as itself (search.parse_replacement). Raises ValueError for the user."""
    if len(text) >= 4 and text.startswith('["') and text.endswith('"]'):
        return text[2:-2]
    if text == '[""]':
        return ""
    if len(text) >= 2 and text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if inner in ("true", "false"):
            return inner == "true"
        if inner and _NUMBER_START.match(inner):
            return parse_replacement(REPLACE_NUMBER, inner)
    return text


def key_input(key: object) -> str:
    """A key as parse_key reads it back (the rename popup's starting text)."""
    if isinstance(key, str):
        return f'["{key}"]' if key == "" or parse_key(key) != key or type(parse_key(key)) is not str else key
    return key_text(key)


@dataclass
class OpResult:
    """What a staging call did: ok, or refused with message. warning: shown before an array entry is deleted;
    dropped: staged edits inside a deleted table that went with it."""
    ok: bool
    message: str = ""
    warning: str | None = None
    dropped: int = 0


@dataclass
class _FileStage:
    file: SvFile
    sha256: str
    edits: dict[TypedPath, FieldEdit] = field(default_factory=dict)


@dataclass
class FilePlan:
    """One file's edits for Apply. file carries the SHA-256 they were made against."""
    file: SvFile
    edits: list[FieldEdit]


@dataclass
class Plan:
    files: dict[SvFile, FilePlan] = field(default_factory=dict)
    staged: int = 0  # staged edits in the plan

    def units(self) -> list[tuple[SvFile, FilePlan]]:
        """(file, plan) per file, the shared pipeline's units."""
        return list(self.files.items())


class Staging:
    """The edits staged on the review, per file (by path)."""

    def __init__(self) -> None:
        self._files: dict[Path, _FileStage] = {}

    @property
    def count(self) -> int:
        return sum(len(stage.edits) for stage in self._files.values())

    def files(self) -> list[SvFile]:
        return [stage.file for stage in self._files.values() if stage.edits]

    def clear(self) -> None:
        self._files.clear()

    def _stage(self, doc: SvDocument, create: bool = False) -> _FileStage | None:
        stage = self._files.get(doc.file.path)
        if stage is None and create:
            stage = self._files[doc.file.path] = _FileStage(doc.file, doc.sha256 or "")
        return stage

    def edit_for(self, doc: SvDocument, node: Node) -> FieldEdit | None:
        """The edit staged on node, if any (the review marks it)."""
        stage = self._stage(doc)
        return None if stage is None or node.kind != VALUE else stage.edits.get(typed_path(node.path))

    def deleted_above(self, doc: SvDocument, node: Node) -> bool:
        """True when node or a key above it is staged for delete."""
        stage = self._stage(doc)
        if stage is None or node.kind != VALUE:
            return False
        typed = typed_path(node.path)
        return any(getattr(stage.edits.get(typed[:n]), "delete", False) for n in range(1, len(typed) + 1))

    def _refused(self, doc: SvDocument, node: Node) -> str | None:
        """Why nothing may be staged on node at all."""
        if node.kind != VALUE or doc.sha256 is None or doc.data is None or doc.error is not None:
            return NOT_LOADED
        stage = self._stage(doc)
        if stage is not None and stage.edits and stage.sha256 != doc.sha256:
            return CHANGED
        return None

    def _put(self, doc: SvDocument, node: Node, edit: FieldEdit, operation: str) -> None:
        stage = self._stage(doc, create=True)
        stage.sha256 = doc.sha256 or ""
        typed = typed_path(node.path)
        if edit.empty:
            stage.edits.pop(typed, None)
        else:
            stage.edits[typed] = edit
        log_event("svb.staged", operation=operation, flavor=doc.file.flavor.folder, path=doc.file.rel,
                  key=path_text(node.path))

    def _current(self, doc: SvDocument, node: Node) -> FieldEdit:
        return self.edit_for(doc, node) or FieldEdit(node.path, positional=node.positional)

    def _clash(self, doc: SvDocument, node: Node, edit: FieldEdit) -> list[tuple]:
        """Keys node's table would hold twice with edit staged on node."""
        parent = node.parent
        if parent is None or not isinstance(parent.value, Table):
            return []
        return _table_clash(self._stage(doc), parent.value, typed_path(node.path), edit)

    def set_problem(self, doc: SvDocument, node: Node, value: object) -> str | None:
        """Why set_value would refuse value on node, or None (stages nothing)."""
        return self._refused(doc, node) or (None if node.can_edit_value else NOT_A_VALUE) \
            or value_problem(value) or (INSIDE_DELETE if self.deleted_above(doc, node) else None)

    def set_value(self, doc: SvDocument, node: Node, value: Replacement) -> OpResult:
        problem = self.set_problem(doc, node, value)
        if problem:
            return OpResult(False, problem)
        current = self._current(doc, node)
        same = _same_value(value, node.value.value) or encode_value(value) == doc.data[node.value.start:node.value.end]
        edit = replace(current, set_value=not same, value=None if same else value)
        self._put(doc, node, edit, "set")
        return OpResult(True, "unchanged" if same else "")

    def rename_problem(self, doc: SvDocument, node: Node, new_key: object) -> str | None:
        """Why rename would refuse new_key on node, or None (stages nothing)."""
        problem = self._refused(doc, node)
        if problem is None and not node.can_rename:
            problem = TOP_LEVEL if node.top_level else ARRAY_RENAME
        problem = problem or key_problem(new_key) or (INSIDE_DELETE if self.deleted_above(doc, node) else None)
        if problem:
            return problem
        clash = self._clash(doc, node, self._renamed(doc, node, new_key))
        return f"The table already has the key {key_text(clash[0][1])}." if clash else None

    def _renamed(self, doc: SvDocument, node: Node, new_key: object) -> FieldEdit:
        same = key_id(new_key) == key_id(node.key)
        return replace(self._current(doc, node), rename=not same, new_key=None if same else new_key)

    def rename(self, doc: SvDocument, node: Node, new_key: object) -> OpResult:
        problem = self.rename_problem(doc, node, new_key)
        if problem:
            return OpResult(False, problem)
        edit = self._renamed(doc, node, new_key)
        self._put(doc, node, edit, "rename")
        return OpResult(True, "" if edit.rename else "unchanged")

    def delete_problem(self, doc: SvDocument, node: Node) -> str | None:
        """Why delete would refuse node, or None (stages nothing)."""
        problem = self._refused(doc, node)
        if problem is None and not node.can_delete:
            problem = TOP_LEVEL
        if problem is None and self.deleted_above(doc, node):  # itself (nothing left to do) or a key above it
            problem = INSIDE_DELETE
        return problem

    def staged_inside(self, doc: SvDocument, node: Node) -> int:
        """Edits staged below node (a delete of node drops them)."""
        stage = self._stage(doc)
        typed = typed_path(node.path)
        return sum(1 for t in (stage.edits if stage else ()) if len(t) > len(typed) and t[:len(typed)] == typed)

    def delete(self, doc: SvDocument, node: Node) -> OpResult:
        problem = self.delete_problem(doc, node)
        if problem:
            return OpResult(False, problem)
        stage = self._stage(doc, create=True)
        typed = typed_path(node.path)
        inside = [t for t in stage.edits if len(t) > len(typed) and t[:len(typed)] == typed]
        for t in inside:
            del stage.edits[t]
        self._put(doc, node, FieldEdit(node.path, delete=True, positional=node.positional), "delete")
        return OpResult(True, warning=SHIFT_WARNING if node.positional else None, dropped=len(inside))

    def unstage(self, doc: SvDocument, node: Node) -> OpResult:
        """Drop everything staged on node (Backspace)."""
        edit = self.edit_for(doc, node)
        if edit is None:
            return OpResult(False, NOTHING_STAGED)
        clash = self._clash(doc, node, FieldEdit(node.path))
        if clash:
            return OpResult(False, f"Unstaging it would leave the key {key_text(clash[0][1])} twice in its table; "
                                   f"unstage the rename to that key first.")
        self._stage(doc).edits.pop(typed_path(node.path))
        log_event("svb.unstaged", flavor=doc.file.flavor.folder, path=doc.file.rel, key=path_text(node.path))
        return OpResult(True)

    # --- search hits (D39) -------------------------------------------------------------------------
    def hit_edit(self, hit: Hit) -> FieldEdit | None:
        """The edit staged on the hit's key, if any (made on it or in Browse)."""
        stage = self._files.get(hit.file.path)
        return None if stage is None else stage.edits.get(hit.typed_path)

    def hit_deleted_above(self, hit: Hit) -> bool:
        """True when the hit's key or a key above it is staged for delete."""
        stage = self._files.get(hit.file.path)
        typed = hit.typed_path
        return stage is not None and any(getattr(stage.edits.get(typed[:n]), "delete", False)
                                         for n in range(1, len(typed) + 1))

    def _hit_refused(self, hit: Hit, doc_sha: str | None) -> str | None:
        """Why nothing may be staged on hit: the bytes differ from the file's staged edits' or its loaded document's
        (doc_sha), or its key already has an edit or is under a delete."""
        stage = self._files.get(hit.file.path)
        if (stage is not None and stage.edits and stage.sha256 != hit.sha256) or \
                (doc_sha is not None and doc_sha != hit.sha256):
            return BYTES_DIFFER
        if self.hit_edit(hit) is not None:
            return ALREADY_STAGED
        return UNDER_DELETE if self.hit_deleted_above(hit) else None

    def _put_hit(self, hit: Hit, edit: FieldEdit, operation: str) -> None:
        stage = self._files.get(hit.file.path)
        if stage is None:
            stage = self._files[hit.file.path] = _FileStage(hit.file, hit.sha256)
        stage.sha256 = hit.sha256
        stage.edits[hit.typed_path] = edit
        log_event("svb.staged", operation=operation, flavor=hit.file.flavor.folder, path=hit.file.rel,
                  key=path_text(hit.path))

    def stage_hit_value(self, hit: Hit, value: Replacement | None, doc_sha: str | None = None) -> OpResult:
        """Stage value on the hit's key (D39). The value already there stages nothing ("unchanged", D29)."""
        problem = self._hit_refused(hit, doc_sha) or value_problem(value)
        if problem:
            return OpResult(False, problem)
        if _same_value(value, hit.old) or encode_value(value) == hit.old_bytes:
            return OpResult(True, "unchanged")
        self._put_hit(hit, FieldEdit(hit.path, set_value=True, value=value, positional=hit.key_span is None), "set")
        return OpResult(True)

    def stage_hit_rename(self, hit: Hit, new_key: object, table: Table | None,
                         doc_sha: str | None = None) -> OpResult:
        """Stage a rename of the hit's key to new_key (D39, D5). table: the table holding the key, as the search's
        bytes have it (bulk.read_tables), for the duplicate check. Its own key stages nothing ("unchanged")."""
        if len(hit.path) < 2:
            return OpResult(False, TOP_LEVEL)
        if hit.key_span is None:
            return OpResult(False, ARRAY_RENAME)
        problem = key_problem(new_key) or self._hit_refused(hit, doc_sha)
        if problem:
            return OpResult(False, problem)
        if key_id(new_key) == key_id(hit.key):
            return OpResult(True, "unchanged")
        edit = FieldEdit(hit.path, rename=True, new_key=new_key)
        if table is None:
            return OpResult(False, NOT_LOADED)
        clash = _table_clash(self._files.get(hit.file.path), table, hit.typed_path, edit)
        if clash:
            return OpResult(False, f"The table already has the key {key_text(clash[0][1])}.")
        self._put_hit(hit, edit, "rename")
        return OpResult(True)

    def unstage_hit(self, hit: Hit, table: Table | str | None = None) -> OpResult:
        """Drop what is staged on the hit's key (Backspace in Results). table: the key's table, needed to unstage a
        rename (it must not leave a key twice); a str (bulk.read_tables) is why it could not be read."""
        edit = self.hit_edit(hit)
        if edit is None:
            return OpResult(False, NOTHING_STAGED)
        stage = self._files[hit.file.path]
        if edit.rename:
            if table is None or isinstance(table, str):
                return OpResult(False, table or NOT_LOADED)
            clash = _table_clash(stage, table, hit.typed_path, FieldEdit(hit.path))
            if clash:
                return OpResult(False, f"Unstaging it would leave the key {key_text(clash[0][1])} twice in its "
                                       f"table; unstage the rename to that key first.")
        stage.edits.pop(hit.typed_path)
        log_event("svb.unstaged", flavor=hit.file.flavor.folder, path=hit.file.rel, key=path_text(hit.path))
        return OpResult(True)

    def plans(self) -> Plan:
        """The staged edits as one FilePlan per file (what Apply and Dry run write)."""
        plan = Plan()
        for stage in self._files.values():
            if stage.edits:
                file = replace(stage.file, sha256=stage.sha256)
                plan.files[file] = FilePlan(file, list(stage.edits.values()))
                plan.staged += len(stage.edits)
        return plan


def _table_clash(stage: _FileStage | None, table: Table, typed: TypedPath, edit: FieldEdit) -> list[tuple]:
    """Keys table (holding the key at typed) would hold twice with edit staged on that key, counting the edits
    already staged in it."""
    parent = typed[:-1]
    edits = {t[-1]: e for t, e in (stage.edits.items() if stage else ()) if t[:-1] == parent}
    if edit.empty:
        edits.pop(typed[-1], None)
    else:
        edits[typed[-1]] = edit
    return new_duplicates(table.fields, edits)
