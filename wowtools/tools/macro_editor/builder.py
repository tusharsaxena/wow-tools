"""The conditional builder's two-way reading of one [...] block (config tools spec ME9). UI-free.

`read_block` fills the builder from a block: its target (the unit it names, `target=x` read as `@x`), its unit
reaction (help or harm, none for either) and the states the builder lists (the reference's `builder` section), each
matched without regard to case. `write_block` writes the choices back: unchanged choices give the block exactly as
written; otherwise each item keeps its place and its spelling, an item the builder unticked is dropped, a new target
or reaction goes first and new states go last. Items the builder doesn't show (`spec:2`, `@party1`'s neighbours,
`mod:shift/ctrl`) are always kept.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from wowtools.tools.macro_editor.syntax import Token, tokenize

__all__ = ["REACTIONS", "BlockChoice", "block_at", "read_block", "write_block"]

REACTIONS = ("help", "harm")


@dataclass(frozen=True)
class BlockChoice:
    target: str | None             # "@mouseover"; None: the block names no unit
    unit: str | None               # "help", "harm"; None: either
    states: tuple[str, ...]        # the builder states the block has, in the builder's spelling, block order
    items: tuple[str, ...]         # the block's items as written


def _items(block: str) -> list[str]:
    inner = block.strip().removeprefix("[").removesuffix("]")
    return [item.strip() for item in inner.split(",") if item.strip()]


def _is_unit(item: str) -> bool:
    return item.startswith("@") or item.lower().startswith("target=")


def _unit_of(item: str) -> str:
    """`@Focus`, `target=focus` -> "@focus"."""
    return "@" + (item[1:] if item.startswith("@") else item.split("=", 1)[1]).strip().lower()


def _states(builder: Mapping[str, Sequence[str]]) -> dict[str, str]:
    return {state.lower(): state for state in builder.get("states", ())}


def read_block(block: str, builder: Mapping[str, Sequence[str]]) -> BlockChoice:
    items = _items(block)
    units = [item for item in items if _is_unit(item)]
    target = _unit_of(units[-1]) if units else None
    unit = next((item.lower() for item in items if item.lower() in REACTIONS), None)
    known = _states(builder)
    states = tuple(dict.fromkeys(known[item.lower()] for item in items if item.lower() in known))
    return BlockChoice(target, unit, states, tuple(items))


def write_block(original: BlockChoice | None, *, target: str | None, unit: str | None, states: Collection[str],
                builder: Mapping[str, Sequence[str]], block: str | None = None) -> str:
    """The block for these choices. `original` (and `block`, its text) the block being rewritten, None for a new
    one."""
    known = _states(builder)
    wanted = [known.get(s.lower(), s) for s in states]
    if (original is not None and block is not None and (target, unit) == (original.target, original.unit)
            and set(wanted) == set(original.states)):
        return block
    items = list(original.items) if original is not None else []
    last_unit = max((i for i, item in enumerate(items) if _is_unit(item)), default=None)
    out: list[str] = []
    placed_target = placed_unit = False
    kept_states: set[str] = set()
    for index, item in enumerate(items):
        low = item.lower()
        if index == last_unit:
            if target is not None:
                out.append(item if _unit_of(item) == target else target)
                placed_target = True
        elif low in REACTIONS:
            if unit is not None and not placed_unit:
                out.append(item if low == unit else unit)
                placed_unit = True
        elif low in known:
            if known[low] in wanted and known[low] not in kept_states:
                out.append(item)
                kept_states.add(known[low])
        else:
            out.append(item)
    if unit is not None and not placed_unit:
        out.insert(0, unit)
    if target is not None and not placed_target:
        out.insert(0, target)
    out += [state for state in known.values() if state in wanted and state not in kept_states]
    return "[" + ",".join(out) + "]"


def block_at(body: str, offset: int) -> Token | None:
    """The condition block under the cursor (on its brackets or anywhere inside), None outside one."""
    return next((t for t in tokenize(body) if t.kind == "condition_block" and t.start <= offset <= t.end), None)
