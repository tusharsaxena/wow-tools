"""The Macro Editor's optimizer (config tools spec ME10): rewrites that are the same in game, so a macro fits in 255
characters. UI-free.

Only rules listed in wowtools/kb/optimizer_rules.json with `automatic` true are applied, in RULES' order; each
rewrite carries the rule's reason and source. Rules work on the tokens of syntax.py, so they only touch condition
blocks, `;` separators and `#showtooltip` lines of commands that read conditions: a spell or item name, chat text
or Lua code is never changed.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from wowtools.core.kb import RuleInfo, load_optimizer_rules
from wowtools.tools.macro_editor.syntax import Line, lines

__all__ = ["RULES", "Rewrite", "optimize"]

SAME_AS_DEFAULT = ("/cast", "/use")  # the commands whose first spell #showtooltip shows by default


@dataclass(frozen=True)
class Rewrite:
    rule: str
    before: str   # the whole line before
    after: str    # and after
    reason: str
    source: str


def _splice(text: str, base: int, edits: list[tuple[int, int, str]]) -> str:
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start - base] + new + text[end - base:]
    return text


def _target_to_at(line: Line, _all: list[Line], _index: int) -> str:
    edits = [(t.start, t.end, "@" + t.text.split("=", 1)[1].lstrip())
             for clause in line.clauses for _, items in clause.blocks for t in items
             if t.kind == "unit" and t.text.lower().startswith("target=")]
    return _splice(line.text, line.start, edits)


def _duplicate_conditions(line: Line, _all: list[Line], _index: int) -> str:
    edits = []
    for clause in line.clauses:
        for block, _items in clause.blocks:
            closed = block.text.endswith("]")
            segments = (block.text[1:-1] if closed else block.text[1:]).split(",")
            seen: set[str] = set()
            keep = []
            for segment in segments:
                word = segment.strip()
                if word.lower().startswith(("@", "target=")):
                    keep.append(segment)  # never drop a unit: which of several wins is not ours to guess
                    continue
                if word and word in seen:
                    continue
                seen.add(word)
                keep.append(segment)
            if len(keep) < len(segments):
                edits.append((block.start, block.end, "[" + ",".join(keep) + ("]" if closed else "")))
    return _splice(line.text, line.start, edits)


def _strip_spaces(line: Line, _all: list[Line], _index: int) -> str:
    if line.head is None or line.head.kind != "command":
        return line.text
    edits = []
    for n, clause in enumerate(line.clauses):
        if clause.blocks:
            first, last = clause.blocks[0][0], clause.blocks[-1][0]
            joined = "".join("[" + ",".join(t.text for t in items) + ("]" if block.text.endswith("]") else "")
                             for block, items in clause.blocks)
            start = first.start
            if n > 0:  # the spaces after the ; before this clause
                start = line.start + line.text.rfind(";", 0, first.start - line.start) + 1
            edits.append((start, last.end, joined))
        elif n > 0 and clause.value is not None:
            start = line.start + line.text.rfind(";", 0, clause.value.start - line.start) + 1
            edits.append((start, clause.value.start, ""))
    return _splice(line.text, line.start, edits)


def _showtooltip_same(line: Line, all_lines: list[Line], index: int) -> str:
    if line.head is None or line.head.text != "#showtooltip" or len(line.clauses) != 1:
        return line.text
    clause = line.clauses[0]
    if clause.blocks or clause.value is None:
        return line.text
    first = next((other for other in all_lines[index + 1:]
                  if other.head is not None and other.head.kind == "command"), None)
    if first is None or first.head.text.lower() not in SAME_AS_DEFAULT or not first.options:
        return line.text
    if any(c.value is None or c.value.text != clause.value.text for c in first.clauses):
        return line.text
    last = first.clauses[-1]
    if last.blocks and not any(not items for _, items in last.blocks):
        return line.text  # the last clause can fail, so the default could show nothing
    return line.text[:line.head.end - line.start]


RULES: dict[str, Callable[[Line, list[Line], int], str] | None] = {
    "target_to_at": _target_to_at,
    "duplicate_conditions": _duplicate_conditions,
    "strip_spaces": _strip_spaces,
    "showtooltip_same": _showtooltip_same,
    "cast_to_use": None,  # in the KB for the record (automatic false): /cast and /use differ on a name both share
}


def optimize(body: str, *, rules: Mapping[str, RuleInfo] | None = None) -> tuple[str, list[Rewrite]]:
    """The body with every applicable rewrite made, and the rewrites in order (rule, then line)."""
    rules = load_optimizer_rules() if rules is None else rules
    rewrites: list[Rewrite] = []
    for rule_id, fn in RULES.items():
        info = rules.get(rule_id)
        if fn is None or info is None or not info.automatic:
            continue
        parsed = lines(body)
        out = []
        for index, line in enumerate(parsed):
            new = fn(line, parsed, index)
            if new != line.text:
                rewrites.append(Rewrite(rule_id, line.text, new, info.reason, info.source))
            out.append(new)
        body = "\n".join(out)
    return body, rewrites
