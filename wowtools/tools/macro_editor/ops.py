"""Staged macro changes: paste, edit, new, delete and Replace text, and the bytes they write (config tools spec ME3,
ME4, ME6, ME7, ME13). UI-free; never writes a file.

Staged holds at most one MacroChange per macro id and file, folded as the user works: editing a macro that a paste
or New added keeps it an `add` with the new text, deleting it drops it, and an edit back to the file's own text
drops the change. Every operation works on the set as staged so far (effective_macros), so a second Replace text
sees the first one's text and a paste counts the slots earlier pastes took.

IDs (ME6, V5): an edit or an overwrite keeps the macro's id, so the target's action bar buttons keep working; a new
or pasted macro gets the highest id of its prefix plus one, counting every id the file holds as read (a macro
deleted in the same run never gives its id away) and every add staged so far. A name is cut at NAME_LIMIT, as the
client does; a body over BODY_LIMIT characters, or one the file layout can't hold, is refused for that macro.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from wowtools.core.client_apply import ClientChange
from wowtools.core.macrofile import (BODY_LIMIT, ICON_DEFAULT, NAME_LIMIT, Macro, MacroChange, MacroFile,
                                     apply_macro_changes, next_macro_id, parse_macros)
from wowtools.tools.macro_editor.model import MACRO_FILE, MacroSet

__all__ = ["ClashChoice", "PasteClash", "PastePreview", "ReplaceRow", "Staged", "body_length", "build_changes",
           "check_macro", "clash_key", "copy_staged", "cut_name", "effective_macros", "free_slots", "preview_paste",
           "preview_replace", "rename_for_clash", "stage_delete", "stage_edit", "stage_new", "stage_paste",
           "stage_replace_text"]

ClashChoice = Literal["skip", "rename", "overwrite"]
_EMPTY = parse_macros(b"")
_PROBE_ID = "0" * 16


@dataclass
class Staged:
    """Pending changes per set path, at most one per macro id, in the order they were first staged."""
    changes: dict[Path, list[MacroChange]] = field(default_factory=dict)

    def count(self) -> int:
        return sum(len(changes) for changes in self.changes.values())

    def clear(self) -> None:
        self.changes.clear()


@dataclass(frozen=True)
class ReplaceRow:
    """One macro Replace text would change: its body before and after, how many matches, and why it is refused
    (None: it can be staged)."""
    mset: MacroSet
    macro: Macro
    before: str
    after: str
    count: int
    refusal: str | None


def cut_name(name: str) -> str:
    return name[:NAME_LIMIT]


def body_length(body: str) -> int:
    """What the client's `n/255` counts: characters, a line break being one (ME8)."""
    return len(body)


def check_macro(name: str, icon: str, body: str) -> str | None:
    """Why a macro with this name, icon and body can't be written, or None. The name must already be cut."""
    if not name:
        return "a macro needs a name"
    if body_length(body) > BODY_LIMIT:
        return f"the macro would be {body_length(body)} characters, over the {BODY_LIMIT} a macro holds"
    try:  # the file layout's own rules, once (core.macrofile)
        apply_macro_changes(b"", _EMPTY, [MacroChange("add", _PROBE_ID, name, icon, body)])
    except ValueError as exc:
        return str(exc)
    return None


def _key(macro_id: str) -> str:
    return macro_id.upper()


def effective_macros(staged: Staged, mset: MacroSet) -> tuple[Macro, ...]:
    """The set's macros with its staged changes: replaced ones in place (their span is the file's), deleted ones
    gone, added ones last (span (0, 0): not in the file yet)."""
    by_id = {_key(c.id): c for c in staged.changes.get(mset.path, ())}
    out: list[Macro] = []
    for macro in mset.parsed.macros:
        change = by_id.pop(_key(macro.id), None)
        if change is None:
            out.append(macro)
        elif change.kind == "replace":
            out.append(replace(macro, name=change.name, icon=change.icon, body=change.body))
    out.extend(Macro(c.id, c.name, c.icon, c.body, (0, 0)) for c in by_id.values() if c.kind == "add")
    return tuple(out)


def free_slots(staged: Staged, mset: MacroSet) -> int:
    return max(0, mset.limit - len(effective_macros(staged, mset)))


def _writable(mset: MacroSet) -> None:
    if mset.read_only:
        raise ValueError(f"{mset.label}: read-only ({mset.parsed.problem})")


def _find(staged: Staged, mset: MacroSet, macro_id: str) -> Macro:
    for macro in effective_macros(staged, mset):
        if _key(macro.id) == _key(macro_id):
            return macro
    raise ValueError(f"{mset.label}: no macro {macro_id}")


def _put(staged: Staged, mset: MacroSet, change: MacroChange) -> None:
    """Fold `change` into the set's staged list (one change per id)."""
    changes = staged.changes.setdefault(mset.path, [])
    at = next((i for i, c in enumerate(changes) if _key(c.id) == _key(change.id)), None)
    previous = changes[at] if at is not None else None
    original = next((m for m in mset.parsed.macros if _key(m.id) == _key(change.id)), None)
    if previous is not None and previous.kind == "add":
        change = replace(change, kind="add") if change.kind == "replace" else None
    elif (change.kind == "replace" and original is not None
          and (change.name, change.icon, change.body) == (original.name, original.icon, original.body)):
        change = None  # back to the file's own text
    if at is None:
        if change is not None:
            changes.append(change)
    elif change is None:
        del changes[at]
    else:
        changes[at] = change
    if not changes:
        del staged.changes[mset.path]


def _next_id(staged: Staged, mset: MacroSet) -> str:
    known = [*mset.parsed.macros,
             *(Macro(c.id, "", "", "", (0, 0)) for c in staged.changes.get(mset.path, ()) if c.kind == "add")]
    return next_macro_id(MacroFile(tuple(known), mset.parsed.newline, True, None), mset.scope)


def _add(staged: Staged, mset: MacroSet, name: str, icon: str, body: str) -> str:
    new_id = _next_id(staged, mset)
    _put(staged, mset, MacroChange("add", new_id, name, icon, body))
    return new_id


def stage_new(staged: Staged, mset: MacroSet, *, name: str, body: str, icon: str = ICON_DEFAULT) -> str:
    """Stage a new macro; returns its id. Raises ValueError on a read-only or full set, or a macro the file can't
    hold."""
    _writable(mset)
    if not free_slots(staged, mset):
        raise ValueError(f"{mset.label}: no free macro slot ({mset.limit}/{mset.limit})")
    name = cut_name(name)
    problem = check_macro(name, icon, body)
    if problem:
        raise ValueError(f"{mset.label}: {problem}")
    return _add(staged, mset, name, icon, body)


def stage_edit(staged: Staged, mset: MacroSet, macro_id: str, *, name: str, icon: str, body: str) -> None:
    """Stage new text for a macro, keeping its id (ME6). A new name is cut to NAME_LIMIT; the macro's own name, even
    one the file holds over the limit, is kept as it is (ME13). Raises ValueError on a read-only set, an id it lacks
    (or already deleted), or a macro the file can't hold."""
    _writable(mset)
    macro = _find(staged, mset, macro_id)
    if name != macro.name:
        name = cut_name(name)
    problem = check_macro(name, icon, body)
    if problem:
        raise ValueError(f"{mset.label}: {problem}")
    _put(staged, mset, MacroChange("replace", macro.id, name, icon, body))


def stage_delete(staged: Staged, mset: MacroSet, macro_id: str) -> None:
    """Stage a macro's removal (an added one is just dropped). Raises ValueError on a read-only set or an id it
    lacks."""
    _writable(mset)
    macro = _find(staged, mset, macro_id)
    _put(staged, mset, MacroChange("delete", macro.id))


def rename_for_clash(name: str, taken: Collection[str]) -> str:
    """`Name 2` (then 3, ...), the name cut so the whole fits NAME_LIMIT, the first one not in `taken`."""
    number = 2
    while True:
        suffix = f" {number}"
        candidate = f"{cut_name(name)[:NAME_LIMIT - len(suffix)].rstrip()}{suffix}"
        if candidate not in taken:
            return candidate
        number += 1


def stage_paste(staged: Staged, macros: Sequence[Macro], target: MacroSet,
                on_clash: Callable[[Macro, Macro], ClashChoice]) -> list[str]:
    """Stage `macros` (from any set, any flavor: ME5) into `target`, in order. A macro whose cut name a target macro's
    cut name matches is a clash: on_clash(pasted, existing) says skip, rename (rename_for_clash, a new macro) or
    overwrite (the existing macro's id keeps, its name, icon and body are the pasted one's: ME6). A new macro needs
    a free slot (ME3). Returns one line per macro not pasted (read-only target, no free slot, a macro the file
    can't hold); the rest are staged."""
    refusals: list[str] = []
    for macro in macros:
        why = _paste_one(staged, macro, target, on_clash)
        if why is not None:
            refusals.append(f"{target.label}: {why}; {macro.name} was not pasted.")
    return refusals


def _paste_one(staged: Staged, macro: Macro, target: MacroSet,
               on_clash: Callable[[Macro, Macro], ClashChoice]) -> str | None:
    """Stage one pasted macro; returns why it was not pasted (None: staged or skipped)."""
    if target.read_only:
        return f"read-only ({target.parsed.problem})"
    name = cut_name(macro.name)
    current = effective_macros(staged, target)
    clash = next((m for m in current if cut_name(m.name) == name), None)
    if clash is not None:
        choice = on_clash(macro, clash)
        if choice == "skip":
            return None
        if choice == "overwrite":
            problem = check_macro(name, macro.icon, macro.body)
            if problem is None:
                _put(staged, target, MacroChange("replace", clash.id, name, macro.icon, macro.body))
            return problem
        name = rename_for_clash(name, {cut_name(m.name) for m in current})
    if len(current) >= target.limit:
        return f"no free macro slot ({len(current)}/{target.limit})"
    problem = check_macro(name, macro.icon, macro.body)
    if problem is None:
        _add(staged, target, name, macro.icon, macro.body)
    return problem


@dataclass(frozen=True)
class PasteClash:
    """A pasted macro whose (cut) name a macro of the target already has, and what is done about it."""
    target: MacroSet
    pasted: Macro
    existing: Macro
    choice: ClashChoice


@dataclass
class PastePreview:
    """What a paste would do (ME4): `staged`, a copy of the review's staging with the paste in it; every clash met
    with the choice it got; one refusal line per macro not pasted (stage_paste's)."""
    staged: Staged
    clashes: list[PasteClash]
    refusals: list[str]


def copy_staged(staged: Staged) -> Staged:
    """A copy of `staged` that can be changed without touching it."""
    return Staged({path: list(changes) for path, changes in staged.changes.items()})


def clash_key(target: MacroSet, pasted: Macro) -> tuple[Path, str]:
    """How a clash's choice is looked up: the target set and the pasted macro's cut name."""
    return target.path, cut_name(pasted.name)


def preview_paste(staged: Staged, macros: Sequence[Macro], targets: Sequence[MacroSet],
                  choices: Mapping[tuple[Path, str], ClashChoice], default: ClashChoice = "skip") -> PastePreview:
    """Paste `macros` into each of `targets` in order on a copy of `staged`: a clash takes its choice from `choices`
    (clash_key), else `default`. The review shows the clashes and refusals and, once the user agrees, keeps the
    copy as its staging; `staged` itself is never changed."""
    preview = PastePreview(copy_staged(staged), [], [])
    for target in targets:
        def on_clash(pasted: Macro, existing: Macro, target: MacroSet = target) -> ClashChoice:
            choice = choices.get(clash_key(target, pasted), default)
            preview.clashes.append(PasteClash(target, pasted, existing, choice))
            return choice
        preview.refusals += stage_paste(preview.staged, macros, target, on_clash)
    return preview


def _replaced(body: str, find: str, new: str, case: bool) -> tuple[str, int]:
    if case:
        return body.replace(find, new), body.count(find)
    return re.subn(re.escape(find), lambda _match: new, body, flags=re.IGNORECASE)


def preview_replace(staged: Staged, picks: Sequence[tuple[MacroSet, Macro]], find: str, new: str, *,
                    case: bool) -> list[ReplaceRow]:
    """What Replace text would do to the bodies of the picked macros, as staged so far (ME7): one row per macro
    with at least one match, in pick order (a macro picked twice counts once). A row whose result is over
    BODY_LIMIT, can't be written, or is in a read-only set carries its refusal. Stages nothing."""
    rows: list[ReplaceRow] = []
    seen: set[tuple[Path, str]] = set()
    if not find:
        return rows
    for mset, picked in picks:
        if (mset.path, _key(picked.id)) in seen:
            continue
        seen.add((mset.path, _key(picked.id)))
        try:
            macro = _find(staged, mset, picked.id)
        except ValueError:
            continue  # deleted since it was picked
        after, count = _replaced(macro.body, find, new, case)
        if not count:
            continue
        refusal = (f"read-only ({mset.parsed.problem})" if mset.read_only
                   else check_macro(macro.name, macro.icon, after))
        rows.append(ReplaceRow(mset, macro, macro.body, after, count, refusal))
    return rows


def stage_replace_text(staged: Staged, picks: Sequence[tuple[MacroSet, Macro]], find: str, new: str, *,
                       case: bool) -> int:
    """Stage preview_replace's rows that carry no refusal; returns how many macros were changed."""
    rows = [row for row in preview_replace(staged, picks, find, new, case=case) if row.refusal is None]
    for row in rows:
        stage_edit(staged, row.mset, row.macro.id, name=row.macro.name, icon=row.macro.icon, body=row.after)
    return len(rows)


def _line(change: MacroChange, mset: MacroSet) -> str:
    if change.kind == "delete":
        name = next((m.name for m in mset.parsed.macros if _key(m.id) == _key(change.id)), change.id)
        return f'{MACRO_FILE}: deleted "{name}"'
    verb = "added" if change.kind == "add" else "changed"
    return f'{MACRO_FILE}: {verb} "{change.name}"'


def build_changes(staged: Staged, sets: Sequence[MacroSet]) -> list[ClientChange]:
    """One ClientChange per set (in `sets` order) whose staged changes alter its bytes: the file spliced by
    apply_macro_changes (every macro not changed keeps its bytes, ME13), the SHA-256 the scan read (None: the run
    creates the file) and one line per change. Raises ValueError for a staged set not in `sets`."""
    by_path = {mset.path: mset for mset in sets}
    missing = [path for path in staged.changes if path not in by_path]
    if missing:
        raise ValueError(f"staged changes for a set that was not passed: {', '.join(map(str, missing))}")
    out: list[ClientChange] = []
    for mset in sets:
        changes = staged.changes.get(mset.path)
        if not changes:
            continue
        new = apply_macro_changes(mset.data, mset.parsed, changes)
        if new == mset.data and mset.sha256 is not None:
            continue
        out.append(ClientChange(mset.path, new, mset.sha256, tuple(_line(c, mset) for c in changes)))
    return out
