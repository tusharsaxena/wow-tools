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

plans(hits) joins the staged edits with the ticked search hits (D11, D12): a hit sets the value to its replacement
(a whole value, or the string with the Contains text replaced). A hit on a value that has a staged edit, or on or
under a staged delete, is dropped with its reason (the staged edit wins); a hit on a key that is only renamed
combines with the rename. Hits from a file whose bytes differ from what its staged edits were made on are dropped.
The result is one FilePlan per file, keyed by its SvFile carrying the SHA-256 the edits were made against (the
shared pipeline skips a file whose bytes changed since).
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.core.luasv import Field, Table, encode_value, key_id
from wowtools.core.svfiles import SvFile
from wowtools.tools.sv_browser.model import VALUE, Node, SvDocument, key_text
from wowtools.tools.sv_browser.search import Hit, Replacement, number_problem

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

# Why a ticked hit is left out of a plan (DroppedHit.reason).
HAS_STAGED_EDIT = "its value has a staged edit (the staged edit wins)"
UNDER_DELETE = "it is staged for delete, or inside a key staged for delete"
FILE_CHANGED = "the file changed between browsing and the search; rescan"
DUPLICATE_HIT = "the same value is ticked twice"


def typed_path(path: Sequence) -> TypedPath:
    return tuple(key_id(k) for k in path)


def path_text(path: Sequence) -> str:
    """A key path as the tree shows it: `ElvDB › profiles › [5]`."""
    return " › ".join(key_text(k) for k in path)


@dataclass(frozen=True, slots=True)
class FieldEdit:
    """What happens to one key: its value set (set_value, value), its key renamed (rename, new_key; new_key may be
    False, so a flag says whether it is set), or the key deleted. path: the top-level name, then each key as the
    file holds it now. positional: an array entry (no written key). hit: the value comes from a ticked search hit."""
    path: tuple
    set_value: bool = False
    value: Replacement | None = None
    rename: bool = False
    new_key: object = None
    delete: bool = False
    positional: bool = False
    hit: bool = False

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


@dataclass(frozen=True)
class DroppedHit:
    hit: Hit
    reason: str


@dataclass
class Plan:
    files: dict[SvFile, FilePlan] = field(default_factory=dict)
    dropped: list[DroppedHit] = field(default_factory=list)
    staged: int = 0  # staged edits in the plan
    hits: int = 0  # ticked hits in the plan (a hit combined with a staged rename included)

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
        stage = self._stage(doc)
        parent_typed = typed_path(parent.path)
        edits = {typed[-1]: e for typed, e in (stage.edits.items() if stage else ())
                 if typed[:-1] == parent_typed}
        own = typed_path(node.path)[-1]
        if edit.empty:
            edits.pop(own, None)
        else:
            edits[own] = edit
        return new_duplicates(parent.value.fields, edits)

    def set_value(self, doc: SvDocument, node: Node, value: Replacement) -> OpResult:
        problem = self._refused(doc, node) or (None if node.can_edit_value else NOT_A_VALUE) \
            or value_problem(value) or (INSIDE_DELETE if self.deleted_above(doc, node) else None)
        if problem:
            return OpResult(False, problem)
        current = self._current(doc, node)
        same = encode_value(value) == doc.data[node.value.start:node.value.end]
        edit = replace(current, set_value=not same, value=None if same else value)
        self._put(doc, node, edit, "set")
        return OpResult(True, "unchanged" if same else "")

    def rename(self, doc: SvDocument, node: Node, new_key: object) -> OpResult:
        problem = self._refused(doc, node)
        if problem is None and not node.can_rename:
            problem = TOP_LEVEL if node.top_level else ARRAY_RENAME
        problem = problem or key_problem(new_key) or (INSIDE_DELETE if self.deleted_above(doc, node) else None)
        if problem:
            return OpResult(False, problem)
        current = self._current(doc, node)
        same = key_id(new_key) == key_id(node.key)
        edit = replace(current, rename=not same, new_key=None if same else new_key)
        clash = self._clash(doc, node, edit)
        if clash:
            return OpResult(False, f"The table already has the key {key_text(clash[0][1])}.")
        self._put(doc, node, edit, "rename")
        return OpResult(True, "unchanged" if same else "")

    def delete(self, doc: SvDocument, node: Node) -> OpResult:
        problem = self._refused(doc, node)
        if problem is None and not node.can_delete:
            problem = TOP_LEVEL
        if problem is None and node.parent is not None and self.deleted_above(doc, node.parent):
            problem = INSIDE_DELETE
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

    def plans(self, hits: Iterable[Hit] = ()) -> Plan:
        """The staged edits plus the ticked hits as one FilePlan per file (D12's overlap rules). Hits of a find-only
        search (no replacement) are ignored."""
        plan = Plan()
        work: dict[Path, tuple[SvFile, dict[TypedPath, FieldEdit]]] = {}
        for path, stage in self._files.items():
            if stage.edits:
                work[path] = (replace(stage.file, sha256=stage.sha256), dict(stage.edits))
                plan.staged += len(stage.edits)
        for hit in hits:
            if hit.new is None:
                continue
            file, edits = work.setdefault(hit.file.path, (hit.file, {}))
            reason = _overlap(file, edits, hit)
            if reason:
                plan.dropped.append(DroppedHit(hit, reason))
                continue
            typed = hit.typed_path
            current = edits.get(typed) or FieldEdit(hit.path, positional=hit.key_span is None)
            edits[typed] = replace(current, set_value=True, value=hit.new, hit=True)
            plan.hits += 1
        for file, edits in work.values():
            if edits:
                plan.files[file] = FilePlan(file, list(edits.values()))
        return plan


def _overlap(file: SvFile, edits: dict[TypedPath, FieldEdit], hit: Hit) -> str | None:
    """Why hit can't join the file's edits (D12), or None."""
    if file.sha256 != hit.sha256:
        return FILE_CHANGED
    typed = hit.typed_path
    if any(getattr(edits.get(typed[:n]), "delete", False) for n in range(1, len(typed) + 1)):
        return UNDER_DELETE
    current = edits.get(typed)
    if current is not None and current.set_value:
        return DUPLICATE_HIT if current.hit else HAS_STAGED_EDIT
    return None
