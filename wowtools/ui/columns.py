"""A tree node's data in aligned columns, the suite standard (feedback round 2 spec R4, STD-7.28): wherever a node
shows more than one piece of data (a name plus a reason, size, age, date, value, status...), each piece is a column
as wide as its widest cell among the sibling rows it aligns with (`natural_widths`), up to the column's cap; when
the pane is narrow `fit_columns` gives the free-text columns way first and drops whole columns last, so a row fits
while its name keeps its minimum (narrower still, the name keeps its minimum and the row scrolls sideways: user
decision U1, so sibling names stay apart); `column_text` builds the row's Rich text, long cells cut with `…`;
`fit_keeping_count` fits a row with a leaf count and `group_text` a group's name and count, the count always kept
(STD-7.27: the name gives way, never below its minimum, and the row scrolls past the pane instead). A tool
keeps its cells (a report function) and its `ColumnLayout`; the screen, which knows the pane's width, fits and
draws. Pure functions over Rich, no Textual import: one implementation for every tool (moved out of the Config
Editor, where the CVar rows started it, feedback round 1 CF2)."""
from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from typing import NamedTuple

from rich.cells import cell_len
from rich.text import Text

from wowtools.ui.counts import COUNT_GAP, COUNT_STYLE

__all__ = ["ELLIPSIS", "GROUP_NAME_MINIMUM", "NARROW_GAP", "WIDE_GAP", "ColumnLayout", "column_text", "cut_middle",
           "cut_to_room", "fit_columns", "fit_keeping_count", "group_text", "natural_widths"]

ELLIPSIS = "…"
WIDE_GAP, NARROW_GAP = 2, 1  # spaces between two columns: two when everything fits so, else one
GROUP_NAME_MINIMUM = 4  # a group's name (a name and its count) is never cut below this; its line scrolls past (U1)


class ColumnLayout(NamedTuple):
    """How a tool's columns fit a narrow pane, one entry per column. `caps`: the widest a column grows (None: as
    wide as its widest cell). `minimums`: the narrowest a column that gives way is cut to. `shrink`: the columns
    that give way, in stages (within a stage the one furthest over its minimum first; the free-text ones: a reason,
    a value, then the name); a column in no stage (a status, a size, an age) is never cut, only dropped. `drop`: the
    columns dropped whole, one more each step, when the minimums still do not fit; past them every column but the
    first goes, and the first (the name, never dropped) is cut to the room, never below its minimum (U1)."""
    caps: tuple[int | None, ...]
    minimums: tuple[int, ...]
    shrink: tuple[tuple[int, ...], ...] = ((0,),)
    drop: tuple[int, ...] = ()


Cell = str | Text  # a cell is plain text, or Rich text of its own colours (the WTF Cleaner's reasons)


def _cells(cell: Cell) -> int:
    return cell.cell_len if isinstance(cell, Text) else cell_len(cell)


def natural_widths(rows: Iterable[Sequence[Cell]]) -> tuple[int, ...]:
    """Each column's widest cell, in terminal cells, over the sibling rows that align (() for no rows)."""
    return tuple(max(map(_cells, column)) for column in zip(*rows))


def _visible_total(widths: Sequence[int], gap: int) -> int:
    shown = [width for width in widths if width]
    return sum(shown) + gap * max(0, len(shown) - 1)


def fit_columns(natural: Sequence[int], room: int | None, layout: ColumnLayout) -> tuple[tuple[int, ...], int]:
    """The column widths and the gap between them: each column's widest cell (`natural`) up to its cap, two spaces
    apart when that fits `room` (the cells the row may take; None: no limit). Otherwise the gap drops to one space
    and the `shrink` stages give way down to their minimums; still too wide, the `drop` columns go one more each
    step (the others take room back), then every column but the first, which is cut to the room but never below
    its minimum (narrower than that the row is wider than the room and scrolls sideways, user decision U1; at least
    one cell). A width of 0 is a column not shown (an empty column takes no gap)."""
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
    widths[0] = max(1, min(capped[0], layout.minimums[0]), min(widths[0], room))  # the name alone, cut to the room
    return tuple(widths), NARROW_GAP


def fit_keeping_count(natural: Sequence[int], room: int | None, layout: ColumnLayout, *,
                      count: int = 1) -> tuple[tuple[int, ...], int]:
    """fit_columns for a row with a leaf count in column `count` (STD-7.27): the row as fit_columns fits it while
    that keeps the count; where it would drop the count, the name and the count alone, the name cut (in its middle)
    so the count fits, never below its minimum (narrower than that the row scrolls sideways past the pane, U1, its
    count kept). The name never narrows as the room grows."""
    widths, gap = fit_columns(natural, room, layout)
    if room is None or not natural[count] or widths[count]:
        return widths, gap
    name = natural[0] if layout.caps[0] is None else min(natural[0], layout.caps[0])
    shown = [0] * len(natural)
    shown[count] = natural[count] if layout.caps[count] is None else min(natural[count], layout.caps[count])
    shown[0] = max(1, min(name, layout.minimums[0]), min(name, room - NARROW_GAP - shown[count]))
    return tuple(shown), NARROW_GAP


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


def cut_to_room(name: str, room: int | None, *, minimum: int = GROUP_NAME_MINIMUM) -> str:
    """A group's name cut in its middle to `room` cells (None: no limit), never below `minimum` cells: narrower than
    that the row scrolls sideways (user decision U1) rather than every sibling reading `…`."""
    return name if room is None else cut_middle(name, max(room, minimum))


def group_text(name: str, style: str, note: str | None, room: int | None, *, note_style: str = COUNT_STYLE,
               minimum: int = GROUP_NAME_MINIMUM) -> Text:
    """A group's line (a name and its dim count, STD-7.27; not a column row): the name in `style`, then `note` (its
    count, `27 items`, or a note in its place) two spaces after it, the name cut in its middle so the note fits
    `room` (None: no limit) but never below `minimum` cells. Narrower than that the line scrolls sideways past the
    pane with its count kept (user decision U1). `note` None: the name alone, cut to the room."""
    if note is None:
        return Text(cut_to_room(name, room, minimum=minimum), style=style)
    after = f"{COUNT_GAP}{note}"
    if room is not None:
        name = cut_to_room(name, room - cell_len(after), minimum=minimum)
    return Text.assemble((name, style), (after, note_style))


def column_text(cells: Sequence[Cell], widths: Sequence[int], styles: Sequence[str], gap: int = WIDE_GAP, *,
                middle: Collection[int] = ()) -> Text:
    """A row's columns as Rich text: each cell in its style, cut with … to its width (in its middle for a column in
    `middle`, else at its end) and padded to it but the last, `gap` spaces apart; a column of width 0 is left out.
    A Rich-text cell keeps its own colours over its column's style (it is cut at its end). The caller puts the tick mark in front and fits `widths` to the pane (fit_columns)."""
    shown = [(i, cell, width, style) for i, (cell, width, style) in enumerate(zip(cells, widths, styles)) if width]
    text = Text()
    for position, (i, cell, width, style) in enumerate(shown):
        last = position == len(shown) - 1
        if isinstance(cell, Text):
            piece = Text(style=style)
            piece.append_text(cell)
        else:
            piece = Text(cut_middle(cell, width) if i in middle else cell, style=style)
        piece.truncate(width, overflow="ellipsis", pad=not last)
        text.append_text(piece)
        if not last:
            text.append(" " * gap)
    return text
