"""The Config Copier's plan of one (target, file) pair (config tools spec CC3, CC4, CC7). UI-free."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from wowtools.core.install import Character

__all__ = ["CONFIG_FILE", "COPY_FILES", "MACRO_FILE", "MACRO_WARNING", "PairPlan", "Status"]

# CC3: the only files offered, in this order. Nothing else is ever read or written as a client file (X4); never
# cache.md5 or a .old file (V2).
COPY_FILES = ("macros-cache.txt", "AddOns.txt", "chat-cache.txt", "config-cache.wtf", "layout-local.txt")
MACRO_FILE = "macros-cache.txt"
CONFIG_FILE = "config-cache.wtf"  # merged, not copied (CC5)
MACRO_WARNING = "Action bar buttons that use macros may need placing again."  # CC7

Status = Literal["new", "replace", "unchanged", "no-source", "unreadable"]


@dataclass(frozen=True)
class PairPlan:
    """What copying `name` onto `target` does. `new` is the bytes the target gets (None for no-source and
    unreadable); `old` and `old_sha256` the target's file as read (None when it has none). `warnings` are shown on
    the review and in the confirm popup (CC7); `problem` says why an unreadable pair can't be copied."""
    target: Character
    name: str
    status: Status
    new: bytes | None
    old: bytes | None
    old_sha256: str | None
    warnings: tuple[str, ...] = ()
    problem: str | None = None
