"""Plain-text helpers every tool's report module uses: counted nouns, file sizes and Listed (one entry of a list a
popup shows collapsed). UI-free; a flavor's display name is install.flavor_name()."""
from __future__ import annotations

from typing import NamedTuple

MISSING = "—"  # a size that is not known
_UNITS = ("KB", "MB", "GB", "TB")


class Listed(NamedTuple):
    """One entry of a list that can grow (warnings, notes, refusals, skipped items), as a popup shows it behind one
    counted tree row (ui.dialogs.CountedTree, STD-7.26): the message (a sentence, the same for every entry it
    concerns, so it is shown once), where (flavor · account; "" for none) and the item (an addon, a file; "" for
    none)."""
    message: str
    where: str = ""
    item: str = ""


def plural(n: int, word: str, words: str | None = None) -> str:
    """"1 file", "2 files"; `words` for an irregular plural (plural(2, "copy", "copies"))."""
    return f"{n} {word if n == 1 else (words or word + 's')}"


def human_size(n: int | None) -> str:
    """A byte count as "512 B", "1.5 KB", ... up to TB (one decimal above bytes); MISSING for None."""
    if n is None:
        return MISSING
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for unit in _UNITS:
        value /= 1024
        if value < 1024 or unit == _UNITS[-1]:
            break
    return f"{value:.1f} {unit}"
