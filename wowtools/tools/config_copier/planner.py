"""Plan a copy from one source character to its targets, pair by pair (config tools spec CC2-CC7). UI-free; reads
files, never writes one.

Every (target, file) pair gets a status: `new` (the target has no such file), `replace`, `unchanged` (the target
already holds exactly what it would get), `no-source` (the source has no such file: nothing is copied and the
target's file is left alone) or `unreadable` (the source's or the target's file could not be read: never copied).
Plain files are copied byte for byte (CC6), an empty one as empty; config-cache.wtf is merged (CC5). A
macros-cache.txt replacing a target's file that holds macros, or that the reader can't parse, carries the CC7
warning.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from wowtools.core.events import log_event
from wowtools.core.install import Character
from wowtools.core.macrofile import parse_macros
from wowtools.tools.config_copier.merge import merge_config
from wowtools.tools.config_copier.model import CONFIG_FILE, COPY_FILES, MACRO_FILE, MACRO_WARNING, PairPlan

__all__ = ["plan_copy"]


class _Unreadable(Exception):
    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path.name} could not be read: {reason}")
        self.path = path
        self.reason = reason


def _read(path: Path) -> bytes | None:
    """The file's bytes; None when there is no such entry. Raises _Unreadable for anything else (a folder by that
    name, no permission, an I/O error), logged once per path."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        log_event("copier.file_unreadable", path=str(path), reason=reason)
        raise _Unreadable(path, reason) from None


def _has_macros(data: bytes) -> bool:
    parsed = parse_macros(data)
    return bool(parsed.macros) or (not parsed.known_layout and bool(data.strip()))


def _pair(target: Character, name: str, source: bytes | None | _Unreadable) -> PairPlan:
    if source is None:
        return PairPlan(target, name, "no-source", None, None, None)
    if isinstance(source, _Unreadable):
        return PairPlan(target, name, "unreadable", None, None, None, problem=str(source))
    try:
        old = _read(target.path / name)
    except _Unreadable as exc:
        return PairPlan(target, name, "unreadable", None, None, None, problem=str(exc))
    new = merge_config(source, old) if name == CONFIG_FILE else source
    if old is None:
        return PairPlan(target, name, "new", new, None, None)
    old_sha = hashlib.sha256(old).hexdigest()
    if new == old:
        return PairPlan(target, name, "unchanged", new, old, old_sha)
    warnings = (MACRO_WARNING,) if name == MACRO_FILE and _has_macros(old) else ()
    return PairPlan(target, name, "replace", new, old, old_sha, warnings)


def plan_copy(source: Character, targets: Sequence[Character], names: Sequence[str]) -> list[PairPlan]:
    """One PairPlan per target and file: targets in the order given, files in COPY_FILES' order. Raises ValueError
    for a name not in COPY_FILES (X4) or the source among the targets (CC2)."""
    unknown = [name for name in names if name not in COPY_FILES]
    if unknown:
        raise ValueError(f"not a file the Config Copier copies: {', '.join(unknown)}")
    if any(target.path == source.path for target in targets):
        raise ValueError("the source character can't be a target")
    ordered = [name for name in COPY_FILES if name in set(names)]
    sources: dict[str, bytes | None | _Unreadable] = {}
    for name in ordered:
        try:
            sources[name] = _read(source.path / name)
        except _Unreadable as exc:
            sources[name] = exc
    plans = [_pair(target, name, sources[name]) for target in targets for name in ordered]
    log_event("copier.planned", source=f"{source.account}/{source.label}", targets=len(targets), files=ordered,
              counts=dict(sorted(Counter(plan.status for plan in plans).items())))
    return plans
