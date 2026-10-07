"""The blacklist's (flavor folder, addon) pairs (spec B1), shared by the tools that keep one (the Ace3 Profile Manager,
the WTF Cleaner): parsed from and written to a tool's `blacklist` setting as `flavor:Addon, ...`, matched ignoring
case, a flavor "*" (a bare name) standing for every flavor. Each tool keeps its own list and decides what being
listed means; the tree's `b` key is ui/review.py's BlacklistAction. UI-free."""
from __future__ import annotations

import re
from collections.abc import Iterable

__all__ = ["WILDCARD", "Pair", "format_blacklist", "is_blacklisted", "parse_blacklist", "toggle_pair", "unique_pairs"]

_SPLIT = re.compile(r"[,\r\n]+")
WILDCARD = "*"  # the flavor of a bare (legacy) blacklist name: every flavor
Pair = tuple[str, str]  # (flavor folder, addon)


def _pair_order(pair: Pair) -> tuple[str, str]:
    return pair[1].casefold(), pair[0].casefold()


def unique_pairs(pairs: Iterable[Pair]) -> list[Pair]:
    """Duplicates (ignoring case) keep the first spelling; sorted by addon, then flavor, ignoring case."""
    seen: dict[tuple[str, str], Pair] = {}
    for flavor, addon in pairs:
        seen.setdefault((flavor.casefold(), addon.casefold()), (flavor, addon))
    return sorted(seen.values(), key=_pair_order)


def parse_blacklist(text: str) -> list[Pair]:
    """`flavor:addon` entries separated by commas or new lines (`_retail_:ElvUI, Questie`). A bare name (the first
    build's form) becomes ("*", name): every flavor. Blanks dropped, duplicates (ignoring case) keep the first
    spelling."""
    pairs: list[Pair] = []
    for part in _SPLIT.split(text or ""):
        flavor, sep, addon = part.partition(":")
        flavor, addon = (flavor.strip(), addon.strip()) if sep else (WILDCARD, flavor.strip())
        if addon and flavor:
            pairs.append((flavor, addon))
    return unique_pairs(pairs)


def format_blacklist(pairs: Iterable[Pair]) -> str:
    """`flavor:addon, ...`, sorted; a wildcard pair stays a bare name."""
    return ", ".join(addon if flavor == WILDCARD else f"{flavor}:{addon}" for flavor, addon in unique_pairs(pairs))


def is_blacklisted(pairs: Iterable[Pair], flavor: str, addon: str) -> bool:
    """(flavor folder, addon) is on the blacklist, ignoring case; "*" matches every flavor."""
    wanted_flavor, wanted_addon = flavor.casefold(), addon.casefold()
    return any(name.casefold() == wanted_addon and (where == WILDCARD or where.casefold() == wanted_flavor)
               for where, name in pairs)


def toggle_pair(pairs: Iterable[Pair], flavor: str, addon: str, folders: Iterable[str]) -> tuple[list[Pair], bool]:
    """Blacklist (flavor, addon), or take it off when it is on. Taking it off drops its pair and turns a wildcard
    for that addon into explicit pairs for the other flavor folders in `folders`, so they stay blacklisted.
    Returns the new list and whether the pair is now blacklisted."""
    pairs = list(pairs)
    if not is_blacklisted(pairs, flavor, addon):
        return unique_pairs([*pairs, (flavor, addon)]), True
    name, here = addon.casefold(), flavor.casefold()
    kept: list[Pair] = []
    for where, other in pairs:
        if other.casefold() != name:
            kept.append((where, other))
        elif where == WILDCARD:
            kept += [(folder, other) for folder in folders if folder.casefold() != here]
        elif where.casefold() != here:
            kept.append((where, other))
    return unique_pairs(kept), False
