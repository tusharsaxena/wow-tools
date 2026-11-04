"""The leaf count after a tree node's label, the suite standard (feedback round 2 spec R2, STD-7.27): every node that
has children shows, two spaces after its label and dimmed, how many leaf-level items sit below it at any depth, as
the tree currently shows them (after the search and the tool's own Show filters): `Retail  27 items`,
`Aellâ  1 item`. The WTF Cleaner's look, now one implementation. Each tool decides what its leaf is (and documents
it in its internals doc) and counts it from its model, so a node whose children load on expand counts them before
it is opened. Pure Rich, no Textual import."""
from __future__ import annotations

from rich.text import Text

from wowtools.core.text import plural

__all__ = ["COUNT_GAP", "COUNT_STYLE", "count_text", "with_count"]

COUNT_STYLE = "dim"
COUNT_GAP = "  "


def count_text(n: int) -> str:
    """`1 item`, `27 items`."""
    return plural(n, "item")


def with_count(label: Text | str, n: int) -> Text:
    """A copy of `label` with the dim count after it (the label itself is left as it was)."""
    text = Text(label) if isinstance(label, str) else label.copy()
    text.append(f"{COUNT_GAP}{count_text(n)}", COUNT_STYLE)
    return text
