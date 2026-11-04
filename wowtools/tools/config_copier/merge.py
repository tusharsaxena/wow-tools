"""config-cache.wtf is merged, not copied (config tools spec CC5). UI-free.

A CVar on the knowledge base's state list (core.kb.is_state_cvar: progress, history, IDs, UI bookkeeping) is the
target's own; every other CVar is a preference. The result is the target's file with its preferences made exactly
the source's: a preference the source sets gets the source's value (left untouched when the client already reads
that value), one only the target sets is removed, one only the source sets is appended in the source's order. The
target's state lines, other lines and line endings stay byte for byte, in place. With no target file the result is
the source's file without its state lines. CVar names match case-insensitively, as the client reads them.
"""
from __future__ import annotations

from wowtools.core.cvarfile import apply_cvar_changes, parse_cvars
from wowtools.core.kb import is_state_cvar

__all__ = ["merge_config"]


def merge_config(source: bytes, target: bytes | None) -> bytes:
    """The target's config-cache.wtf after a copy from `source` (see the module docstring)."""
    parsed_source = parse_cvars(source)
    if target is None:
        state = {line.name for line in parsed_source.lines if is_state_cvar(line.name)}
        return apply_cvar_changes(source, parsed_source, {}, state)
    preferences: dict[str, tuple[str, str]] = {}  # casefolded name -> (source spelling, the value the client reads)
    for line in parsed_source.lines:
        if not is_state_cvar(line.name):
            key = line.name.casefold()
            preferences[key] = (preferences.get(key, (line.name,))[0], line.value)
    parsed_target = parse_cvars(target)
    sets = {name: value for key, (name, value) in preferences.items() if parsed_target.get(name) != value}
    removes = {line.name.casefold() for line in parsed_target.lines
               if not is_state_cvar(line.name) and line.name.casefold() not in preferences}
    return apply_cvar_changes(target, parsed_target, sets, removes)
