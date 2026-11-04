"""A tree node's data in aligned columns, the suite standard (feedback round 2 spec R4, STD-7.28): wherever a node
shows more than one piece of data (a name plus a reason, size, age, date, value, status...), each piece is a column
as wide as its widest cell among the sibling rows it aligns with (`natural_widths`), up to the column's cap; when
the pane is narrow `fit_columns` gives the free-text columns way first and drops whole columns last, so a row always
fits; `column_text` builds the row's Rich text, long cells cut with `…`. A tool keeps its cells (a report function)
and its `ColumnLayout`; the screen, which knows the pane's width, fits and draws. Pure functions over Rich, no
Textual import: one implementation for every tool (moved out of the Config Editor, where the CVar rows started
it, feedback round 1 CF2)."""
from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from typing import NamedTuple

from rich.cells import cell_len
from rich.text import Text

__all__ = ["ELLIPSIS", "NARROW_GAP", "WIDE_GAP", "ColumnLayout", "column_text", "cut_middle", "fit_columns",
           "natural_widths"]

ELLIPSIS = "…"
WIDE_GAP, NARROW_GAP = 2, 1  # spaces between two columns: two when everything fits so, else one


class ColumnLayout(NamedTuple):
    """How a tool's columns fit a narrow pane, one entry per column. `caps`: the widest a column grows (None: as
    wide as its widest cell). `minimums`: the narrowest a column that gives way is cut to. `shrink`: the columns
    that give way, in stages (within a stage the one furthest over its minimum first; the free-text ones: a reason,
    a value, then the name); a column in no stage (a status, a size, an age) is never cut, only dropped. `drop`: the
    columns dropped whole, one more each step, when the minimums still do not fit; past them every column but the
    first goes, and the first (the name, never dropped) is cut to the room."""
    caps: tuple[int | None, ...]
    minimums: tuple[int, ...]
    shrink: tuple[tuple[int, ...], ...] = ((0,),)
    drop: tuple[int, ...] = ()


def natural_widths(rows: Iterable[Sequence[str]]) -> tuple[int, ...]:
    """Each column's widest cell, in terminal cells, over the sibling rows that align (() for no rows)."""
    return tuple(max(map(cell_len, column)) for column in zip(*rows))


def _visible_total(widths: Sequence[int], gap: int) -> int:
    shown = [width for width in widths if width]
    return sum(shown) + gap * max(0, len(shown) - 1)


def fit_columns(natural: Sequence[int], room: int | None, layout: ColumnLayout) -> tuple[tuple[int, ...], int]:
    """The column widths and the gap between them: each column's widest cell (`natural`) up to its cap, two spaces
    apart when that fits `room` (the cells the row may take; None: no limit). Otherwise the gap drops to one space
    and the `shrink` stages give way down to their minimums; still too wide, the `drop` columns go one more each
    step (the others take room back), then every column but the first, which is cut to the room. A width of 0 is a
    column not shown (an empty column takes no gap)."""
    capped = [width if cap is None else min(width, cap) for width, cap in zip(natural, layout.caps)]
    if room is None or _visible_total(capped, WIDE_GAP) <= room:
        return tuple(capped), WIDE_GAP
    steps: list[set[int]] = [set()]
    for column in layout.drop:
        steps.append(steps[-1] | {column})
    steps.append(set(range(1, len(capped))))  # the name alone
    widths = capped
    for dropped in steps:
        widths = [0 if i in dropped else width for i, width in enumerate(capped)]
        excess = _visible_total(widths, NARROW_GAP) - room
        for columns in layout.shrink:
            while excess > 0:
                shrinkable = [i for i in columns if widths[i] > layout.minimums[i]]
                if not shrinkable:
                    break
                widest = max(shrinkable, key=lambda i: widths[i] - layout.minimums[i])
                widths[widest] -= 1
                excess -= 1
        if excess <= 0:
            return tuple(widths), NARROW_GAP
    widths[0] = max(1, min(widths[0], room))  # the name alone, cut to the room
    return tuple(widths), NARROW_GAP


def _take(text: str, cells: int, *, from_end: bool = False) -> str:
    chars = reversed(text) if from_end else iter(text)
    out: list[str] = []
    used = 0
    for char in chars:
        width = cell_len(char)
        if used + width > cells:
            break
        out.append(char)
        used += width
    return "".join(reversed(out) if from_end else out)


def cut_middle(text: str, width: int) -> str:
    """`text` cut to `width` cells in its middle, keeping its start and its end (feedback round 1 FB2r: names that
    share a long start, raidFramesDisplay…, stay apart)."""
    if cell_len(text) <= width:
        return text
    if width <= 1:
        return ELLIPSIS[:max(width, 0)]
    head = width // 2
    return _take(text, head) + ELLIPSIS + _take(text, width - 1 - head, from_end=True)


def column_text(cells: Sequence[str], widths: Sequence[int], styles: Sequence[str], gap: int = WIDE_GAP, *,
                middle: Collection[int] = ()) -> Text:
    """A row's columns as Rich text: each cell in its style, cut with … to its width (in its middle for a column in
    `middle`, else at its end) and padded to it but the last, `gap` spaces apart; a column of width 0 is left out.
    The caller puts the tick mark in front and fits `widths` to the pane (fit_columns)."""
    shown = [(i, cell, width, style) for i, (cell, width, style) in enumerate(zip(cells, widths, styles)) if width]
    text = Text()
    for position, (i, cell, width, style) in enumerate(shown):
        last = position == len(shown) - 1
        piece = Text(cut_middle(cell, width) if i in middle else cell, style=style)
        piece.truncate(width, overflow="ellipsis", pad=not last)
        text.append_text(piece)
        if not last:
            text.append(" " * gap)
    return text
