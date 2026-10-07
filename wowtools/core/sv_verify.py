"""Checks shared by the tools that rewrite SavedVariables, run on the re-parsed edited file before it is written
(Ace3 spec §8.2, SV Browser spec D19): the same assignments in the same order, the text between them unchanged, an
assignment nothing was planned for byte-identical, and every byte outside the edited spans unchanged. UI-free."""
from __future__ import annotations

from collections.abc import Callable, Collection, Sequence

from wowtools.core.luasv import Assignment, Chunk

Span = tuple[int, int]
NOT_THE_SAME = "the edited file does not hold the same SavedVariables"
TEXT_BETWEEN = "text between the SavedVariables changed"


def gaps(data: bytes, chunk: Chunk) -> list[bytes]:
    """The bytes between and around the top-level assignments (blank lines, comments)."""
    out, pos = [], 0
    for item in chunk.assignments:
        out.append(data[pos:item.start])
        pos = item.end
    out.append(data[pos:])
    return out


def check_assignments(old: bytes, old_chunk: Chunk, new: bytes, new_chunk: Chunk, planned: Collection[str], *,
                      on_planned: Callable[[Assignment, Assignment], list[str]] | None = None) -> list[str]:
    """Problems with the edited file's top level: other assignment names or order (only that problem, the rest
    cannot be compared), changed text between them, or a changed assignment not in `planned`. on_planned(before,
    after) checks each planned one, its problems kept in assignment order."""
    if [a.name for a in new_chunk.assignments] != [a.name for a in old_chunk.assignments]:
        return [NOT_THE_SAME]
    problems: list[str] = []
    if gaps(new, new_chunk) != gaps(old, old_chunk):
        problems.append(TEXT_BETWEEN)
    for before, after in zip(old_chunk.assignments, new_chunk.assignments):
        if before.name in planned:
            if on_planned is not None:
                problems.extend(on_planned(before, after))
            continue
        if old[before.start:before.end] != new[after.start:after.end]:
            problems.append(f"{before.name} changed but nothing was planned for it")
    return problems


def rest_outside(data: bytes, start: int, end: int, cuts: Sequence[Span]) -> bytes:
    """data[start:end] with the (sorted, non-overlapping) cuts taken out, the pieces joined by a NUL so that moving
    bytes across a cut never compares equal."""
    out, pos = [], start
    for cut_start, cut_end in sorted(cuts):
        out.append(data[pos:cut_start])
        pos = cut_end
    out.append(data[pos:end])
    return b"\0".join(out)


def same_outside(old: bytes, old_spans: Sequence[Span], new: bytes, new_spans: Sequence[Span]) -> bool:
    """True when every byte outside the edited spans is unchanged: old_spans are the edited ranges of the old file,
    new_spans the ranges that replaced them in the new one (same count, same order)."""
    if len(old_spans) != len(new_spans):
        return False
    return rest_outside(old, 0, len(old), old_spans) == rest_outside(new, 0, len(new), new_spans)
